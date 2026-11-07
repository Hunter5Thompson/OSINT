# Runtime readiness and resource bounds

`GET /api/health` remains process liveness. `GET /api/health/ready` probes Neo4j
and the configured Qdrant collection/schema as required dependencies, Redis as
optional. Probes run concurrently with a two-second bound: unavailable required
dependencies return 503; a missing cache returns 200/degraded. This does not
measure publisher freshness, model quality or external factual truth.

Redis retains its client after connection failure. Operations have a one-second
bound; a five-second cooldown and one recovery probe avoid a concurrent retry
stampede. Cache misses remain safe while recovery runs.

Manual RAG ingestion returns 501 and creates no job. Statistics use exact Qdrant
counts; failed/invalid responses retain null plus unavailable, distinct from a
successful zero. Each known source family has independent count availability.

Timeline histogram templates aggregate distinct matching events in Neo4j without
an event LIMIT. Result rows are bounded by requested buckets (maximum 240).
Each row contains weighted raw category/severity groups, normalized using the
shared Python functions. Bytes still depend on distinct category/severity pairs;
this is not a constant-byte or bounded database-scan claim. Exact spatial reads
remain in one snapshot with their separate coverage accounting. Temporal bounds,
sub-millisecond truncation, dates before 1970 and dateline filters are tested.
A marked disposable Neo4j benchmark seeds 20,000 events per case and compares all
buckets to the previous Python algorithm across twelve global/spatial/time cases.
All matched; the global case transferred four rows instead of 15,000.

The map leases at most one paused, detached Cesium Viewer between route visits.
Healthy reuse avoids repeated native context allocation. Token changes, rendering
failure and context loss discard the lease. Layer hooks still unmount normally.
This bounds ordinary navigation; it does not fix Chromium context disposal or
qualify arbitrarily repeated device failures.

Two diagnostic OpenGL builds failed with context loss and NVIDIA Xid 31/69.
Artifact comparison subsequently showed that those local builds, and an initial
Vulkan diagnostic run, omitted `VITE_SPATIAL_SCOPE_ENABLED=true`. They do not
qualify the spatial-enabled release. The first Vulkan run was stopped around
minute 49; no result was transferred to release acceptance.

All 411 served files were copied directly from the immutable candidate image and
independently hash-matched. The four native tests and full 60-minute soak were
repeated against those exact assets. The release verdict passes with zero render
errors/context losses/kernel Xids and unchanged thresholds. The native fixture
now requires an observed spatial-catalog request, so the disabled build is rejected.
This is qualification of the documented Vulkan profile, not an OpenGL or general
driver-fix claim. See the [closure report](../reviews/2026-11-07-reliability-closure.md).

Native acceptance is separate from JS heap. The complete 60-minute dense native
soak compares medians at minutes 10–15 and 55–60: browser RSS growth <32 MiB and
slope <0.5 MiB/min, GPU process RSS growth <64 MiB, renderer RSS growth <128 MiB;
existing JS heap (<5 MiB) and DOM (<50 nodes) gates remain. Errors/context losses
must be zero. Shared device-wide VRAM is diagnostic, not app-owned memory.
The source/assets were frozen before the run. Final verdict and measurements:
`/data/odin-reliability-20261106/p5/native-verdict.json` (passed).
Browser/GPU-process/renderer RSS deltas were -6.9/+4.7/+21.4 MiB; JS heap +1.96 MiB,
DOM +0, browser slope -0.209 MiB/min. Shared device VRAM is not included.


## Native workstation browser

The shared `services/frontend/scripts/native-browser-profile.json` pins Chromium
156.0.8078.4 and native NVIDIA Vulkan 1.4.329 on this RTX 5090. The native tests and
the operator launcher consume the same graphics flags. This operating configuration
passed the exact-image native qualification; it
does not qualify the spatial-enabled OpenGL path or identify the cause of the
diagnostic OpenGL failures. No driver, global browser preference,
model service or GPU reset is required.

From `services/frontend`, with the existing locked Playwright browser installed:

```bash
PLAYWRIGHT_BROWSERS_PATH=/data/odin-caches/playwright \
ODIN_NATIVE_URL=http://127.0.0.1:5173/worldview \
ODIN_NATIVE_PROFILE=/data/odin-browser/native-vulkan \
npm run browser:native
```

Use the configured loopback gateway URL for authenticated operation if applicable;
never put credentials in the URL. `-- --check` verifies the actual map renderer in
a visible browser and closes that owned browser. The ordinary command keeps it
open for use. An existing non-ODIN profile is refused. Browser version and actual
Vulkan/NVIDIA renderer are checked before navigation; software fallback is refused.
The profile path is separate from normal browser profiles. The launcher neither
installs browsers nor changes desktop defaults. Requalify after browser/driver
changes. Remote terrain and human visual acceptance remain separate.


For future release qualification, stage the immutable image's complete served
HTML/assets into the preview directory, preserve any previous local build, and
compare every served file hash before and after the run. Keep the explicit spatial
build argument set to `true` in Docker/CI. Run the native short suite followed by
`playwright.soak.config.ts`; freeze the image identity, source and asset hashes.
The observed catalog request catches the demonstrated missing-flag error; it does
not replace full artifact identity checks. The separately named SwiftShader
negative/positive guard probes are not native performance evidence.
