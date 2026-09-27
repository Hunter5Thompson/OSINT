# HN-I04 incident mutation transaction design

**State:** Senior design and implementation review approved on 2026-09-27. Both
subruns completed in commit `12b4842` (PR #133, merge pending). Independent validation:
729 backend tests with `NEO4J_URL=bolt://127.0.0.1:1`, 12 isolated real Neo4j tests,
Ruff, Mypy and diff checks passed. No outstanding review findings.

## Transaction contract

Each public store mutation creates its operation ID and immutable inputs once, before
calling `session.execute_write`. The managed callback may run repeatedly, but reuses
those exact inputs and does not publish events, alter caller-owned collections, or
generate timestamps/IDs. It first executes a parameterized, target-specific lock query
on `(:Incident {id: $incident_id})` using `SET` followed by `REMOVE`, fully consumes
that result, then reads the current record in the same transaction. It computes and
writes the mutation before the callback returns and the managed transaction commits.
Neo4j retains the acquired write lock until commit or rollback. Missing target means
`not_found`.

The current status, timeline, severity, sources, hints, and applied operation receipts
are read only after acquiring the lock. `applied_mutation_ids` is an internal list on
the Incident node; absent properties on old nodes are treated as empty. The ID is
stored atomically with each mutation. A callback replay with the same ID returns the
current record as `applied` without appending again. This list grows alongside timeline
mutations; no migration is required.

`MutationResult` carries `applied`, `unchanged`, or `not_found` and the current Incident
when one exists. `apply_signal_update` and `append_timeline_event` act only on OPEN
records. Signal severity is `max(current, incoming)`; sources and hints are ordered
unions of locked current values and incoming values. Timeline JSON is extended from
the locked current timeline. Their deterministic parameterized UPDATE never uses
`MERGE`, never writes status or closed time, and never rewrites location properties or
Geo relationships.

`close_incident` rejects `IncidentStatus.OPEN` with `ValueError`. From OPEN, it sets the
requested terminal status and close time. Repeating the same target or requesting a
different terminal transition on a terminal record returns `unchanged` and that
current record; no transition is reopened.

## Caller behavior

- `ClusterStore.handle` publishes `incident.update` only for `applied` with a returned
  OPEN record. Under its own lock it increments the current hit count and sets local
  severity to `max(local current severity, returned DB severity)`, so an earlier-
  returning lower update cannot downgrade local state.
- Silence and promote routes keep their existing response shape: `not_found` is HTTP
  404; both `applied` and `unchanged` return the current Incident as HTTP 200. They
  publish SSE and call `mark_silenced` / `mark_promoted` only for `applied` and the
  matching returned status.
- The promoter sweeper publishes `incident.close` and drops the cluster only for an
  `applied` close whose returned status is CLOSED. An `unchanged` CLOSED result can
  clean up the stale local cluster without a close event. An `unchanged` PROMOTED or
  SILENCED result synchronizes local status without calling `mark_*` (which would
  create a new cooldown) or dropping that active state; it cannot produce a close
  event.
- `append_timeline_event` moves to the same locked mutation basis. `delete_incident`
  stays a boolean `MATCH`/`DELETE` operation; it cannot recreate a missing node.
- Event publication remains outside the transaction callback and happens only after
  `execute_write` returns successfully. This is not an outbox or a process-crash
  exactly-once guarantee.

## Database race proof

The real Neo4j test lives in `services/backend/integration_tests/`, outside the normal
`testpaths = ["tests"]`, and runs explicitly in a dedicated CI service job and by an
explicit local command. Both paths require `HN_TEST_NEO4J_URI` and
`HN_TEST_NEO4J_PASSWORD`; missing settings or a missing `HNTestInstance` marker are
hard failures. The test creates unique IDs and deletes only those IDs. It never imports
or uses the application's default Neo4j settings/driver and never wipes a database.

Two independent sessions use barriers and transaction metadata. The test polls
`SHOW TRANSACTIONS` by its unique metadata tag to prove that the second transaction is
blocked by the first Incident lock before releasing the first transaction. Coverage:
Update versus Silence/Close/Promote in both lock-winning orders, two concurrent
updates with descending severity, two terminal requests, callback rollback replay,
commit-ack replay across two committed managed transactions, missing Incident, and
preservation of existing Geo node and relationship identities. The original unsafe
read-then-whole-record-write implementation was separately exercised as a baseline
negative control and lost one of two concurrent timeline events; that control is
recorded outside the continuing positive regression suite. CI bootstraps the marker
on its own Neo4j 5.26.23 service before running the explicit integration test.

## References

- [Neo4j concurrent data access and write locks](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/)
- [Neo4j Python managed transactions and callback retries](https://neo4j.com/docs/python-manual/current/transactions/)
