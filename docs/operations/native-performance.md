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

Run from services/frontend after a source-bound production build:

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
The corrected diagnostic maintained 535 DOM nodes over the final 50-remount run;
previous failing attempts and reference paths remain in the external evidence.
