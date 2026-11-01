# Native rendering acceptance

The historical G07 ~1.06 FPS result is not a valid scene-frame measurement on
the reproduced Chromium/Cesium combination. The selected CDP range is marked
`isBlockCoverage: false`: it counts a function rather than the actual executed
postRender call. Simultaneous public event counting showed 603 scene frames in
10.029 seconds while that coverage range counted only 330 calls. The original
30-second method still reports ~32 calls; neither count represents actual frames.
The artifacts and historical failures are retained, not rewritten as passes.

The replacement probe attaches to the mounted widget once through a CDP pause,
then uses Cesium's public `scene.postRender` event. It does not replace render
functions, clocks, shaders or scheduling. It detaches the debugger before warmup.
The application PerformanceGuard now uses this same public event instead of RAF
callbacks and divides by actual elapsed time. Hidden tabs and intentional
on-demand idle periods do not cause false degradation. See
[Cesium Scene events and request rendering](https://cesium.com/learn/cesiumjs/ref-doc/Scene.html).

Prefer extracting `/usr/share/nginx/html` from the reviewed frontend image into
the test server's `dist` directory, preserving the previous local build elsewhere.
Hash every extracted file and verify `/build-info.json` against the image's OCI
revision. This avoids qualifying a local build with different feature flags.
A local build alternative must explicitly use `VITE_SPATIAL_SCOPE_ENABLED=true`
and `ODIN_BUILD_REVISION=<full-code-sha>`; it is not image identity evidence.
Run from services/frontend against the frozen, source-bound production files:

```bash
ODIN_BROWSER_PORT=15301 ODIN_BROWSER_ARTIFACTS=/data/<run>/native \
PLAYWRIGHT_BROWSERS_PATH=/data/odin-caches/playwright \
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia \
__VK_LAYER_NV_optimus=NVIDIA_only \
npm run test:browser -- --config playwright.native.config.ts
```

The fixture requires an RTX 5090 renderer (no software fallback), 1920x1080,
10,000 synthetic co-located flights, 10s warmup, three 30s open-ended camera drags,
then a separate 10s idle sample. Each active interval must deliver >=30 actual
frames/s and P95 scene-frame gap <=33.3ms; 60 FPS is the optimization target.
Twenty programmatic layer actions measure state update through two RAF callbacks
with P95 <=200ms, separately from physical input and network latency. UI state is
asserted after every action. Do not overlap a qualifying FPS run with other GPU
browser workloads. Record build/engine/driver identity and host/model load.

`playwright.soak.config.ts` explicitly runs a separate 60-minute route/time/layer
soak. It never silently skips in CI. It records retained JS heap after collection
and DOM counters at a consistent mounted route, with a predeclared 5 MiB retained
heap / 50-node growth ceiling across warm five-sample windows. Host GPU/process
memory must be observed separately. These bounds detect specified regressions,
not a proof of zero leaks in every resource or workload.

Neither fixture qualifies live source density, photorealistic remote tiles,
factual retrieval, headed-display latency, or operator readability. The three
human workflow judgments remain explicit in the dated acceptance report.

## Viewer lifetime regression

A 50-remount native test compares retained heap and DOM after collection. Heap
snapshots demonstrated two Cesium 1.142.0 leaks: the global 16x16 terrain index
cache retained destroyed contexts through GPU buffer objects, and CreditDisplay
appended a stylesheet per construction without removing it. Cleanup only removes
the destroyed viewer's own context entries and synchronously created credit
styles; foreign contexts/styles remain intact. The terrain compatibility seam is
version-pinned and fails visibly on a changed internal contract. It does not
claim cleanup for remote terrain of other dimensions. Requalify on Cesium upgrade.
The corrected diagnostic returned to 535 DOM nodes, with transient spikes but no
accumulating trend across 50 remounts. Previous failing attempts and reference
paths remain in the external evidence. The final image-backed 60-minute soak had
exactly 1361 DOM nodes in all 142 collected samples.

## Context loss is a failure, not a slower frame sample

The first image-backed soak failed after 28 cycles / about 11.85 minutes. The
kernel recorded NVIDIA Xid 13 for the Chrome GPU process at 2026-11-01 16:25:52 UTC;
WebGL was lost and Cesium stopped with a RangeError. This establishes the observed
GPU/browser failure, not its ultimate cause or independence from the workload.
The interrupted run is preserved as FAIL, never promoted to a 60-minute pass.

The viewer now stops its loop and presents a controlled reload action on context
loss or render error. It removes old listeners/resources and reapplies shaders
when rebuilding. An injected native context-loss test verifies resumed rendering
and preserved layer selection. This does not repair or certify the GPU driver.
Native actions have a 15-second deadline; the soak checks both render-error UI
and captured context-loss events and records browser warning/error messages.

## Broader process-memory gate remains open

The e1c46a6 image completed 60.11 minutes / 142 cycles with stable DOM and a
+2.79 MiB retained JS heap warm delta. That is the declared JS/DOM gate only.
Browser-process RSS rose +148.2 MiB between the 10–15 and 55–60 minute windows.
A minimal same-distribution Cesium viewer without ODIN reproduced native browser
retention; page closure reclaimed it, explicit WebGL context loss did not.
HTTP/history-only, plain WebGL and worker-blob controls are recorded in the
[dated review](../reviews/2026-11-01-quality.md). The full "no continuing memory
rise" criterion remains open; no native allocator root cause or fix is claimed.
`native.workers.perf.ts` separately checks blob ownership and records Linux
browser RSS plus a pressure diagnostic; it does not silently certify RSS bounds.
