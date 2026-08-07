# Spatial Plan 05 Admin-1 and prefetch canary evidence

Date: 2026-08-07
Catalog revision: `spatial-v1-e76a16bff799`
Configuration: `VITE_SPATIAL_SCOPE_ENABLED=true`

This is the local Slice-5 acceptance run for the reviewed Admin-1 catalog,
shared hover/click loads, bounded caches, and the real Cesium presentation path.
It permits Phase C/default-on review; it does not authorize Plan-05D legacy
deletion. The browser run used Firefox 153.0.3 on Linux with WebGL2.

## Catalog evidence

The immutable catalog contains 204 scopes, including all 27 direct Ukrainian
Admin-1 children selected by the declarative catalog plan. Each Admin-1 scope has
canonical lineage, a regional outline, strict containment, and a working direct
deep link. Donetsk resolved cold as
`admin1:iso3166-2:UA-14` with parent `country:UKR`, 2/2 primitives ready, and no
retained staging container or waiter.

`spatial_catalog verify` and `spatial_catalog audit` passed:

| Metric | Observed | Limit |
|---|---:|---:|
| Assets | 68 | — |
| Catalog bytes | 5,355,159 | 26,214,400 |
| Largest wire asset | 820,372 | 4,194,304 |
| Largest estimated asset heap | 2,654,336 | 16,777,216 |
| Largest asset vertex count | 41,260 | 50,000 (regional LOD) |
| Containment coverage | 38/38 pass | 28 mandatory |
| Maximum containment error | 0 m | 50 m |

Two independent offline builds and the published workspace catalog were
byte-identical under recursive comparison.

## Real-browser performance

All 27 Admin-1 deep transitions were run cold against the local backend:

| Timing | p95 | Maximum | Gate |
|---|---:|---:|---:|
| Semantic resolve/commit | 120 ms | 591 ms | — |
| Visual boundary ready | 292 ms | 641 ms | < 800 ms |

The isolated warm Core-Commit run completed 12/12 transitions in 7–20 ms
(12.7 ms mean), below the 50-ms gate. A separate 100-transition
`world ↔ country:UKR ↔ admin1:iso3166-2:UA-14` soak, deliberately run while camera flights
continued, recorded cached semantic p95 48 ms and visual p95 555 ms.

Firefox does not expose the Long Tasks API. The canary therefore records the
application-owned geometry conversion chunks directly. Across the soak and the
isolated commits it observed 349 chunks, a 6-ms maximum, and zero chunks over
50 ms. Cesium geometry combination remained asynchronous.

## Bounded lifecycle counters

The 100-transition soak returned every retained counter to its warmed baseline:

| Counter | Baseline | After 100 |
|---|---:|---:|
| Active asset leases | 0 | 0 |
| Decoded cache entries | 5 | 5 |
| Estimated decoded bytes | 4,181,632 | 4,181,632 |
| Asset in-flight loads | 0 | 0 |
| Metadata entries | 4 | 4 |
| Metadata bytes | 5,004 | 5,004 |
| Metadata in-flight loads | 0 | 0 |
| Active containers | 1 | 1 |
| Scope primitives | 2 | 2 |
| Camera listeners | 1 | 1 |
| Post-render waiters | 0 | 0 |
| Staging containers | 0 | 0 |

Observed high-water stayed bounded: 8 decoded entries across the cold run
(configured maximum 8), 4,181,632 decoded bytes (64-MiB maximum), 28 metadata
entries/38,109 bytes in the all-Admin-1 cold run (256 entries/128-MiB maximum),
two Cesium containers, and five primitives during an atomic swap. No monotonic
lease, cache, primitive, listener, waiter, or staging growth was observed.

## Quality gates

- Backend: 505 tests passed; Ruff and strict Mypy passed.
- Data ingestion: 1,259 passed, 1 explicitly skipped, 17 deselected; Ruff passed.
- Frontend: 551/551 tests passed both flag-off and flag-on; ESLint and TypeScript
  passed; both production builds completed.

The frontend install reported the repository's existing npm audit findings
(1 low, 1 moderate, 6 high); Plan 05 did not change dependency versions.
