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
mkdir -p public
hf download jayinnn/Skyfall-GS-ply JAX_068_final.ply --local-dir public
ls -lh public/JAX_068_final.ply   # expect ~229 MiB

# Serve the harness.
npm run dev
# Open http://127.0.0.1:8765/
```

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
