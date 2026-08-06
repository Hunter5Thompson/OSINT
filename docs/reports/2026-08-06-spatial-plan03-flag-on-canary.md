# Spatial Plan 03 flag-on canary evidence

Date: 2026-08-06  
Branch: `feat/spatial-plan03`  
Configuration: `VITE_SPATIAL_SCOPE_ENABLED=true`

This is the deterministic pre-deployment lifecycle canary for Plan 03. It does
not replace the Phase C browser soak. Production remains default-off.

## Reproduction

Run from `services/frontend`:

```bash
VITE_SPATIAL_SCOPE_ENABLED=true npm test -- --run \
  src/spatial/__tests__/httpCatalog.test.ts \
  src/spatial/__tests__/cesiumAdapter.test.ts
VITE_SPATIAL_SCOPE_ENABLED=true npm run build
```

Observed result: 32 focused tests passed and the flag-on production artifact
built successfully.

## Bounded lifecycle counters

The adapter fixture completed 100 committed semantic transitions:

| Counter | Settled value / maximum | After dispose |
|---|---:|---:|
| Mounted scope containers | 1 | 0 |
| Scope primitives | 2 | 0 |
| Post-render listeners | 0 | 0 |
| Camera listeners | 1 | 0 |
| Asset leases acquired / released | 200 / 200 | 200 / 200 |

The same fixture completed 100 alternating camera-LOD swaps with one mounted
container, two settled primitives, at most one transient staging primitive, and
the same canonical pick primitive throughout.

The decoded-asset cache fixture used a one-entry bound and reported:

| Counter | Settled value | After dispose |
|---|---:|---:|
| Decoded entries | 1 | 0 |
| Estimated decoded bytes | 1,728 | 0 |
| Active leases | 0 | 0 |
| In-flight loads | 0 | 0 |
| Configured byte ceiling | 33,554,432 | 33,554,432 |

No monotonic primitive, listener, lease, or decoded-cache growth was observed.
The Plan 03 pre-deployment stop rule therefore did not trigger.
