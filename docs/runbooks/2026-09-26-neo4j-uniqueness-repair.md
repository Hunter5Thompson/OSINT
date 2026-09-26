# Neo4j uniqueness repair — 2026-09-26

## Outcome and scope

The authorized production repair completed with `incident_id_unique`,
`event_key_unique`, and `entity_name_type_unique` active. All three constraints
rejected deliberate duplicate inserts with `ConstraintValidationFailed` in rolled
back transactions. Their backing indexes are ONLINE. ODIN services were resumed;
the six Entity lookups, graph neighbors, and event endpoints returned HTTP 200.

This is structural integrity and preservation evidence, **not a claim that every
historical extraction is factually correct or every real-world identity resolved**.

## Backup and original state

Evidence directory: `/data/odin-backups/neo4j-repair-20260926/`.

- Paused `odin-data-ingestion-spark`, `osint-backend-1`, `osint-intelligence-1`.
- Stopped `osint-neo4j-1`; dumped both `neo4j` and `system` databases.
- `neo4j.dump`, `system.dump`, and `apoc.jar` have SHA-256 receipts in `SHA256SUMS`.
- Restored both databases into an isolated container/data directory and verified
  Neo4j **5.26.23**, APOC **5.26.23**, and matching Event baseline properties.
- Original Neo4j image:
  `sha256:40bf5ae9282213087e4d6036aab3ec443fe9c974d3dd4f14a11892c63157238f`.
- GPU/model services, Qdrant, and unrelated worktree files were not changed.

Production remained free of application writes throughout migration and constraint
installation. Dumps are offline full backups, not per-group undo operations.
Restoring them later would also revert subsequent legitimate Neo4j writes.

## Why the old apply was unsafe

The reported 74,817 duplicates in 8,272 groups counted repeated Document rows as
independent Event nodes. There were 128 Events linked to multiple Document nodes;
each of those Document pairs shared URL and title. Corrected candidate counts were
74,689 extra nodes in 8,165 groups, but a shared key was not sufficient evidence of
identity. The largest candidate group contained 1,559 PortWatch reports spanning
different dates behind the same ArcGIS endpoint.

Also, 1,886 existing keys differed from a recomputation using current Document
metadata. Existing keys are now preserved: Document titles change and collectors
can provide their own content hashes. Lowest internal node ID is not proof of age.

## Conservative resolution

| Metric | Before | After, with writers paused |
|---|---:|---:|
| All graph nodes | 1,724,131 | 1,721,715 |
| All graph relationships | 38,238,574 | 38,238,574 |
| Non-GDELT Events | 255,542 | 253,132 |
| Non-GDELT Events with keys | 125,555 | 253,132 |
| Exact Entity name/type duplicate groups | 6 | 0 |

- Merged **2,410** redundant Event nodes in **2,143** groups with equal extraction
  properties, excluding only `updated_at` and the key itself.
- Preserved all relationship instances, directions, endpoints after survivor
  mapping, and properties (`mergeRels:false`). Parallel evidence edges are
  intentionally retained, not silently collapsed.
- Archived original nodes, relationships, and key assignments before mutation with
  exclusive file creation and fsync. Each merge survivor also contains
  `repair_merged_nodes_json`, including the original property snapshots.
- All 4,553 original Event nodes participating in merges and all 12 original
  Entity nodes remain represented in those in-graph archives as well as the dump.
- Missing documents/URLs, conflicting document identities, conflicting existing
  keys, stale write inputs, and incomplete postflight checks fail closed.
- The precondition uses Neo4j's own serialized property snapshots: driver
  round-trips can represent a stored `Z` datetime as `[UTC]`, causing false
  inequality in native map comparisons. This was found and fixed on the clone;
  the clone was then restored afresh and the complete procedure repeated.

### Entity decisions

`entity-decisions.json` and `entities-before.json` contain the reviewed IDs,
properties, source URLs, and relationships. All six merges were evidence-backed:

- Alex Scheel and Marilyn Strickland: identical Intercept article/context per pair.
- Helen McEntee: identical European Parliament committee article per pair.
- F-35: both describe the aircraft type; shared Claim neighbors and overlapping
  articles, with no individual airframe identifier.
- Houthi: shared Red Sea shipping Claim, Yemen alias and UCDP context.
- Postal Service: both cite the same two Brookings articles, including the USPS
  financial-condition article; both refer to the United States Postal Service.

Entity aliases were unioned; confidence retained its maximum; first/last seen
retain the full range. All other conflicting original values remain archived.

### Unresolved historical identity remains explicit

**87,107 retained Events** carry `repair_identity_status = 'unresolved'`:

| Reason | Nodes |
|---|---:|
| Shared API endpoint without original record identity | 82,934 |
| Different extraction facts under the same title/context | 4,073 |
| Distinct existing source keys | 100 |

Legacy events without a defensible canonical identity receive unique `legacy:`
keys. These satisfy uniqueness without pretending that they identify a resolved
real-world event. Existing keys are not overwritten. The markers do **not**
automatically exclude these Events from existing read APIs. Historical PortWatch
extractions therefore still need source-backed semantic review; this repair does
not certify their content. No port/date identity was guessed from narrative text.

Forward protection: PortWatch daily numeric flows already bypass LLM extraction
in the deployed collector. New narrative disruptions now use
`#eventid=<stable source ID>` in Document URLs and reject missing IDs, preventing
unrelated records from sharing a Document node.

## Verification receipts

In the evidence directory:

- `production-verification.json` / `.log`: exact multiset comparison of **367,627**
  Event relationships and **69** affected Entity relationships, global counts,
  surviving properties, preserved original keys, and archived node snapshots.
- `production-entity-properties.log`: aliases, confidence, time ranges, all 12
  original Entity snapshots retained.
- `production-constraints.json`: exact constraint schema and three negative controls.
- `production-event.log`: complete coverage, zero duplicate keys, idempotent re-plan.
- `backend-graph-smoke.json`: six repaired Entity lookups and two graph endpoints.
- `odin-smoke.log`: **24 passed, 0 failed, 1 skipped** (inactive local ingestion
  profile; Spark ingestion is running).
- `service-tests.log`: Data Ingestion **1,502 passed, 1 skipped, 17 deselected**;
  live tests are excluded by the existing pytest configuration.
- `final-targeted-tests.log`: **49 passed**; `lint.log` and `git diff --check` clean.
- `probe.log`: real APOC transaction tests for datetime snapshots, conflicting
  scalar archives, relationship properties, self-loops, and stale-input rejection.
- Red-phase receipts: `tests-red.log`, `portwatch-red.log`, `entity-red.log`.

## Operational reuse

Run commands from `services/data-ingestion`. First pause writers, make and test an
offline dump, then rehearse on a restored isolated database using matching
Neo4j/APOC versions. Configure the target through the normal Neo4j settings.

```bash
uv run python -m migrations.backfill_event_key
uv run python -m migrations.backfill_event_key --apply --archive /data/odin-backups/NEW-RUN/events.jsonl
```

The archive must not already exist. Check the plan and unresolved classifications;
a successful exit does not mean all historical identities are semantically resolved.
Entity repair accepts explicitly reviewed groups of exact element IDs via
`migrations.repair_entity_duplicates.run`; do not replay the broad historical
same-name merge query.

Before `entity_name_type_unique`, inspect the standalone `entity_name_type` index:
it must be RANGE, Entity(name,type), with no owningConstraint. Remove it using
`entity_name_type_drop_index.cypher`, then immediately create the unique constraint
while writers remain paused. Neo4j 5.26 otherwise rejects the new constraint with
`IndexAlreadyExists`. Verify exact schemas and ONLINE indexes before resuming.

The evidence directory includes the exact backup/load logs, operator scripts,
original-to-survivor mappings, runtime metadata, failed rehearsal evidence, and
successful rehearsal/production receipts. The stopped rehearsal container and its
`/data` directories are retained for inspection.

## Runtime deployment

The patched collector is in the source tree and the running ingestion container
(file hash checked). A minimal image derived from the original image was built
without network access and tagged `osint-data-ingestion-spark:neo4j-repair-20260926`
and `:latest` for subsequent recreation. The existing container keeps its original
image ID plus the verified file overlay. Original image retained as
`osint-data-ingestion-spark:before-neo4j-repair-20260926`.

Next semantic work, if undertaken: recover original PortWatch record IDs and valid
source observations before further reconciliation. Do not treat generic endpoint,
matching title, adjacent internal IDs, or the presence of a uniqueness constraint
as proof of factual identity.
