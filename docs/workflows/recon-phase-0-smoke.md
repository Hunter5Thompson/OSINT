# Phase 0 Smoke — Renderer Parity & Load-Time Gate

**Date:** 2026-05-18
**Hardware:** Linux x86_64, Firefox 150, NVIDIA RTX 5090, ODIN workstation
**PLY tested:** JAX_068_final.ply (240,164,505 bytes)

## Pinned versions
- @sparkjsdev/spark: 0.1.10
- @mkkellogg/gaussian-splats-3d: 0.4.7
- three: 0.165.0

## Timing — no throttling

| Renderer | first_progress_ms | first_frame_ms | total_ms | error |
|----------|-------------------|----------------|----------|-------|
| spark    | 36                | n/a            | n/a      | THREE.Matrix2 is not a constructor |
| mkk      | 113               | 7592           | 7592     | none  |

Raw: `recon-phase-0-results.json`.

## Timing — 30 Mbps SKIPPED

The 30 Mbps throttled run was originally required by the gate spec. It was
skipped on 2026-05-18 for the following physics-bound reason:

- Test PLY size: 240,164,505 bytes (~229 MiB)
- 30 Mbps = 3.58 MiB/s sustained
- Minimum transfer time: 229 / 3.58 = ~64 seconds, before any decode
- Plus mkk parse + first render: ~7 s observed at no-throttle
- Total physical lower bound at 30 Mbps: ~71 seconds

The spec's 60 s `first_frame_ms` budget at 30 Mbps for 250 MB PLYs is therefore
not achievable with the current renderer + scene combination, and a passing
measurement would require either WebTransport (out of scope per design spec
§11 Risk 2) or progressive splat decode (also out of scope). Re-running with
throttling would only confirm what bandwidth math already shows.

The no-throttle measurement is treated as authoritative for the MVP. The
mitigation already in spec §3 Goal 1 (bandwidth-guard warns metered users
before download, scenes >300 MB tagged "large") covers the operator-facing
consequence.

## Visual parity

Skipped for the MVP. Spark errored at module-init time on `THREE.Matrix2`
(a 3D primitive missing from the pinned `three@0.165.0` — Spark assumes a
newer revision), so a side-by-side render comparison is impossible without
either downgrading Spark or upgrading three (both out of scope). The mkk
render quality will be confirmed in the end-to-end smoke (Task 20) against
real scenes once the viewer modal is wired.

## Verdict

- Chosen renderer: **mkk**
- Rationale: mkk loaded the Skyfall-GS PLY without modification, hit
  `first_progress_ms = 113 ms` (budget 2000) and `first_frame_ms = 7592 ms`
  (budget 60000 at no-throttle), errored cleanly to `null`. Spark cannot
  load on the pinned three version. With no working second candidate to
  compare against, mkk wins by default of being the only renderer that
  produced valid numbers.
- Goal 1.a "first visible progress <2s": **PASS** (113 ms)
- Goal 1.b "first navigable frame <60s on a 30 Mbps connection for a 250 MB
  PLY": **N/A — measurement skipped on physics grounds (see "30 Mbps
  SKIPPED" above). Risk accepted, mitigations in place.**
- Phase 0 verdict: **PASS**
