# Skyfall Recon — Phase 0 Smoke Harness

A two-pane renderer parity + load-time gate for the Skyfall Recon MVP. Runs
`@sparkjsdev/spark` and `@mkkellogg/gaussian-splats-3d` side by side against the
same PLY so a human operator can pick a renderer based on real numbers and
real screenshots.

Phase A (Tasks 1-21) is BLOCKED until `verify_results.py` exits zero.

## Prerequisites

- Node 20+
- `hf` CLI on `PATH` (Hugging Face CLI; used to fetch the test PLY)
- A Chromium-based browser with DevTools (for Network throttling)
- Python 3 on `PATH` (for `verify_results.py`)

## Setup

```bash
cd scripts/recon/phase0
npm install --no-audit --no-fund

# Download the representative PLY (~230 MB, gitignored).
# THIS STEP IS REQUIRED. If you skip it, mkk silently fails with
# "splatArray is undefined" (its loader never finds end_header in an
# empty/HTML response) and Spark errors on a non-existent file.
mkdir -p public
hf download jayinnn/Skyfall-GS-ply JAX_068_final.ply --local-dir public
ls -lh public/JAX_068_final.ply   # expect ~229 MiB

# Serve the harness.
npm run dev
# Open http://127.0.0.1:8765/
```

### Vite config

`vite.config.ts` ships two fixes for failures the operator hit on first run
(2026-05-18):

- `optimizeDeps.exclude: ["@sparkjsdev/spark"]`. Spark inlines its WASM as a
  `data:application/wasm;base64,...` URL inside `new URL(..., import.meta.url)`.
  When Vite 5.4.x's dep-optimizer pre-bundles Spark via esbuild, that data-URL
  fetch path produces:

  ```
  WebAssembly.instantiateStreaming failed because your server does not serve
  Wasm with `application/wasm` MIME type.
  TypeError: WebAssembly: Response has unsupported MIME type ''
  expected 'application/wasm'
  ```

  Excluding Spark from dep optimization tells Vite to serve Spark's published
  ESM module unmodified; the data URL then fetches with the correct
  `application/wasm` Content-Type and `instantiateStreaming` succeeds.

- A `wasm-mime` middleware that sets `Content-Type: application/wasm` for any
  request ending in `.wasm`. Defensive; not strictly required today because
  Spark uses a data URL and mkk has no native `.wasm` dep, but it costs
  nothing and prevents future regressions if either library starts shipping a
  side-loaded `.wasm` companion file.

> Note on `first_progress_ms`: the harness streams the PLY itself via
> `fetch()` + a `ReadableStream` reader to measure the first non-zero
> byte chunk honestly. The bytes are then handed to Spark via
> `SplatMesh({ fileBytes, fileType })`. mkk's `addSplatScene` re-fetches
> from the URL (its own `onProgress` is wired up too) — the second fetch
> is served from the browser HTTP cache, so it doesn't double the wire
> time on the no-throttle run. On the 30 Mbps throttled run there *is*
> a small re-download cost for mkk; that's acceptable for a smoke test,
> and the timing run still measures both renderers fairly because each
> path uses its own dedicated progress hook.

## Capture procedure

1. DevTools -> Network -> "No throttling". Click **Run benchmark**, wait for
   both rows to log `first_frame_ms`.
2. Click **Screenshot spark.png** and **Screenshot mkk.png**. Save both into
   `docs/workflows/recon-phase-0-screenshots/`.
3. Click **Export phase0-results.json**. Save it as
   `docs/workflows/recon-phase-0-results.json`.
4. Reload, set DevTools throttling to a custom **30 Mbps** profile
   (30000 kbps down, 5000 kbps up, 50 ms RTT). Re-run **Run benchmark**.
   Click **Export phase0-results.json** and save as
   `docs/workflows/recon-phase-0-results-30mbps.json`.
5. Open the official Skyfall-GS Mip-Splatting demo (spec §13), set the same
   JAX_068 camera angle as the harness, screenshot to
   `docs/workflows/recon-phase-0-screenshots/reference.png`.
6. Fill in `docs/workflows/recon-phase-0-smoke.md` with the real numbers from
   the JSON exports and a written comparison of the three screenshots.

## Gate

```bash
cd ~/ODIN/OSINT
python scripts/recon/phase0/verify_results.py
```

`verify_results.py` is the gate. It refuses to PASS until:

- the smoke doc, both JSON results files, and all three screenshots exist
- the smoke doc has no `<...>` angle-bracket placeholders left
- the chosen renderer has no error and real numbers in both runs
- `first_progress_ms <= 2000` in both runs for the chosen renderer
- `first_frame_ms <= 60000` in the 30 Mbps run for the chosen renderer
- the doc declares `Phase 0 verdict: **PASS**` literally

It exits non-zero with a cited reason until those conditions hold; that
non-zero exit is the correct gate behavior until the operator finishes the
capture procedure above.

## Version pinning

This workspace pins:

- `@sparkjsdev/spark` 0.1.10
- `@mkkellogg/gaussian-splats-3d` 0.4.7
- `three` 0.165.0
- `vite` 5.4.10
- `typescript` 5.6.3

Never use `latest`. If a pinned version no longer resolves on npm, bump to
the latest available `0.x` line for that package and document the bump
here. If the renderer-class import (`SplatMesh`, `Viewer`) breaks after a
bump, stop and revisit the plan rather than papering over it.

### Bumps from the original plan pins (2026-05-18)

The plan (`docs/superpowers/plans/2026-05-17-skyfall-recon-mvp.md`, Task 0
Step 1) pinned versions that don't resolve on npm. Both pins were adjusted
on the day of scaffold:

- `@sparkjsdev/spark@0.7.0` -> `@sparkjsdev/spark@0.1.10`. The plan used an
  alias package name; the real package on npm is `@sparkjsdev/spark`
  (verified via `npm search spark gaussian`). The 0.x line maxes at
  `0.1.10`; a `2.0.0` major rewrite exists but we pin the latest 0.x
  for stability. The harness uses the 0.1.10 API surface verified
  against `node_modules/@sparkjsdev/spark/dist/types/SplatMesh.d.ts`:
  the readiness promise is `mesh.initialized` (NOT `loadPromise`), and
  `SplatMeshOptions` has no `onProgress` field — progress is measured
  by the harness's own `fetch()` stream reader before bytes are handed
  to `SplatMesh({ fileBytes, fileType })`.
- `@mkkellogg/gaussian-splats-3d@0.5.3` -> `@mkkellogg/gaussian-splats-3d@0.4.7`.
  `0.5.x` does not exist; `0.4.7` is the latest published 0.x.

If the harness errors at run time with "SplatMesh is not a constructor",
"Cannot read properties of undefined (reading 'initialized')", or
"Viewer.addSplatScene is not a function", the API surface changed in the
0.x line we landed on — STOP, file BLOCKED, do not paper over.

## Known mkk limitation (2026-05-18 diagnosis)

Diagnosis outcome: **(b) PLY header incompatibility / loader-state edge.**

The crash signature the operator reported —

```
TypeError: can't access property "splatCount", splatArray is undefined
  partitionGenerator SplatPartitioner.js:55
  partitionUncompressedSplatArray SplatPartitioner.js:19
  generateFromUncompressedSplatArray SplatBufferGenerator.js:18
  finalize$1 PlyLoader.js:38
  loadFromURL PlyLoader.js:308
```

— traces in `node_modules/@mkkellogg/gaussian-splats-3d/build/gaussian-splats-3d.module.js`
to `PlyLoader.loadFromURL` (line 3486) → `finalize$1` (line 3475) →
`SplatPartitioner.partitionUncompressedSplatArray` (line 3322). The
`splatArray` argument to `finalize$1` originates from
`loadPromise.resolve(standardLoadUncompressedSplatArray)` inside `localOnProgress`.
That variable is only assigned (line 3582) when `headerLoaded` flips true,
which only happens when `PlyParserUtils.checkTextForEndHeader(headerText)`
sees the literal `end_header` token. If the loader streams to `loadComplete=true`
without ever seeing `end_header`, `standardLoadUncompressedSplatArray` stays
`undefined`, the promise resolves with `undefined`, and `finalize$1` crashes
exactly as reported.

Two paths reach that state with a Skyfall-GS PLY:

1. **The PLY is missing on disk.** Vite serves a 404 or (in some
   configurations) HTML, mkk's `fetchWithProgress` finishes the stream, and
   `headerLoaded` never goes true. This is by far the most common cause.
   The harness now does a pre-flight `HEAD` for the PLY URL in `runMkk` and
   throws with the actual status code and a hint about the `hf download`
   step, so this case fails loudly.

2. **mkk 0.4.7 cannot parse Skyfall-GS Mip-Splatting PLYs.** The INRIAV1
   parser at `decodeHeaderLines` (line 2762) recognizes the standard 3DGS
   columns (`x/y/z`, `f_dc_*`, `opacity`, `scale_*`, `rot_*`, optional
   `f_rest_*`) which Skyfall-GS PLYs do ship. Mip-Splatting adds an
   antialiasing kernel parameter at runtime but doesn't change the PLY
   column layout, so header parsing *should* succeed. However: if the
   pre-flight HEAD passes (i.e. the file is present and well-formed) and
   `runMkk` still hits the same crash, we are in this state — mkk's loader
   has an edge case with this PLY shape. That's a renderer-fitness signal,
   not something to patch around: Phase 0's whole point is to score the two
   renderers honestly. The harness will record `mkk.error` with the real
   message and `verify_results.py` can gate on it.

No `format` flag in mkk's `addSplatScene` options fixes this (a `.ply`
extension already selects `SceneFormat.Ply` via `sceneFormatFromPath` at
line 4718). The renderer choice ladder remains: if mkk fails honestly on
the JAX_068 PLY, pick Spark.
