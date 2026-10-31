# Vessel atlas identity regression — 2026-10-30

The full built-browser suite exposed an intermittently missing unknown-course
vessel ring after search camera movement. The assertion and pixel contrast
threshold were preserved. Read-only scene diagnostics established that the
fixture remained inside the viewport (one rendered vessel), projected at
x720/y467.752 on a1440x936 canvas, and eventually reported Billboard.ready=true.
Culling, projection and always disabling depth tests did not explain or reliably
resolve the failure. Temporary diagnostics and the depth override were removed.

The layer rebuilds billboards at camera/degradation refreshes. Passing a cached
HTMLCanvasElement as image still allocates a new Cesium image GUID each time;
its atlas upload repeatedly becomes unready. The new regression test fails on
the first viewport refresh against the previous implementation. A stable public
Billboard.setImage ID now shares the exact icon cache key, preserving the
unknown-course distinction and existing five-degree course quantization.
No private renderer internals or geographic placement changes are involved.

Evidence under /data/odin-plan-20261030/evidence:

- ship-texture-red-identity.log: distinct GUIDs on the first refresh (RED).
- ship-texture-green.log: ten refreshes plus course/unknown distinctions (PASS).
- browser-ship-arrival: previous behavior, three failed fresh runs.
- browser-ship-depth: rejected depth-disable diagnostic, mixed results.
- browser-ship-stable: five fresh uninstrumented runs passed, no retries/skips.
- ship-lint.log and ship-types.log: passed.

The five-run result supports this correction; it does not establish that every
possible renderer/load timing is covered. Full clean-head software and native
functional suites remain separate receipts; no product deployment is included.
