# Spatial Plan 06A Neo4j verification evidence

Date: 2026-08-08
Catalog revision: `spatial-v1-e76a16bff799`
Representative target derivation revision: `spatial-derive-v1-4d1de888e0c7`
Code under test: `9c98376` including the Plan-06A review fix `2aee913`

This is the operator-authorized verification run against the persistent local ODIN
Compose graph selected for Plan 06A. It closes the two previously outstanding
verification activities: applying the additive index migration and collecting real
Neo4j plans, then running and reviewing the spatial backfill in dry-run mode. It does
not approve a data backfill, exact CHRONIK activation, or a production deployment.

## Target and stack

The stack ran through `./odin.sh up interactive-spark`. The ingestion image present
before the run predated the Plan-06A CLI and migration runner, so
`data-ingestion-spark` was rebuilt from the current branch and recreated before the
verification. The final `./odin.sh smoke` result was 14 passed, 0 failed and 1
skipped; all ten containers belonging to the profile were running afterward.

The selected graph was:

- Neo4j 5.26.23 Community in `osint-neo4j-1`;
- `bolt://neo4j:7687` inside Compose and `bolt://localhost:7687` from the host;
- persistent volume `osint_neo4j-data` mounted at `/data`.

With the ingestion scheduler stopped for a stable snapshot, the graph contained
1,404,220 nodes, 14,996 `:Location` nodes and 351,772 `:Event` nodes. The scheduler
was restarted after the evidence was collected, so these are snapshot counts rather
than permanent high-water marks.

## Migration and query-plan evidence

The current `gdelt_raw.migrations.apply.apply_phase2()` runner applied both its GDELT
index file and the centrally owned spatial index migration. Every spatial index then
reported `ONLINE` with 100 percent population:

| Index | Type | Properties |
|---|---|---|
| `location_country_scope_derivation` | RANGE | `country_scope_key`, `spatial_derivation_revision` |
| `location_admin1_scope_derivation` | RANGE | `admin1_scope_key`, `spatial_derivation_revision` |
| `location_admin2_scope_derivation` | RANGE | `admin2_scope_key`, `spatial_derivation_revision` |
| `location_geo` | POINT | `geo` |

The read-only `spatial-index-smoke` command returned
`all_expected_indexes_used=true`. Neo4j selected a `NodeIndexSeek` over the expected
two-column RANGE index for each probe:

| Scope kind | Selected index | Indexed predicates |
|---|---|---|
| Country | `location_country_scope_derivation` | `country_scope_key`, `spatial_derivation_revision` |
| Admin-1 | `location_admin1_scope_derivation` | `admin1_scope_key`, `spatial_derivation_revision` |
| Admin-2 | `location_admin2_scope_derivation` | `admin2_scope_key`, `spatial_derivation_revision` |

`spatial_conflict = false` remained a post-seek `Filter`; the composite seek itself
was driven by scope key plus derivation revision. Conflicts additionally carry a null
derivation revision and therefore cannot satisfy either exact composite predicate.
The probes used `EXPLAIN`, so they executed neither a data read nor a write.

The focused migration, plan-smoke, batch and CLI suites also passed 27/27 immediately
before the operational run.

## Backfill dry-run evidence

The ingestion scheduler was stopped while all four supported lanes were scanned, so
their content-addressed reports describe one stable graph state. Each job used batch
size 500, the catalog and target revisions named above, a fresh checkpoint path and
`--dry-run`. No checkpoint file was created. Before and after the runs, the lane node
counts and the counts carrying catalog/derivation revisions were identical.

| Lane | Total | Already | Resolvable | Unresolved | Conflict | Invalid | Target mismatch | Planned | Applied |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `backend_incident` | 2 | 0 | 1 | 1 | 0 | 0 | 0 | 1 | 0 |
| `gdelt_raw` | 5,756 | 0 | 16 | 140 | 22 | 0 | 5,578 | 38 | 0 |
| `military_aircraft` | 7 | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 0 |
| `rss_pipeline` | 134 | 0 | 0 | 10 | 0 | 0 | 124 | 0 | 0 |

| Lane | Addressable | Country-scoped | Coverage | Stale-compatible | Unstable IDs | Complete |
|---|---:|---:|---:|---:|---:|---|
| `backend_incident` | 1 | 1 | 100% | 0% | 0 | yes |
| `gdelt_raw` | 5,616 | 5,594 | 99.61% | 0% | 0 | yes |
| `military_aircraft` | 0 | 0 | n/a | 0% | 9 | no |
| `rss_pipeline` | 124 | 124 | 100% | 0% | 0 | yes |

The implementation encodes an empty addressable denominator as a numeric coverage
ratio of `0.0`; the table renders the military value as `n/a` so it is not mistaken
for measured zero-percent coverage. The source/code-system accounting was:

- `backend_incident`: 2 `incident_report`, code system `none`;
- `gdelt_raw`: 5,756 `gdelt_actiongeo`, code system `gdelt-gec`;
- `military_aircraft`: 7 `military_aircraft`, code system `none`;
- `rss_pipeline`: 131 `country_centroid` plus 3 `source_country_code`, all `iso2`.

Report fingerprints:

- [`backend_incident`](2026-08-08-spatial-plan06a-backend-incident-dry-run.json):
  `e61525110929f2a33c5fd0294659188cdeb90ddda4289ce5bd8bf2c5a978201c`
- [`gdelt_raw`](2026-08-08-spatial-plan06a-gdelt-raw-dry-run.json):
  `442a93206198500267392df69a737d5b53147291e9c9d6efdb1e046af8de41ad`
- [`military_aircraft`](2026-08-08-spatial-plan06a-military-aircraft-dry-run.json):
  `6637966afbc1624b6f94b9202476a290836a60dcfb5ad7d670d036cdd8f0fc82`
- [`rss_pipeline`](2026-08-08-spatial-plan06a-rss-pipeline-dry-run.json):
  `0aa9106219faed9fc4571a2f8ac9f1406d4ae3f5e3a0e8f9cab1009bb0df3796`

The high target-mismatch counts are expected for this representative single-revision
job: the immutable catalog contains 204 independently derived scope revisions, while
the selected target belongs to `admin1:iso3166-2:UA-14`. They are not silently
treated as writes for another revision.

## Gate decision

The operational evidence is sufficient to close both Plan-06A VERIFY checkboxes:
the real migration/plans and a real, reviewed, zero-write dry-run now exist. It is not
sufficient to open exact queries or approve a backfill apply.

The remaining blockers are explicit:

- nine legacy military-aircraft Locations lack stable IDs, making that lane's report
  incomplete; its seven keyed observations are unresolved by the currently installed
  containment catalog;
- the backend incident forward writer remains an unsupported cross-service lane and
  the two-record snapshot is not promotion evidence;
- the 140 unresolved GDELT and 10 unresolved RSS records remain fail-closed and need
  outcome review before lane promotion;
- only one representative target revision was dry-run; a real initial apply requires
  reviewed jobs for every intended target revision;
- no backup/restore point was created and no data apply was attempted;
- no production writer deployment or exact CHRONIK activation occurred.

The additive indexes remain installed, the full ODIN stack is running again, and the
exact activation gate remains closed.
