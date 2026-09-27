# Verified spatial live cutover — 2026-09-27

The coordinated cutover is complete. Code release
`466ba3e5429ae234eabd4e50ee2cda81a619bf0b` is deployed; backend, intelligence,
Spark ingestion and the existing standalone GDELT backfill are running again.
The active catalog is `spatial-v1-2ff6da288a58` (176 country containment scopes,
220 scopes total). The measured Qdrant projection is
`spatial-projection-v1-bd57faf06c44`.

## Reviewed changes

- [PR #119](https://github.com/Hunter5Thompson/OSINT/pull/119): audit remediation,
  catalog coverage, source adapters, assignment compatibility and migration engines.
- [PR #121](https://github.com/Hunter5Thompson/OSINT/pull/121): live preview exposed
  a validator rejecting the established parent-before-child pair-token order.
- [PR #122](https://github.com/Hunter5Thompson/OSINT/pull/122): distinguish historical
  theatre aggregates from aircraft observations missing stable cursor IDs.

All twelve checks passed on each merged code PR. The token regression was red
before its fix; the final intelligence suite passed 489 tests. The cursor predicate
had two failing cases before its fix and six passing read-only Neo4j cases after it.
The existing 25 batch/scheduler tests also passed. Both follow-up fixes landed
before re-normalization writes began.

## Applied and verified

- Neo4j: 17,448 stable location records scanned across five lanes; 17,155 updates.
- Qdrant: 1,923,721 points updated across seven source lanes.
- Fresh full-lane verification: **zero remaining writes** in both stores.
- Frozen inventory preserved: **2,627,173 nodes**, **67,019,865 relationships**,
  **1,967,003 `odin_intel` points**, and **6 smoke-test points**.
- Across 700 points sampled from all seven lanes, vectors and every non-projection
  payload field remained exactly equal to the captured before-state.
- Outside these lanes, a read-only inventory found zero nonempty spatial audit
  arrays, zero about-token arrays and zero occurrence-token arrays before resuming
  writers. The other 43,282 points had no existing spatial admissions to rotate.

Each apply required a fresh matching input/projection fingerprint. The operator
used six CPU workers and a bounded coordinate cache for the immutable target;
complete fingerprints matched the uncached approved previews. Verification of
finished lanes overlapped the tail of apply only after proving the source filters
disjoint; each verification waited for its lane's complete durable apply report.
Coverage publication waited for the successful complete apply and verification.

### Aircraft labels

All **4,170** observation Locations have correct country/`unresolved` names,
no stale `region`, and saved original label values. **3,642** have a country;
**528** remain unresolved. Of the 697 previously named `ukraine`, 606 now resolve
to ROU, 69 to POL, 8 to HUN, 3 to BLR, one each to SVK and SRB; 9 remain unresolved.

The nine historical theatre aggregate nodes and their **14,654 `SPOTTED_AT`
relationships** remain intact. Their edge coordinates are retained as evidence;
materializing those historical edges as observation Locations is a separate job.

## Measured Qdrant coverage

These are stored-state counts from the final verification, before writers resumed.
There are zero stale, unprojected or inconsistent points in the seven lanes.
Filterable points total **190,743**.

| Source | Points | Filterable | Conflict | Audit only | Unsupported |
|---|---:|---:|---:|---:|---:|
| eonet | 916 | 861 | 0 | 54 | 1 |
| firms | 161,701 | 152,365 | 1,775 | 7,561 | 0 |
| gdacs | 307 | 132 | 0 | 93 | 82 |
| ucdp | 1,805 | 0 | 0 | 0 | 1,805 |
| usgs | 1,026 | 238 | 0 | 788 | 0 |
| gdelt_gkg | 1,757,183 | 37,147 | 616 | 1,719,420 | 0 |
| notebooklm | 783 | 0 | 0 | 783 | 0 |

`audit_only` retains evidence without an admitted spatial token. Missing source
precision leaves all existing UCDP points unsupported. The historical NotebookLM
records have no admitted about assignments. Most GDELT points lack admissible
linked occurrence evidence or resolvable geography. Recovering absent provenance
requires source replay; re-normalization does not manufacture it.

The prose-search policy remains RSS (including fulltext), `suv_structured`,
NotebookLM and vetted Telegram. FIRMS/GDELT/UCDP/GDACS/EONET/USGS observations are
consumed through the graph. A direct active-revision Iraq
scope count returned **30 Neo4j Locations and 14,303 Qdrant occurrence points**;
the Qdrant number describes storage admission, not prose-tool corpus membership.

## Runtime acceptance

- Both reader health endpoints returned HTTP 200.
- Active IRQ/UKR and previous-served UKR references resolved; retired `e76…`
  returned HTTP 409.
- A real `/api/intel/query` request for historical Iraq observations completed
  with a nonempty analysis and three tool calls. Both Qdrant and Neo4j marked the
  active scope and `occurrence` relation as applied. The prose search returned no
  eligible documents and explicitly reported partial coverage; graph retrieval
  returned observations. Scoped graph-neighborhood context remains omitted by policy.
- `./odin.sh smoke`: **24 passed, 0 failed, 1 skipped** after genuine GDELT/RSS
  collection cycles. An earlier immediate post-start smoke caught their stale
  pre-maintenance heartbeat; no freshness timestamps were fabricated.
- Reader pair started around **02:50 UTC**; writers resumed around **02:56 UTC**.
  Subsequent ingestion naturally changes counts beyond the frozen verification.

Measured coverage is published at
`/data/odin-runtime/spatial/qdrant-coverage.json`, mounted read-only into intelligence
at `/run/spatial-coverage/qdrant-coverage.json` through
`SPATIAL_COVERAGE_SNAPSHOT_PATH`. Preserve this mount/environment when recreating
that service. Intelligence uses `odin-intelligence:spatial-b619ad7`; both ingestion
containers use `odin-ingestion:spatial-final-20260927`. Backend uses its original
image with the updated app/data bind mounts. Existing tracing and runtime settings
were preserved.

## Rollback and operator evidence

Private evidence directory:
`/data/odin-backups/spatial-cutover-20260927T003349Z`.
It contains the full Neo4j/system dumps, Qdrant snapshots including vectors,
SHA-256 manifests, approved dry-runs, durable checkpoints, apply/verification
reports, before-state container configuration, runtime checks and smoke logs.
Both database backups were restored into isolated storage and their complete
node/relationship/point counts matched before apply. Original containers and image
tags remain stopped/retained for rollback. Restore matching data, code and pointer
together using the [deployment runbook](../runbooks/spatial-intelligence-contract-deploy.md).
Private container configuration contains credentials and is not committed.
Temporary server-side Qdrant snapshot copies were removed from the system SSD
after checking the restored backups on `/data`; those durable backup files remain.

The previous served catalog is `spatial-v1-0180e188358c`; `e76…` is retired.
Old assignments are not automatically compatible with the new catalog. In saved
frontend history select **Aktiven Kartenstand laden**; a browser reload alone does
not migrate a pinned reference. Geometry remains Natural Earth 1:110m for the 176
catalog countries, with the declared boundary policy and its resolution limits.
