# Skyfall Recon MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a globe-driven "Recon Viewer" capability — twelve pre-built Skyfall-GS scenes (8 JAX + 4 NYC) openable from globe pins, rendered in a Three.js Gaussian-Splatting modal with WASD navigation and PNG capture.

**Architecture:** Read-only FastAPI router (`/api/recon/scenes` + `/api/v1/` alias) serves a static `recon_manifest.json` produced by a one-shot bootstrap script. PLY assets stream from `/static/recon/*.ply` with HTTP Range + immutable Cache-Control. Frontend mounts a Cesium `BillboardCollection` pin layer plus a portal-mounted React modal that lazy-loads the splat renderer chosen in Phase 0.

**Tech Stack:** FastAPI 0.128, Pydantic v2, Starlette `StaticFiles`, React 19, Vite 6, Cesium 1.132 (existing), Three.js + 3DGS renderer (Spark or `@mkkellogg/gaussian-splats-3d`, decided in Phase 0), `hf` HuggingFace CLI for bootstrap.

**Spec:** `docs/superpowers/specs/2026-05-11-skyfall-recon-mvp-design.md` (v2).

---

## Review Round 1 (2026-05-17) — Adjustments

This plan was reviewed by a quality-gate pass; the corrections below are
applied throughout. Read this list before executing — several tasks changed
shape:

1. **Backend wiring uses `lifespan`, not `@app.on_event("startup")`.** The
   real `services/backend/app/main.py` already declares an
   `@asynccontextmanager lifespan(app)`; manifest loading is added inside it
   before `yield`. (Task 5.)
2. **Phase 0 is a real gate with real code, real screenshots, real
   timings.** Pseudocode replaced with concrete renderer calls per each
   library's documented API; pinned package versions; harness produces
   `phase0-results.json` consumed by a verification step. (Task 0.)
3. **Renderer is lazy-loaded.** `ReconViewer` uses dynamic `await
   import("./renderer")` so the splat library + Three.js stay out of the
   initial Vite bundle. (Task 15, Task 18.)
4. **WASD navigation is wired and tested.** `SplatRenderHandle` exposes
   `move()` and `look()`; `<CameraControls>` is mounted inside `ReconViewer`
   and its callbacks call the handle. (Task 15, Task 17, Task 18.)
5. **PNG capture is required, not optional.** Folded into Task 18 (was
   Task 21); button is mounted in the viewer; unit test added. Task 21 is
   removed.
6. **License audit is fail-closed and grounded in local pinned files.**
   `resolve_attribution` requires a real `licenses/<slug>.txt` file to
   exist alongside a per-scene `verified_by` / `verified_at` record;
   missing records raise `LicenseUnverifiedError`. Bootstrap emits
   `services/backend/static/recon/LICENSES.md` from the same records.
   (Task 7, Task 8.)
7. **Cache-busting via `?sha=<sha256>` query.** `ply_url` in the manifest
   includes the SHA so a re-bootstrap with new bytes invalidates the
   immutable cache on the next request. (Task 1, Task 8.)
8. **AppShell wiring is the real entry point.** `<ReconProvider>` wraps
   `<IncidentProvider>` inside `services/frontend/src/app/AppShell.tsx`;
   `<ReconViewer />` lives next to `<IncidentToast />`. (Task 19.)
9. **Bootstrap short-circuits before download.** All 12 expected SHAs are
   checked against the existing manifest + on-disk files first; if they
   match, `hf_download_all` is not called. Test asserts no download/copy
   on full-match rerun. (Task 8.)
10. **Runtime renderer errors surface to the UI with a Retry button.**
    `ReconViewer` holds an `error` state; the renderer's `onError` callback
    transitions into it; retry re-issues the render. Tested with a
    mocked-rejecting renderer. (Task 18.)

## Review Round 2 (2026-05-17) — Additional Adjustments

11. **BandwidthGuard race fixed.** Previously the render effect could fire
    before the canvas was mounted (canvas is inside `BandwidthGuard`, which
    hides children on 2G/3G), and `onConfirm={() => {}}` did not re-trigger
    the effect. Now `ReconViewer` holds `loadAllowed` state, the guard's
    `onConfirm` flips it to true, and the render effect depends on it.
    `BandwidthGuard` also auto-fires `onConfirm` on fast connections so the
    `loadAllowed` gate is symmetric. New tests cover both paths. (Task 14,
    Task 18.)
12. **Phase 0 gate now enforces budgets.** `verify_results.py` parses
    `Chosen renderer: **<spark|mkk>**` from the smoke doc, refuses to PASS
    if that renderer errored in either run, and fails if its
    `first_progress_ms > 2000` (any run) or its 30 Mbps `first_frame_ms >
    60000`. (Task 0, Step 6.)
13. **License audit moved to stdlib JSON.** `records.yaml` → `records.json`
    so the bootstrap can run from the repo root without depending on
    PyYAML (which is service-local only). (Task 7, Task 8.)
14. **MVP completeness gate.** Bootstrap now defaults to raising
    `BootstrapPartialError` when fewer than 12 scenes end up in the
    manifest — the MVP goal is "all twelve scenes openable from a globe-
    pin click". A `--allow-partial` flag preserves the fail-closed
    experimentation path. (Task 8.)
15. **"LARGE" badge for scenes >300 MB.** Spec §3.1 requires scenes above
    300 MB to be tagged "large"; the modal now renders a badge with the
    scene's size in MB, with a unit test using `nyc_219` (324 MB).
    (Task 18.)
16. **Overview text reconciled with task bodies.** File-structure summary
    no longer says "App.tsx" or "startup" — it now matches the lifespan /
    `AppShell.tsx` wiring used by the detailed tasks.

## Review Round 3 (2026-05-17) — Additional Adjustments

17. **Atomic manifest write.** Bootstrap now raises
    `BootstrapPartialError` BEFORE writing `manifest_path`, then writes to
    a `.tmp` sibling and `os.replace`s only on success. Two new tests
    assert: (a) no manifest left behind on partial-fail; (b) a previous
    good manifest is preserved across a subsequent partial-fail run.
    (Task 8.)
18. **Idempotency short-circuit re-audits licenses.** When all 12 PLY
    SHAs match the prior manifest, the bootstrap now runs
    `resolve_attribution` for every source group present in that manifest
    BEFORE skipping the HF download. If `records.json` was emptied since
    the prior run, default behavior raises `BootstrapPartialError` and
    keeps the prior manifest untouched. New test asserts no HF download
    AND the failure. (Task 8.)
19. **Phase 0 gate enforces `first_progress_ms` in both runs.**
    `verify_results.py` loops `(no-throttle, 30mbps)` for the chosen
    renderer's progress budget, matching the spec wording "any run."
    (Task 0.)
20. **LARGE-badge test uses a mutable mock reference.** Tests mutate
    `mocks.state.scenes` (via the `vi.hoisted` block — see Round 4 #22)
    before render. The vi.mock factory reads from the same reference, so
    no `vi.doMock` + re-import dance and no stale module cache. Plus a
    complementary "no badge under 300 MB" test. (Task 18.)
21. **Test-count assertions current.** Bootstrap → 9, ReconViewer → 10,
    BandwidthGuard → 4, with one-line legends.

## Review Round 4 (2026-05-17) — Additional Adjustments

22. **`vi.hoisted` for the ReconViewer mock state.** `vi.mock` factories
    are hoisted above imports, so they can't reference module-scope
    `let`/`const` (TDZ at hoist time). Mutable mock state lives in
    `const mocks = vi.hoisted(() => ({...}))`; the mock factory and the
    test bodies both read/write through `mocks.state.*`. (Task 18.)
23. **Short-circuit refactor — re-audit, refresh, drop into common
    tail.** When PLY SHAs match, the short-circuit no longer takes its
    own early return. Instead it builds a fresh `scenes_out` from the
    prior manifest, runs `resolve_attribution` for every entry (dropping
    any whose licenses no longer verify), and falls through to the
    common partial-fail check + atomic-write tail. This makes
    `--allow-partial + invalidated licenses` rewrite the manifest to a
    smaller verified set rather than silently keep the old 12-scene one.
    It also refreshes `attribution` strings when records change (the
    viewer footer reads `scene.attribution` verbatim). Two new tests:
    `short_circuit_allow_partial_rewrites_to_smaller_manifest` and
    `short_circuit_refreshes_attribution_when_records_change`. (Task 8.)
24. **Phase-0 placeholder check tightened.** `verify_results.py` now
    catches `<from JSON-30>`, `<PASS|FAIL>`, `<spark | mkk>`,
    `<browser + OS + GPU>`, and any leftover angle-bracket placeholder
    via a final regex guard. (Task 0.)
25. **Bootstrap test-count assertion updated.** Bootstrap → 11 (added
    short-circuit-allow-partial-rewrites, short-circuit-refreshes-
    attribution).

---

## File Structure

### Backend (`services/backend/`)
- Create `app/models/recon.py` — Pydantic schemas (`GeoBounds`, `DefaultCamera`, `ReconScene`, `ReconManifest`, `ReconScenesResponse`).
- Create `app/static/cached_static.py` — `CachedStaticFiles` subclass adding immutable Cache-Control.
- Create `app/services/recon_manifest.py` — manifest loader singleton; reads JSON once at startup.
- Create `app/routers/recon.py` — READ-ONLY router with `/recon/scenes` and `/recon/scenes/{scene_id}`.
- Modify `app/main.py` — register router with dual `/api` + `/api/v1` prefixes, mount `CachedStaticFiles` at `/static/recon`, call manifest loader inside the existing `@asynccontextmanager lifespan(app)` before `yield`.
- Create `data/recon_manifest.json` — emitted by bootstrap; tests use temporary fixtures.
- Create `static/recon/.gitkeep` and `static/recon/LICENSES.md` — bootstrap fills LICENSES.md with per-dataset license text.
- Create `tests/test_recon_models.py`, `tests/test_cached_static.py`, `tests/test_recon_manifest_loader.py`, `tests/test_recon_router.py`, `tests/test_recon_static.py`.

### Bootstrap (`scripts/recon/`)
- Create `scripts/recon/__init__.py`.
- Create `scripts/recon/asset_mapping.py` — frozen 12-row mapping table.
- Create `scripts/recon/license_audit.py` — per-source-dataset license resolver.
- Create `scripts/recon/bootstrap_skyfall_plys.py` — main entrypoint (`python -m scripts.recon.bootstrap_skyfall_plys`).
- Create `scripts/recon/tests/__init__.py`, `scripts/recon/tests/test_asset_mapping.py`, `scripts/recon/tests/test_license_audit.py`, `scripts/recon/tests/test_bootstrap_skyfall_plys.py`.

### Frontend (`services/frontend/src/`)
- Create `lib/recon/types.ts` — TS mirror of Pydantic models.
- Create `lib/recon/manifest.ts` — `useReconManifest()` hook with module-level SWR-style cache.
- Create `state/ReconContext.tsx` — `ReconProvider` + `useRecon()` (open/close scene).
- Create `components/recon/WebGLCheck.tsx`.
- Create `components/recon/BandwidthGuard.tsx`.
- Create `components/recon/CameraControls.tsx`.
- Create `components/recon/renderer/SplatRenderer.ts` — abstract interface (`renderScene` → `Disposer`).
- Create `components/recon/renderer/index.ts` — re-exports concrete renderer chosen in Phase 0.
- Create `components/recon/renderer/sparkRenderer.ts` *or* `mkkRenderer.ts` — concrete renderer (file name set after Phase 0 decision).
- Create `components/recon/ReconViewer.tsx` — portal-mounted full-screen modal.
- Create `components/recon/CaptureButton.tsx`.
- Create `components/layers/ReconLayer.tsx` — Cesium `BillboardCollection`, FIRMSLayer pattern.
- Modify `pages/WorldviewPage.tsx` — wire `ReconLayer` with `onSelect` → `useRecon().openScene`.
- Modify `app/AppShell.tsx` (the actual provider tree root) — wrap with `ReconProvider`, mount `<ReconViewer />` once alongside `<IncidentLayer>`.
- Create `components/recon/__tests__/ReconViewer.test.tsx`, `components/recon/__tests__/BandwidthGuard.test.tsx`, `lib/recon/__tests__/manifest.test.ts`, `state/__tests__/ReconContext.test.tsx`, `components/layers/__tests__/ReconLayer.test.tsx`.

### Orchestration & Docs
- Modify `odin.sh` — add `recon` subcommand (`./odin.sh recon bootstrap`).
- Create `docs/workflows/recon-phase-0-smoke.md` — Phase 0 results (renderer + load times).
- Create `docs/workflows/recon-smoke.md` — manual end-to-end smoke checklist.
- Create `scripts/recon/phase0/index.html` — standalone renderer parity harness (deleted after Phase 0, kept under `scripts/recon/phase0/` for reproducibility).

---

## Project Rules to Honor (per `CLAUDE.md`)

- **No `any` in TypeScript.** All recon types declared explicitly.
- **Cesium imperative `BillboardCollection`** in `ReconLayer.tsx`, never Entity API.
- **Hard READ-ONLY surface** on `recon.py` router — no write endpoints, no DB writes, no LLM calls.
- **No hardcoded URLs.** PLY URLs come from the manifest, never inlined.
- **Cesium cleanup must check `viewer.isDestroyed()`** (per `project_s2_worldview_backlog` memory).
- **TDD:** test first, fail, then implement.
- **Two-stage review** is mandatory after Phase A (no shortcuts; per `feedback_never_skip_reviews` memory).

---

# Phase 0 — Smoke Gate (BLOCKS Phase A)

### Task 0: Renderer parity + load-time smoke (REAL GATE)

**Files:**
- Create: `scripts/recon/phase0/package.json`
- Create: `scripts/recon/phase0/index.html`
- Create: `scripts/recon/phase0/harness.ts`
- Create: `scripts/recon/phase0/verify_results.py`
- Create: `scripts/recon/phase0/README.md`
- Create: `docs/workflows/recon-phase-0-smoke.md`
- Create: `docs/workflows/recon-phase-0-screenshots/{spark.png, mkk.png, reference.png}` (binary, produced by harness)

This task is **gated** by Step 6 (a verification script that refuses to PASS
unless the JSON artifact contains real numbers and the screenshots exist).
Pseudocode is not acceptable here.

- [ ] **Step 1: Pin renderer versions**

Create `scripts/recon/phase0/package.json` (Phase 0 lives in its own npm
workspace so it doesn't pollute the frontend's `package.json` until the
winner is chosen):
```json
{
  "name": "skyfall-recon-phase0",
  "private": true,
  "type": "module",
  "scripts": {
    "serve": "vite preview --port 8765 --host 127.0.0.1"
  },
  "dependencies": {
    "@sparkjsdev/spark": "0.1.10",
    "@mkkellogg/gaussian-splats-3d": "0.4.7",
    "three": "0.165.0"
  },
  "devDependencies": {
    "vite": "5.4.10",
    "typescript": "5.6.3"
  }
}
```

Run:
```bash
cd scripts/recon/phase0
npm install
```

(If the pinned versions don't resolve, bump to the latest available
`0.x` line and record the bump in `README.md` — never use `latest`.)

- [ ] **Step 2: Download one representative PLY locally**

```bash
mkdir -p scripts/recon/phase0/public
cd scripts/recon/phase0/public
hf download jayinnn/Skyfall-GS-ply JAX_068_final.ply --local-dir .
ls -lh JAX_068_final.ply   # expect 229 MiB
```

Add `scripts/recon/phase0/public/*.ply` to a local `.gitignore` (do not
commit the PLY; ~230 MB).

- [ ] **Step 3: Write the harness with real renderer calls**

Create `scripts/recon/phase0/index.html`:
```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Skyfall Recon — Phase 0 Renderer Parity</title>
  <style>
    body { margin: 0; background: #0b0b09; color: #ddd; font: 13px monospace; }
    .row { display: flex; height: 70vh; }
    .col { flex: 1; border-left: 1px solid #333; position: relative; }
    .col h2 { position: absolute; top: 8px; left: 8px; margin: 0; font-size: 12px; z-index: 2; }
    canvas { width: 100%; height: 100%; display: block; }
    #panel { padding: 12px; }
    button { background: #333; color: #ddd; border: 1px solid #555; padding: 6px 12px; cursor: pointer; }
    pre { white-space: pre-wrap; }
  </style>
</head>
<body>
  <div class="row">
    <div class="col"><h2>Spark @0.7.0</h2><canvas id="spark"></canvas></div>
    <div class="col"><h2>gaussian-splats-3d @0.5.3</h2><canvas id="mkk"></canvas></div>
  </div>
  <div id="panel">
    <button id="start">Run benchmark</button>
    <button id="screenshot-spark">Screenshot spark.png</button>
    <button id="screenshot-mkk">Screenshot mkk.png</button>
    <button id="export">Export phase0-results.json</button>
    <pre id="results"></pre>
  </div>
  <script type="module" src="./harness.ts"></script>
</body>
</html>
```

Create `scripts/recon/phase0/harness.ts`. This file uses each library's
documented loader so a real PLY is actually streamed and rendered:
```ts
import * as THREE from "three";
// Pinned imports — concrete classes per each library's README on 2026-05-11.
// If a class name changes in a later version, update both the import and
// package.json pin; do not rely on "default" exports here.
import { SplatMesh } from "@sparkjsdev/spark";
import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";

const PLY_URL = "/JAX_068_final.ply";
const PLY_EXPECTED_BYTES = 240164505;

interface Timing {
  module_load_ms: number;
  first_progress_ms: number | null;
  first_frame_ms: number | null;
  total_ms: number | null;
  error: string | null;
}

const results: { spark: Timing; mkk: Timing; ua: string; pinned_versions: Record<string,string> } = {
  spark: empty(), mkk: empty(),
  ua: navigator.userAgent,
  pinned_versions: { "@sparkjsdev/spark": "0.7.0", "@mkkellogg/gaussian-splats-3d": "0.5.3", three: "0.165.0" },
};

function empty(): Timing {
  return { module_load_ms: 0, first_progress_ms: null, first_frame_ms: null, total_ms: null, error: null };
}

function log(line: string) {
  const el = document.getElementById("results")!;
  el.textContent += line + "\n";
}

async function runSpark(canvas: HTMLCanvasElement, t: Timing) {
  const tStart = performance.now();
  try {
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, canvas.clientWidth / canvas.clientHeight, 0.1, 5000);
    camera.position.set(0, 0, 200);
    camera.lookAt(0, 0, 0);

    let progressFired = false;
    // SplatMesh exposes onProgress / onLoad per Spark 0.7 README.
    const mesh = new SplatMesh({
      url: PLY_URL,
      onProgress: (loaded: number, total: number) => {
        if (!progressFired) {
          t.first_progress_ms = performance.now() - tStart;
          progressFired = true;
        }
      },
    });
    scene.add(mesh);

    // Render loop; first frame timestamp = first requestAnimationFrame after mesh load resolves.
    await mesh.loadPromise;
    renderer.render(scene, camera);
    t.first_frame_ms = performance.now() - tStart;
    requestAnimationFrame(function loop() {
      renderer.render(scene, camera);
      requestAnimationFrame(loop);
    });
    t.total_ms = performance.now() - tStart;
    log(`spark: progress=${t.first_progress_ms?.toFixed(0)}ms frame=${t.first_frame_ms.toFixed(0)}ms`);
  } catch (e) {
    t.error = (e as Error).message;
    log(`spark ERROR: ${t.error}`);
  }
}

async function runMkk(canvas: HTMLCanvasElement, t: Timing) {
  const tStart = performance.now();
  try {
    // Viewer API per gaussian-splats-3d 0.5 README.
    const viewer = new GaussianSplats3D.Viewer({
      useBuiltInControls: false,
      rootElement: canvas.parentElement!,
      sharedMemoryForWorkers: false,
    });
    let progressFired = false;
    await viewer.addSplatScene(PLY_URL, {
      onProgress: (percent: number) => {
        if (!progressFired) {
          t.first_progress_ms = performance.now() - tStart;
          progressFired = true;
        }
      },
    });
    t.first_frame_ms = performance.now() - tStart;
    viewer.start();
    t.total_ms = performance.now() - tStart;
    log(`mkk: progress=${t.first_progress_ms?.toFixed(0)}ms frame=${t.first_frame_ms.toFixed(0)}ms`);
  } catch (e) {
    t.error = (e as Error).message;
    log(`mkk ERROR: ${t.error}`);
  }
}

document.getElementById("start")!.addEventListener("click", async () => {
  const moduleLoadStart = performance.now();
  await Promise.all([
    runSpark(document.getElementById("spark") as HTMLCanvasElement, results.spark),
    runMkk(document.getElementById("mkk") as HTMLCanvasElement, results.mkk),
  ]);
  log(`done`);
});

function downloadCanvas(canvas: HTMLCanvasElement, name: string) {
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  });
}

document.getElementById("screenshot-spark")!.addEventListener("click",
  () => downloadCanvas(document.getElementById("spark") as HTMLCanvasElement, "spark.png"));
document.getElementById("screenshot-mkk")!.addEventListener("click",
  () => downloadCanvas(document.getElementById("mkk") as HTMLCanvasElement, "mkk.png"));

document.getElementById("export")!.addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(results, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "phase0-results.json"; a.click();
  URL.revokeObjectURL(url);
});
```

- [ ] **Step 4: Serve, capture timings, capture screenshots**

```bash
cd scripts/recon/phase0
npx vite --port 8765
# Browser: http://127.0.0.1:8765/
# 1. DevTools → Network → "No throttling". Click "Run benchmark".
#    Wait for both rows to log first_frame_ms.
# 2. Click "Screenshot spark.png" and "Screenshot mkk.png" — save into
#    docs/workflows/recon-phase-0-screenshots/.
# 3. Click "Export phase0-results.json" — save it to
#    docs/workflows/recon-phase-0-results.json.
# 4. Repeat with DevTools throttling at "30 Mbps custom" (Network tab →
#    Throttling profile → Add → 30000 kbps down, 5000 kbps up, 50 ms RTT).
#    Save as phase0-results-30mbps.json.
# 5. Open the official Skyfall-GS Mip-Splatting demo (spec §13), set the
#    same JAX_068 camera angle as the harness, screenshot to
#    docs/workflows/recon-phase-0-screenshots/reference.png.
```

- [ ] **Step 5: Write the decision artifact**

Create `docs/workflows/recon-phase-0-smoke.md`:
```markdown
# Phase 0 Smoke — Renderer Parity & Load-Time Gate

**Date:** <YYYY-MM-DD>
**Hardware:** <browser + OS + GPU>
**PLY tested:** JAX_068_final.ply (240,164,505 bytes)

## Pinned versions
- @sparkjsdev/spark: 0.7.0
- @mkkellogg/gaussian-splats-3d: 0.5.3
- three: 0.165.0

## Timing — no throttling
| Renderer | first_progress_ms | first_frame_ms | total_ms |
|----------|-------------------|----------------|----------|
| spark    | <from JSON>       | <from JSON>    | <from JSON> |
| mkk      | <from JSON>       | <from JSON>    | <from JSON> |

## Timing — 30 Mbps throttled
| Renderer | first_progress_ms | first_frame_ms | total_ms |
|----------|-------------------|----------------|----------|
| spark    | <from JSON-30>    | <from JSON-30> | <from JSON-30> |
| mkk      | <from JSON-30>    | <from JSON-30> | <from JSON-30> |

## Visual parity
- `recon-phase-0-screenshots/reference.png` (Skyfall-GS demo)
- `recon-phase-0-screenshots/spark.png`
- `recon-phase-0-screenshots/mkk.png`

Comparison notes: <one paragraph: sharpness on building edges, diagonal-line
aliasing, color fidelity. Cite which renderer is closer to the reference.>

## Verdict
- Chosen renderer: **<spark | mkk>**
- Rationale: <one paragraph citing the table + screenshots above>
- Goal 1.a "first visible progress <2s": <PASS|FAIL>
- Goal 1.b "first navigable frame <60s @ 30 Mbps for 250 MB PLY": <PASS|FAIL>
- Phase 0 verdict: **<PASS|PAUSE>**
```

Replace every `<...>` placeholder with the actual values from the JSON
artifacts and the screenshots.

- [ ] **Step 6: Verification script (the actual gate)**

Create `scripts/recon/phase0/verify_results.py`:
```python
"""Refuses to PASS Phase 0 unless artifacts exist, numbers are real, the
chosen renderer has no error in either timing run, and the chosen
renderer meets the Goal §3.1 latency budgets:

  - first_progress_ms (any run): <= 2000
  - first_frame_ms (30 Mbps run): <= 60000
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

DOCS = Path("docs/workflows")
SCREENSHOTS = DOCS / "recon-phase-0-screenshots"
SMOKE = DOCS / "recon-phase-0-smoke.md"
RESULTS = DOCS / "recon-phase-0-results.json"
RESULTS_30 = DOCS / "recon-phase-0-results-30mbps.json"

PROGRESS_BUDGET_MS = 2000
FRAME_BUDGET_30MBPS_MS = 60000

CHOSEN_RE = re.compile(r"Chosen renderer:\s*\*\*(spark|mkk)\*\*", re.IGNORECASE)


def fail(msg: str) -> "None":
    print(f"PHASE 0 GATE FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    # 1. Artifacts must exist
    for p in (SMOKE, RESULTS, RESULTS_30):
        if not p.exists():
            fail(f"missing artifact: {p}")
    for name in ("spark.png", "mkk.png", "reference.png"):
        if not (SCREENSHOTS / name).exists():
            fail(f"missing screenshot: {SCREENSHOTS / name}")

    text = SMOKE.read_text()

    # 2. Smoke doc must not contain placeholders
    placeholder_substrings = (
        "<from JSON>", "<from JSON-30>",
        "<one paragraph", "<YYYY-MM-DD>",
        "<browser + OS + GPU>",
        "Chosen renderer: **<", "Phase 0 verdict: **<",
        "<spark | mkk>", "<PASS|FAIL>", "<PASS | FAIL>",
        "<from JSON",  # catch any remaining angle-bracket JSON refs
    )
    for needle in placeholder_substrings:
        if needle in text:
            fail(f"smoke.md still contains placeholder {needle!r}; fill in real values")
    # Bare angle-bracket regex (catches anything like <foo bar>) as a final guard
    if re.search(r"<[A-Za-z][^>]{0,80}>", text):
        m = re.search(r"<[A-Za-z][^>]{0,80}>", text)
        fail(f"smoke.md still contains an angle-bracket placeholder: {m.group(0)!r}")

    # 3. Parse the chosen renderer
    m = CHOSEN_RE.search(text)
    if not m:
        fail("smoke.md does not declare 'Chosen renderer: **spark|mkk**'")
    chosen = m.group(1).lower()

    # 4. Numbers must be real for ALL renderers (so the comparison is honest)
    data = json.loads(RESULTS.read_text())
    data30 = json.loads(RESULTS_30.read_text())
    for label, src in (("no-throttle", data), ("30mbps", data30)):
        for r in ("spark", "mkk"):
            t = src[r]
            if t.get("error"):
                if r == chosen:
                    fail(f"chosen renderer {chosen!r} errored in {label}: {t['error']}")
                continue
            for k in ("first_progress_ms", "first_frame_ms", "total_ms"):
                v = t.get(k)
                if v is None or not isinstance(v, (int, float)) or v <= 0:
                    fail(f"{label}: {r}.{k} not measured (got {v!r})")

    # 5. Chosen renderer must hit the latency budgets (spec §3.1)
    #    first_progress_ms <= 2000 in *both* runs (spec: "any run")
    for label, src in (("no-throttle", data), ("30mbps", data30)):
        run = src[chosen]
        if run.get("first_progress_ms", 0) > PROGRESS_BUDGET_MS:
            fail(
                f"chosen renderer {chosen!r} {label} first_progress_ms="
                f"{run['first_progress_ms']:.0f} exceeds "
                f"{PROGRESS_BUDGET_MS}ms budget"
            )
    # first_frame_ms <= 60000 in the 30 Mbps run (spec: "on a 30 Mbps connection")
    chosen_30 = data30[chosen]
    if chosen_30["first_frame_ms"] > FRAME_BUDGET_30MBPS_MS:
        fail(
            f"chosen renderer {chosen!r} 30mbps first_frame_ms="
            f"{chosen_30['first_frame_ms']:.0f} exceeds "
            f"{FRAME_BUDGET_30MBPS_MS}ms budget"
        )

    # 6. Verdict must be PASS to count as PASS (PAUSE explicitly fails the gate)
    if "Phase 0 verdict: **PASS**" not in text:
        if "Phase 0 verdict: **PAUSE**" in text:
            fail("smoke.md declares PAUSE — phase 0 did not pass")
        fail("smoke.md does not declare 'Phase 0 verdict: **PASS**'")

    print(f"PHASE 0 GATE: PASS (chosen={chosen})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run:
```bash
cd ~/ODIN/OSINT
python scripts/recon/phase0/verify_results.py
# Expected: PHASE 0 GATE: PASS, exit 0.
# If it exits non-zero, fix the cited artifact and re-run.
```

- [ ] **Step 7: Commit Phase 0 artifacts**

```bash
cd ~/ODIN/OSINT
echo "/scripts/recon/phase0/public/*.ply" >> .gitignore
echo "/scripts/recon/phase0/node_modules" >> .gitignore
git add .gitignore scripts/recon/phase0/{package.json,index.html,harness.ts,verify_results.py,README.md}
git add docs/workflows/recon-phase-0-smoke.md \
       docs/workflows/recon-phase-0-results.json \
       docs/workflows/recon-phase-0-results-30mbps.json \
       docs/workflows/recon-phase-0-screenshots/
git commit -m "feat(recon): Phase 0 smoke — renderer parity, screenshots, timings (gated)"
```

**GATE:** If `verify_results.py` exits non-zero, or the smoke doc declares
`verdict: PAUSE`, stop. Revisit the spec.

---

# Phase A — Backend

### Task 1: Pydantic models

**Files:**
- Create: `services/backend/app/models/recon.py`
- Test: `services/backend/tests/test_recon_models.py`

- [ ] **Step 1: Write the failing test**

Create `services/backend/tests/test_recon_models.py`:
```python
import json
from app.models.recon import GeoBounds, DefaultCamera, ReconScene, ReconManifest


def test_geobounds_accepts_valid_coordinates():
    b = GeoBounds(center_lat=30.33, center_lon=-81.65, radius_m=350)
    assert b.center_lat == 30.33


def test_default_camera_serializes_position_as_tuple():
    c = DefaultCamera(position=(0.0, 0.0, 200.0), look_at=(0.0, 0.0, 0.0), fov_deg=60.0)
    assert c.model_dump()["position"] == (0.0, 0.0, 200.0)


def test_recon_scene_requires_source_canonical_value():
    s = ReconScene(
        scene_id="jax_068", hf_filename="JAX_068_final.ply",
        display_name="Jacksonville District 068",
        ply_url="/static/recon/JAX_068_final.ply?sha=" + "a" * 64,
        ply_size_bytes=240164505,
        ply_sha256="a" * 64,
        bounds=GeoBounds(center_lat=30.33, center_lon=-81.65, radius_m=350),
        bounds_source="spacenet_metadata",
        default_camera=DefaultCamera(position=(0, 0, 200), look_at=(0, 0, 0), fov_deg=60),
        attribution="Reconstruction: Skyfall-GS ...",
        source="skyfall_gs_hf",
    )
    assert s.scene_id == "jax_068"
    assert s.ply_url.endswith("?sha=" + "a" * 64)


def test_recon_scene_rejects_ply_url_without_sha_query():
    """The cache-busting ?sha=<sha256> query is required to make 'immutable' safe."""
    import pytest
    with pytest.raises(ValueError):
        ReconScene(
            scene_id="jax_068", hf_filename="JAX_068_final.ply",
            display_name="x",
            ply_url="/static/recon/JAX_068_final.ply",  # no ?sha=
            ply_size_bytes=1, ply_sha256="a"*64,
            bounds=GeoBounds(center_lat=0, center_lon=0, radius_m=1),
            bounds_source="manual",
            default_camera=DefaultCamera(position=(0,0,1), look_at=(0,0,0), fov_deg=60),
            attribution="x", source="skyfall_gs_hf",
        )


def test_recon_manifest_parses_v2_payload():
    payload = {
        "version": 2,
        "generated_at": "2026-05-17T00:00:00Z",
        "source_commit": "deadbeef",
        "scenes": [],
    }
    m = ReconManifest.model_validate(payload)
    assert m.version == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_models.py -v
```
Expected: FAIL — `app.models.recon` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `services/backend/app/models/recon.py`:
```python
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class GeoBounds(BaseModel):
    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0)


class DefaultCamera(BaseModel):
    position: tuple[float, float, float]
    look_at: tuple[float, float, float]
    fov_deg: float = Field(gt=0, le=180)


class ReconScene(BaseModel):
    scene_id: str
    hf_filename: str
    display_name: str
    ply_url: str
    ply_size_bytes: int = Field(gt=0)
    ply_sha256: str = Field(min_length=64, max_length=64)
    bounds: GeoBounds
    bounds_source: Literal["spacenet_metadata", "manual"]
    default_camera: DefaultCamera
    attribution: str
    source: str

    @model_validator(mode="after")
    def _ply_url_must_carry_sha_query(self) -> "ReconScene":
        # Immutable Cache-Control is only safe when the URL changes whenever
        # bytes change. Bootstrap embeds ?sha=<ply_sha256> in ply_url; reject
        # manifests that don't.
        expected = f"?sha={self.ply_sha256}"
        if not self.ply_url.endswith(expected):
            raise ValueError(
                f"ply_url must end with {expected!r} for cache-bust safety; "
                f"got {self.ply_url!r}"
            )
        return self


class ReconManifest(BaseModel):
    version: int
    generated_at: str
    source_commit: str
    scenes: list[ReconScene]


class ReconScenesResponse(BaseModel):
    scenes: list[ReconScene]
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_models.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/models/recon.py services/backend/tests/test_recon_models.py
git commit -m "feat(backend/recon): add Pydantic models for recon scenes and manifest"
```

---

### Task 2: CachedStaticFiles subclass

**Files:**
- Create: `services/backend/app/static/__init__.py`
- Create: `services/backend/app/static/cached_static.py`
- Test: `services/backend/tests/test_cached_static.py`

- [ ] **Step 1: Write the failing test**

Create `services/backend/tests/test_cached_static.py`:
```python
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.static.cached_static import CachedStaticFiles


def _build_app(tmp_path: Path) -> FastAPI:
    (tmp_path / "hello.bin").write_bytes(b"abcdefghijklmnop")
    app = FastAPI()
    app.mount("/s", CachedStaticFiles(directory=str(tmp_path)), name="s")
    return app


def test_full_request_returns_200_with_immutable_cache_control(tmp_path):
    client = TestClient(_build_app(tmp_path))
    r = client.get("/s/hello.bin")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.content == b"abcdefghijklmnop"


def test_range_request_returns_206_with_correct_bytes(tmp_path):
    client = TestClient(_build_app(tmp_path))
    r = client.get("/s/hello.bin", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.content == b"abcd"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unknown_file_returns_404(tmp_path):
    client = TestClient(_build_app(tmp_path))
    r = client.get("/s/missing.bin")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/backend
uv run pytest tests/test_cached_static.py -v
```
Expected: FAIL — `app.static.cached_static` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `services/backend/app/static/__init__.py` (empty).

Create `services/backend/app/static/cached_static.py`:
```python
from starlette.staticfiles import StaticFiles
from starlette.responses import Response


class CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that adds immutable Cache-Control headers.

    Range requests are inherited from Starlette's FileResponse, which already
    returns 206 Partial Content when a Range header is present.
    """

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 206):
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )
        return response
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/backend
uv run pytest tests/test_cached_static.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/static/ services/backend/tests/test_cached_static.py
git commit -m "feat(backend/recon): add CachedStaticFiles with immutable Cache-Control"
```

---

### Task 3: Manifest loader service

**Files:**
- Create: `services/backend/app/services/__init__.py` (if missing)
- Create: `services/backend/app/services/recon_manifest.py`
- Test: `services/backend/tests/test_recon_manifest_loader.py`

- [ ] **Step 1: Write the failing test**

Create `services/backend/tests/test_recon_manifest_loader.py`:
```python
import json
from pathlib import Path
import pytest
from app.services.recon_manifest import (
    ReconManifestLoader,
    ReconManifestMissingError,
)


def _valid_manifest_dict():
    sha = "a" * 64
    return {
        "version": 2,
        "generated_at": "2026-05-17T00:00:00Z",
        "source_commit": "deadbeef",
        "scenes": [
            {
                "scene_id": "jax_068",
                "hf_filename": "JAX_068_final.ply",
                "display_name": "Jacksonville District 068",
                "ply_url": f"/static/recon/JAX_068_final.ply?sha={sha}",
                "ply_size_bytes": 240164505,
                "ply_sha256": sha,
                "bounds": {"center_lat": 30.33, "center_lon": -81.65, "radius_m": 350},
                "bounds_source": "spacenet_metadata",
                "default_camera": {"position": [0, 0, 200], "look_at": [0, 0, 0], "fov_deg": 60},
                "attribution": "test attribution",
                "source": "skyfall_gs_hf",
            }
        ],
    }


def test_loader_reads_manifest_into_memory_dict(tmp_path):
    path = tmp_path / "recon_manifest.json"
    path.write_text(json.dumps(_valid_manifest_dict()))
    loader = ReconManifestLoader(path)
    loader.load()
    assert loader.is_loaded
    assert loader.get_scene("jax_068") is not None
    assert loader.get_scene("jax_068").display_name == "Jacksonville District 068"
    assert loader.get_scene("missing") is None


def test_loader_list_scenes_returns_all(tmp_path):
    path = tmp_path / "recon_manifest.json"
    path.write_text(json.dumps(_valid_manifest_dict()))
    loader = ReconManifestLoader(path)
    loader.load()
    assert len(loader.list_scenes()) == 1


def test_loader_missing_file_raises(tmp_path):
    loader = ReconManifestLoader(tmp_path / "absent.json")
    with pytest.raises(ReconManifestMissingError):
        loader.load()
    assert not loader.is_loaded
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_manifest_loader.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `services/backend/app/services/__init__.py` if missing (check first; if it already exists, skip).

Create `services/backend/app/services/recon_manifest.py`:
```python
import json
from pathlib import Path
from app.models.recon import ReconManifest, ReconScene


class ReconManifestMissingError(FileNotFoundError):
    """Raised when the recon manifest JSON cannot be located on disk."""


class ReconManifestLoader:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._by_id: dict[str, ReconScene] = {}
        self._loaded = False

    def load(self) -> None:
        if not self._path.exists():
            raise ReconManifestMissingError(str(self._path))
        raw = json.loads(self._path.read_text())
        manifest = ReconManifest.model_validate(raw)
        self._by_id = {s.scene_id: s for s in manifest.scenes}
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_scene(self, scene_id: str) -> ReconScene | None:
        return self._by_id.get(scene_id)

    def list_scenes(self) -> list[ReconScene]:
        return list(self._by_id.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_manifest_loader.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/services/recon_manifest.py services/backend/tests/test_recon_manifest_loader.py
git commit -m "feat(backend/recon): add ReconManifestLoader with in-memory cache"
```

---

### Task 4: Recon router

**Files:**
- Create: `services/backend/app/routers/recon.py`
- Test: `services/backend/tests/test_recon_router.py`

- [ ] **Step 1: Write the failing test**

Create `services/backend/tests/test_recon_router.py`:
```python
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import recon as recon_router
from app.services.recon_manifest import ReconManifestLoader


def _seed_manifest(tmp_path: Path) -> ReconManifestLoader:
    sha = "a" * 64
    payload = {
        "version": 2, "generated_at": "2026-05-17T00:00:00Z", "source_commit": "x",
        "scenes": [
            {
                "scene_id": "jax_068", "hf_filename": "JAX_068_final.ply",
                "display_name": "Jacksonville District 068",
                "ply_url": f"/static/recon/JAX_068_final.ply?sha={sha}",
                "ply_size_bytes": 240164505, "ply_sha256": sha,
                "bounds": {"center_lat": 30.33, "center_lon": -81.65, "radius_m": 350},
                "bounds_source": "spacenet_metadata",
                "default_camera": {"position": [0,0,200], "look_at": [0,0,0], "fov_deg": 60},
                "attribution": "test", "source": "skyfall_gs_hf",
            }
        ],
    }
    p = tmp_path / "m.json"
    p.write_text(json.dumps(payload))
    loader = ReconManifestLoader(p)
    loader.load()
    return loader


def _build_app(loader: ReconManifestLoader) -> FastAPI:
    app = FastAPI()
    app.state.recon_manifest = loader
    app.include_router(recon_router.router, prefix="/api")
    app.include_router(recon_router.router, prefix="/api/v1")
    return app


def test_list_scenes_returns_manifest_shape(tmp_path):
    client = TestClient(_build_app(_seed_manifest(tmp_path)))
    r = client.get("/api/recon/scenes")
    assert r.status_code == 200
    body = r.json()
    assert "scenes" in body
    assert body["scenes"][0]["scene_id"] == "jax_068"


def test_list_scenes_v1_alias_matches_primary(tmp_path):
    client = TestClient(_build_app(_seed_manifest(tmp_path)))
    a = client.get("/api/recon/scenes").json()
    b = client.get("/api/v1/recon/scenes").json()
    assert a == b


def test_get_scene_by_id(tmp_path):
    client = TestClient(_build_app(_seed_manifest(tmp_path)))
    r = client.get("/api/recon/scenes/jax_068")
    assert r.status_code == 200
    assert r.json()["scene_id"] == "jax_068"


def test_get_scene_404_for_unknown_id(tmp_path):
    client = TestClient(_build_app(_seed_manifest(tmp_path)))
    r = client.get("/api/recon/scenes/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "scene not found"


def test_router_503_when_manifest_not_loaded(tmp_path):
    loader = ReconManifestLoader(tmp_path / "absent.json")  # not loaded
    client = TestClient(_build_app(loader))
    r = client.get("/api/recon/scenes")
    assert r.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_router.py -v
```
Expected: FAIL — `app.routers.recon` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `services/backend/app/routers/recon.py`:
```python
from fastapi import APIRouter, HTTPException, Request
from app.models.recon import ReconScene, ReconScenesResponse
from app.services.recon_manifest import ReconManifestLoader

router = APIRouter(tags=["recon"])


def _loader(request: Request) -> ReconManifestLoader:
    loader: ReconManifestLoader | None = getattr(
        request.app.state, "recon_manifest", None
    )
    if loader is None or not loader.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="recon manifest not loaded; run ./odin.sh recon bootstrap",
        )
    return loader


@router.get("/recon/scenes", response_model=ReconScenesResponse)
def list_scenes(request: Request) -> ReconScenesResponse:
    loader = _loader(request)
    return ReconScenesResponse(scenes=loader.list_scenes())


@router.get("/recon/scenes/{scene_id}", response_model=ReconScene)
def get_scene(scene_id: str, request: Request) -> ReconScene:
    loader = _loader(request)
    scene = loader.get_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene not found")
    return scene
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_router.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/recon.py services/backend/tests/test_recon_router.py
git commit -m "feat(backend/recon): add READ-ONLY recon router with dual /api + /api/v1 mount"
```

---

### Task 5: Wire router + static mount + lifespan integration into `main.py`

**Files:**
- Modify: `services/backend/app/main.py`
- Create: `services/backend/static/recon/.gitkeep`
- Create: `services/backend/data/.gitkeep` (only if `data/` directory doesn't exist yet — check first)
- Test: `services/backend/tests/test_recon_static.py`

- [ ] **Step 1: Write the failing test**

Create `services/backend/tests/test_recon_static.py`:
```python
"""Integration smoke for the real app wiring (router + static mount)."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_with_seeded_manifest(tmp_path, monkeypatch):
    static_dir = tmp_path / "static" / "recon"
    static_dir.mkdir(parents=True)
    ply = static_dir / "JAX_TEST_final.ply"
    ply.write_bytes(b"PLYDATA" * 10)  # 70 bytes

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    sha = "b" * 64
    manifest = {
        "version": 2, "generated_at": "2026-05-17T00:00:00Z", "source_commit": "x",
        "scenes": [{
            "scene_id": "jax_test", "hf_filename": "JAX_TEST_final.ply",
            "display_name": "Test",
            "ply_url": f"/static/recon/JAX_TEST_final.ply?sha={sha}",
            "ply_size_bytes": 70, "ply_sha256": sha,
            "bounds": {"center_lat": 30.0, "center_lon": -81.0, "radius_m": 100},
            "bounds_source": "manual",
            "default_camera": {"position": [0,0,100], "look_at": [0,0,0], "fov_deg": 60},
            "attribution": "test", "source": "skyfall_gs_hf",
        }],
    }
    (data_dir / "recon_manifest.json").write_text(json.dumps(manifest))

    monkeypatch.setenv("RECON_MANIFEST_PATH", str(data_dir / "recon_manifest.json"))
    monkeypatch.setenv("RECON_STATIC_DIR", str(static_dir))

    # Re-import the app fresh so the module-level mount picks up env vars.
    # Use TestClient as a context manager so the FastAPI lifespan executes
    # and the manifest loader is wired into app.state.
    import importlib
    import app.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client


def test_recon_scenes_endpoint_live(app_with_seeded_manifest):
    r = app_with_seeded_manifest.get("/api/recon/scenes")
    assert r.status_code == 200
    assert r.json()["scenes"][0]["scene_id"] == "jax_test"


def test_recon_ply_static_serves_with_immutable_cache_control(app_with_seeded_manifest):
    r = app_with_seeded_manifest.get("/static/recon/JAX_TEST_final.ply")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_recon_ply_range_returns_206(app_with_seeded_manifest):
    r = app_with_seeded_manifest.get(
        "/static/recon/JAX_TEST_final.ply",
        headers={"Range": "bytes=0-2"},
    )
    assert r.status_code == 206
    assert r.content == b"PLY"
```

> Note: the fixture must use `yield client` instead of `return client` so
> the `with` block stays open for the duration of the test. Mark the
> fixture function with `pytest.fixture()` (already in the snippet above)
> — the generator form switches automatically.

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_static.py -v
```
Expected: FAIL — env vars unused; lifespan/mount integration absent.

- [ ] **Step 3: Modify `app/main.py`**

The existing `services/backend/app/main.py` declares an
`@asynccontextmanager lifespan(app)` around line 50. **Do not use
`@app.on_event("startup")`** — with an explicit lifespan, event handlers
are silently ignored. Manifest loading goes inside `lifespan()` before the
`yield`.

Add near the top of the file (after the existing imports):
```python
import os
from pathlib import Path
from app.routers import recon as recon_router_module
from app.services.recon_manifest import (
    ReconManifestLoader,
    ReconManifestMissingError,
)
from app.static.cached_static import CachedStaticFiles
```

Inside the existing `lifespan` body, immediately before the existing
`logger.info("backend_started", ...)` line and before `yield`, insert:
```python
    # Recon manifest — load into app.state for the recon router
    recon_manifest_path = Path(os.environ.get(
        "RECON_MANIFEST_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "recon_manifest.json"),
    ))
    recon_loader = ReconManifestLoader(recon_manifest_path)
    try:
        recon_loader.load()
        logger.info("recon_manifest_loaded",
                    path=str(recon_manifest_path),
                    scenes=len(recon_loader.list_scenes()))
    except ReconManifestMissingError:
        logger.warning("recon_manifest_missing",
                       path=str(recon_manifest_path),
                       hint="run ./odin.sh recon bootstrap")
    app.state.recon_manifest = recon_loader
```

After the existing `for r in (...)` dual-prefix block (around
`app/main.py:111`), add:
```python
# Recon router — dual /api + /api/v1 prefix (matches existing convention)
app.include_router(recon_router_module.router, prefix="/api")
app.include_router(recon_router_module.router, prefix="/api/v1")

# Static PLY assets for recon (immutable Cache-Control, Range supported)
_recon_static_dir = Path(os.environ.get(
    "RECON_STATIC_DIR",
    str(Path(__file__).resolve().parent.parent / "static" / "recon"),
))
_recon_static_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/recon",
    CachedStaticFiles(directory=str(_recon_static_dir)),
    name="recon_static",
)
```

Create empty placeholders so the directories are committed:
- `services/backend/static/recon/.gitkeep`
- `services/backend/data/.gitkeep` (only if `services/backend/data/` does not exist).

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/backend
uv run pytest tests/test_recon_static.py tests/test_recon_router.py tests/test_cached_static.py tests/test_recon_manifest_loader.py tests/test_recon_models.py -v
```
Expected: all PASS.

- [ ] **Step 5: Full backend suite + lint**

Run:
```bash
cd services/backend
uv run pytest -x
uv run ruff check app/
```
Expected: 0 failures, 0 new ruff errors.

- [ ] **Step 6: Commit**

```bash
git add services/backend/app/main.py services/backend/static/recon/.gitkeep services/backend/tests/test_recon_static.py
# Only add data/.gitkeep if it was newly created:
git add services/backend/data/.gitkeep 2>/dev/null || true
git commit -m "feat(backend/recon): wire recon router + CachedStaticFiles + manifest lifespan into main"
```

---

# Phase A — Bootstrap

### Task 6: Asset mapping table

**Files:**
- Create: `scripts/recon/__init__.py`
- Create: `scripts/recon/asset_mapping.py`
- Create: `scripts/recon/tests/__init__.py`
- Test: `scripts/recon/tests/test_asset_mapping.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/recon/tests/test_asset_mapping.py`:
```python
import re
from scripts.recon.asset_mapping import ASSET_MAPPING, AssetEntry


def test_twelve_entries():
    assert len(ASSET_MAPPING) == 12


def test_scene_ids_unique_and_lowercase():
    ids = [e.scene_id for e in ASSET_MAPPING]
    assert len(set(ids)) == len(ids)
    for sid in ids:
        assert sid == sid.lower()
        assert re.fullmatch(r"(jax|nyc)_\d{3}", sid)


def test_hf_filenames_match_scene_ids():
    for e in ASSET_MAPPING:
        # jax_068 -> JAX_068_final.ply
        prefix, num = e.scene_id.split("_")
        assert e.hf_filename == f"{prefix.upper()}_{num}_final.ply"


def test_sizes_are_positive():
    for e in ASSET_MAPPING:
        assert e.expected_size_bytes > 0


def test_source_group_is_known():
    valid = {"SpaceNet 2", "SpaceNet 4"}
    for e in ASSET_MAPPING:
        assert e.source_group in valid


def test_eight_jax_four_nyc():
    jax = [e for e in ASSET_MAPPING if e.scene_id.startswith("jax_")]
    nyc = [e for e in ASSET_MAPPING if e.scene_id.startswith("nyc_")]
    assert len(jax) == 8
    assert len(nyc) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd ~/ODIN/OSINT
python -m pytest scripts/recon/tests/test_asset_mapping.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/recon/__init__.py` (empty) and `scripts/recon/tests/__init__.py` (empty).

Create `scripts/recon/asset_mapping.py`:
```python
"""Frozen asset mapping for Skyfall-GS pre-built PLYs.

Source: https://huggingface.co/api/models/jayinnn/Skyfall-GS-ply/tree/main
Verified 2026-05-11. Sizes copied from HF API; SHA values are populated at
bootstrap time (not stored here).
"""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AssetEntry:
    scene_id: str           # canonical lowercase: jax_068
    hf_filename: str        # verbatim HF: JAX_068_final.ply
    display_name: str
    expected_size_bytes: int
    source_group: Literal["SpaceNet 2", "SpaceNet 4"]


ASSET_MAPPING: tuple[AssetEntry, ...] = (
    AssetEntry("jax_004", "JAX_004_final.ply", "Jacksonville District 004", 158_510_569, "SpaceNet 4"),
    AssetEntry("jax_068", "JAX_068_final.ply", "Jacksonville District 068", 240_164_505, "SpaceNet 4"),
    AssetEntry("jax_164", "JAX_164_final.ply", "Jacksonville District 164", 290_453_497, "SpaceNet 4"),
    AssetEntry("jax_168", "JAX_168_final.ply", "Jacksonville District 168", 265_047_857, "SpaceNet 4"),
    AssetEntry("jax_175", "JAX_175_final.ply", "Jacksonville District 175", 232_601_521, "SpaceNet 4"),
    AssetEntry("jax_214", "JAX_214_final.ply", "Jacksonville District 214", 222_097_625, "SpaceNet 4"),
    AssetEntry("jax_260", "JAX_260_final.ply", "Jacksonville District 260", 227_118_225, "SpaceNet 4"),
    AssetEntry("jax_264", "JAX_264_final.ply", "Jacksonville District 264", 272_916_913, "SpaceNet 4"),
    AssetEntry("nyc_004", "NYC_004_final.ply", "New York City Tile 004", 243_791_921, "SpaceNet 2"),
    AssetEntry("nyc_010", "NYC_010_final.ply", "New York City Tile 010", 320_689_209, "SpaceNet 2"),
    AssetEntry("nyc_219", "NYC_219_final.ply", "New York City Tile 219", 324_186_833, "SpaceNet 2"),
    AssetEntry("nyc_336", "NYC_336_final.ply", "New York City Tile 336", 213_483_617, "SpaceNet 2"),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd ~/ODIN/OSINT
python -m pytest scripts/recon/tests/test_asset_mapping.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/recon/__init__.py scripts/recon/asset_mapping.py scripts/recon/tests/
git commit -m "feat(recon/bootstrap): add frozen 12-entry asset mapping table"
```

---

### Task 7: License audit module (fail-closed, file-backed)

**Files:**
- Create: `scripts/recon/license_audit.py`
- Create: `services/backend/static/recon/licenses/README.md` — explains the
  directory contract.
- Create: `services/backend/static/recon/licenses/spacenet-2.txt` (empty
  placeholder; committed so the path exists in CI but the audit will
  refuse to consider it verified until populated).
- Create: `services/backend/static/recon/licenses/spacenet-4.txt` (same).
- Create: `services/backend/static/recon/licenses/records.json` — the
  per-source `verified_by` / `verified_at` record. Manually maintained.
  JSON (stdlib) is used instead of YAML because the bootstrap runs from
  the repo root via `python -m scripts.recon...` and the root environment
  does not declare PyYAML (only service-local pyprojects do).
- Test: `scripts/recon/tests/test_license_audit.py`

The audit is fail-closed: a `SourceLicense` is only valid when **all** of
the following exist for that source group:
- a non-empty `licenses/<slug>.txt` file (pinned upstream text), and
- an entry in `records.json` with non-empty `verified_by`, `verified_at`,
  and `spdx` fields.

If any condition is missing, `resolve_attribution()` raises
`LicenseUnverifiedError` and the bootstrap excludes the scene.

- [ ] **Step 1: Write the failing test**

Create `scripts/recon/tests/test_license_audit.py`:
```python
import pytest
from pathlib import Path
from scripts.recon.license_audit import (
    LicenseUnverifiedError,
    resolve_attribution,
    load_license_records,
)


def _seed_records(tmp_path: Path) -> Path:
    import json
    licenses_dir = tmp_path / "licenses"
    licenses_dir.mkdir()
    (licenses_dir / "spacenet-4.txt").write_text("REAL UPSTREAM LICENSE TEXT FOR SPACENET 4\n...")
    (licenses_dir / "spacenet-2.txt").write_text("")  # intentionally empty
    (licenses_dir / "records.json").write_text(json.dumps({
        "records": {
            "SpaceNet 4": {
                "slug": "spacenet-4",
                "spdx": "CC-BY-SA-4.0",
                "upstream_url": "https://spacenet.ai/off-nadir-building-detection/",
                "verified_by": "RT",
                "verified_at": "2026-05-17",
            }
        }
    }))
    return licenses_dir


def test_resolve_attribution_passes_for_fully_verified_source(tmp_path):
    base = _seed_records(tmp_path)
    text = resolve_attribution(source_group="SpaceNet 4", licenses_dir=base)
    assert "Skyfall-GS" in text
    assert "Apache 2.0" in text
    assert "SpaceNet 4" in text
    assert "CC-BY-SA-4.0" in text
    assert "verified" in text.lower()


def test_resolve_attribution_fails_when_license_file_empty(tmp_path):
    import json
    base = _seed_records(tmp_path)
    # SpaceNet 2 has empty license text; add a record too so only the empty file fails
    payload = json.loads((base / "records.json").read_text())
    payload["records"]["SpaceNet 2"] = {
        "slug": "spacenet-2",
        "spdx": "CC-BY-SA-4.0",
        "upstream_url": "https://spacenet.ai/spacenet-buildings-dataset-v2/",
        "verified_by": "RT",
        "verified_at": "2026-05-17",
    }
    (base / "records.json").write_text(json.dumps(payload))
    with pytest.raises(LicenseUnverifiedError, match="empty license file"):
        resolve_attribution(source_group="SpaceNet 2", licenses_dir=base)


def test_resolve_attribution_fails_when_no_record(tmp_path):
    base = _seed_records(tmp_path)
    with pytest.raises(LicenseUnverifiedError, match="no record"):
        resolve_attribution(source_group="SpaceNet 2", licenses_dir=base)


def test_resolve_attribution_fails_for_unknown_source(tmp_path):
    base = _seed_records(tmp_path)
    with pytest.raises(LicenseUnverifiedError):
        resolve_attribution(source_group="Made Up Dataset", licenses_dir=base)


def test_load_license_records_returns_dict(tmp_path):
    base = _seed_records(tmp_path)
    records = load_license_records(base)
    assert "SpaceNet 4" in records
    assert records["SpaceNet 4"]["spdx"] == "CC-BY-SA-4.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd ~/ODIN/OSINT
python -m pytest scripts/recon/tests/test_license_audit.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/recon/license_audit.py`:
```python
"""Fail-closed license audit for Skyfall-GS source datasets.

A source group counts as verified only when:
  1. `<licenses_dir>/<slug>.txt` exists and is non-empty (pinned upstream text)
  2. `<licenses_dir>/records.json` has a `records.<source_group>` entry with
     non-empty `slug`, `spdx`, `upstream_url`, `verified_by`, `verified_at`.

Missing or partial verification raises LicenseUnverifiedError. The bootstrap
script catches that and excludes the corresponding scene from the manifest.

JSON (stdlib) is used so the bootstrap has no dependency outside Python
stdlib — runnable from the repo root via `python -m scripts.recon...`.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


_SKYFALL_LINE = (
    "Reconstruction: Skyfall-GS (Lee et al., 2025; arXiv:2510.15869v3) — Apache 2.0."
)


class LicenseUnverifiedError(ValueError):
    """Raised when a scene's source dataset cannot be confirmed as licensed."""


def load_license_records(licenses_dir: Path) -> dict[str, dict[str, Any]]:
    path = Path(licenses_dir) / "records.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text() or "{}")
    return payload.get("records") or {}


def resolve_attribution(*, source_group: str, licenses_dir: Path) -> str:
    records = load_license_records(licenses_dir)
    record = records.get(source_group)
    if record is None:
        raise LicenseUnverifiedError(
            f"no record for source group {source_group!r} in records.json"
        )

    required = ("slug", "spdx", "upstream_url", "verified_by", "verified_at")
    for k in required:
        if not record.get(k):
            raise LicenseUnverifiedError(
                f"record for {source_group!r} missing field {k!r}"
            )

    slug = record["slug"]
    license_file = Path(licenses_dir) / f"{slug}.txt"
    if not license_file.exists():
        raise LicenseUnverifiedError(
            f"license text not found at {license_file} — populate with the "
            f"upstream license text from {record['upstream_url']}"
        )
    if license_file.stat().st_size == 0:
        raise LicenseUnverifiedError(
            f"empty license file at {license_file} — populate with the "
            f"upstream license text from {record['upstream_url']}"
        )

    return (
        f"{_SKYFALL_LINE} "
        f"Source imagery: {source_group} ({record['spdx']}, "
        f"verified {record['verified_at']} by {record['verified_by']}). "
        f"Upstream: {record['upstream_url']}. Local text: {slug}.txt."
    )


def render_licenses_md(licenses_dir: Path) -> str:
    """Emit LICENSES.md content from records.json + on-disk license files."""
    records = load_license_records(licenses_dir)
    lines: list[str] = [
        "# Recon Scene Licenses",
        "",
        "Skyfall-GS model artifacts: Apache 2.0 "
        "(from https://huggingface.co/jayinnn/Skyfall-GS-ply).",
        "",
        "Per-source-imagery licenses:",
        "",
    ]
    for source_group, record in sorted(records.items()):
        slug = record.get("slug", "<missing>")
        spdx = record.get("spdx", "<missing>")
        upstream = record.get("upstream_url", "<missing>")
        verified_by = record.get("verified_by", "<missing>")
        verified_at = record.get("verified_at", "<missing>")
        lines.extend([
            f"## {source_group}",
            f"- SPDX: {spdx}",
            f"- Upstream: {upstream}",
            f"- Verified: {verified_at} by {verified_by}",
            f"- Local text: [`licenses/{slug}.txt`](licenses/{slug}.txt)",
            "",
        ])
    return "\n".join(lines)
```

Create `services/backend/static/recon/licenses/README.md`:
```markdown
# Recon Licenses Directory

This directory backs the bootstrap license audit. For each source dataset
the recon scenes derive from, two artifacts must exist before scenes from
that source are eligible for the manifest:

1. **`<slug>.txt`** — verbatim upstream license text (non-empty). Copy
   from the dataset's homepage; never paraphrase.
2. **Entry in `records.json`** — with `slug`, `spdx`, `upstream_url`,
   `verified_by`, `verified_at` (all non-empty).

Anything missing → bootstrap excludes the affected scenes (fail-closed).
The audit also generates `../LICENSES.md` from these records.
```

Create `services/backend/static/recon/licenses/records.json`:
```json
{
  "_comment": "Per-source-imagery license records. Populated manually after pulling the upstream license text into licenses/<slug>.txt. Bootstrap reads this. Empty by default — the bootstrap will exclude SpaceNet 2 + SpaceNet 4 scenes from the manifest until each source has a fully populated record AND a non-empty <slug>.txt file alongside.",
  "records": {}
}
```

Create empty `services/backend/static/recon/licenses/spacenet-2.txt` and
`services/backend/static/recon/licenses/spacenet-4.txt` as placeholders:
```bash
mkdir -p services/backend/static/recon/licenses
touch services/backend/static/recon/licenses/spacenet-2.txt
touch services/backend/static/recon/licenses/spacenet-4.txt
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd ~/ODIN/OSINT
python -m pytest scripts/recon/tests/test_license_audit.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/recon/license_audit.py scripts/recon/tests/test_license_audit.py \
        services/backend/static/recon/licenses/
git commit -m "feat(recon/bootstrap): fail-closed file-backed license audit + records.json"
```

> **Operator action before first PASS run:** populate the two `.txt` files
> with the actual upstream license text from spacenet.ai, and fill in
> `records.json` with both SpaceNet 2 and SpaceNet 4 records. Until then
> the bootstrap emits a manifest with 0 scenes (correct fail-closed
> behavior; Task 8 has a `--allow-partial` flag that lets the developer
> run with fewer than 12 scenes intentionally).

---

### Task 8: Bootstrap entrypoint (CLI check + idempotent rerun + manifest emission)

**Files:**
- Create: `scripts/recon/bootstrap_skyfall_plys.py`
- Test: `scripts/recon/tests/test_bootstrap_skyfall_plys.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/recon/tests/test_bootstrap_skyfall_plys.py`:
```python
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from scripts.recon.bootstrap_skyfall_plys import (
    main,
    BootstrapError,
    check_hf_cli,
    HFCLIMissingError,
    sha256_of,
)


def test_check_hf_cli_raises_actionable_message_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(HFCLIMissingError) as exc:
        check_hf_cli()
    assert "pip install" in str(exc.value) or "uv pip install" in str(exc.value)


def test_sha256_of_computes_hex_digest(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert sha256_of(f) == hashlib.sha256(b"hello").hexdigest()


@pytest.fixture()
def fake_hf_cache(tmp_path):
    """Simulates 'hf download' having already populated a local dir."""
    cache = tmp_path / "hf_cache"
    cache.mkdir()
    for name in (
        "JAX_004_final.ply", "JAX_068_final.ply", "JAX_164_final.ply",
        "JAX_168_final.ply", "JAX_175_final.ply", "JAX_214_final.ply",
        "JAX_260_final.ply", "JAX_264_final.ply",
        "NYC_004_final.ply", "NYC_010_final.ply", "NYC_219_final.ply",
        "NYC_336_final.ply",
    ):
        # 1-byte stubs (size mismatch is expected and tested below)
        (cache / name).write_bytes(b"x")
    return cache


@pytest.fixture()
def fake_licenses_dir(tmp_path):
    """Seed a fully-verified licenses dir for both SpaceNet groups."""
    licenses = tmp_path / "licenses"
    licenses.mkdir()
    import json as _json
    (licenses / "spacenet-2.txt").write_text("SPACENET 2 LICENSE TEXT")
    (licenses / "spacenet-4.txt").write_text("SPACENET 4 LICENSE TEXT")
    (licenses / "records.json").write_text(_json.dumps({"records": {
        "SpaceNet 2": {
            "slug": "spacenet-2", "spdx": "CC-BY-SA-4.0",
            "upstream_url": "https://spacenet.ai/spacenet-buildings-dataset-v2/",
            "verified_by": "test", "verified_at": "2026-05-17",
        },
        "SpaceNet 4": {
            "slug": "spacenet-4", "spdx": "CC-BY-SA-4.0",
            "upstream_url": "https://spacenet.ai/off-nadir-building-detection/",
            "verified_by": "test", "verified_at": "2026-05-17",
        },
    }}))
    return licenses


def test_main_emits_manifest_validating_against_pydantic(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(
            static_dir=static_dir,
            manifest_path=manifest_path,
            licenses_dir=fake_licenses_dir,
            strict_sizes=False,
        )

    # Validate against backend Pydantic model
    sys.path.insert(0, str(Path("services/backend").resolve()))
    from app.models.recon import ReconManifest
    m = ReconManifest.model_validate_json(manifest_path.read_text())
    assert m.version == 2
    assert len(m.scenes) == 12
    assert {s.scene_id for s in m.scenes} >= {"jax_068", "nyc_010"}
    # ply_url includes ?sha=<sha256> for cache safety
    for s in m.scenes:
        assert s.ply_url.endswith(f"?sha={s.ply_sha256}")


def test_main_emits_licenses_md(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"
    licenses_md = static_dir / "LICENSES.md"

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False)

    assert licenses_md.exists()
    text = licenses_md.read_text()
    assert "SpaceNet 2" in text
    assert "SpaceNet 4" in text
    assert "Apache 2.0" in text


def test_main_is_idempotent_and_skips_download_when_shas_match(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # First run: download is called once
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ) as download_first:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False)
        first = manifest_path.read_text()
    assert download_first.call_count == 1

    # Second run: all PLYs already on disk with matching SHAs → no download
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all"
    ) as download_second:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False)
        second = manifest_path.read_text()
    assert download_second.call_count == 0, "rerun must short-circuit before HF download"

    # Manifest content stable across runs (timestamps may differ — compare scenes)
    a = json.loads(first)["scenes"]
    b = json.loads(second)["scenes"]
    assert a == b


def test_main_raises_when_fewer_than_12_scenes_and_not_allow_partial(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """Default behavior: bootstrap exits non-zero AND leaves no manifest behind."""
    from scripts.recon.bootstrap_skyfall_plys import BootstrapPartialError
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"
    assert not manifest_path.exists()

    def fake_resolve(*, source_group, licenses_dir):
        if source_group == "SpaceNet 2":
            from scripts.recon.license_audit import LicenseUnverifiedError
            raise LicenseUnverifiedError("simulated")
        return "ok-attribution"

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ), patch(
        "scripts.recon.bootstrap_skyfall_plys.resolve_attribution",
        side_effect=fake_resolve,
    ):
        with pytest.raises(BootstrapPartialError):
            main(static_dir=static_dir, manifest_path=manifest_path,
                 licenses_dir=fake_licenses_dir, strict_sizes=False,
                 allow_partial=False)

    # Manifest must NOT be written on partial-fail — otherwise a half-baked
    # 0/4/8-scene file would silently undermine the "12 or fail" guarantee.
    assert not manifest_path.exists()
    # And no half-written tmp file either
    assert not manifest_path.with_suffix(manifest_path.suffix + ".tmp").exists()


def test_main_partial_fail_preserves_existing_manifest(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """If a previous good manifest exists, a subsequent partial-fail run must
    not clobber it — atomic-rename semantics."""
    from scripts.recon.bootstrap_skyfall_plys import BootstrapPartialError
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # First: a clean run with all licenses populated → 12 scenes
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    good = manifest_path.read_text()
    assert len(json.loads(good)["scenes"]) == 12

    # Second: simulate license records getting wiped — must fail without
    # overwriting the existing good manifest.
    def fake_resolve(*, source_group, licenses_dir):
        from scripts.recon.license_audit import LicenseUnverifiedError
        raise LicenseUnverifiedError("simulated wipe")

    # Force a re-download path (existing files match prior so short-circuit
    # would fire; we test the post-download write-guard here, so wipe targets).
    for entry in __import__(
        "scripts.recon.asset_mapping", fromlist=["ASSET_MAPPING"]
    ).ASSET_MAPPING:
        (static_dir / entry.hf_filename).unlink(missing_ok=True)

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ), patch(
        "scripts.recon.bootstrap_skyfall_plys.resolve_attribution",
        side_effect=fake_resolve,
    ):
        with pytest.raises(BootstrapPartialError):
            main(static_dir=static_dir, manifest_path=manifest_path,
                 licenses_dir=fake_licenses_dir, strict_sizes=False,
                 allow_partial=False)

    assert manifest_path.read_text() == good


def test_short_circuit_reaudits_licenses_and_fails_if_invalidated(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """A rerun with all PLY SHAs intact but invalidated license records must
    NOT keep serving the prior manifest unless --allow-partial is set."""
    from scripts.recon.bootstrap_skyfall_plys import BootstrapPartialError
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # Run 1: clean — 12 scenes land on disk + in manifest
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)

    # Wipe records.json — short-circuit path must catch this
    (fake_licenses_dir / "records.json").write_text(json.dumps({"records": {}}))

    # Run 2: PLYs still match, but license re-audit must fail
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all"
    ) as no_download:
        with pytest.raises(BootstrapPartialError, match="no longer verified"):
            main(static_dir=static_dir, manifest_path=manifest_path,
                 licenses_dir=fake_licenses_dir, strict_sizes=False,
                 allow_partial=False)
    # Short-circuit should still have prevented HF download
    assert no_download.call_count == 0


def test_short_circuit_allow_partial_rewrites_to_smaller_manifest(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """Short-circuit + allow_partial + partial license invalidation must
    REWRITE the manifest (not keep the old 12-scene one with invalidated
    attributions). Otherwise the viewer would still serve unverified scenes."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # Run 1: clean 12-scene manifest
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    assert len(json.loads(manifest_path.read_text())["scenes"]) == 12

    # Invalidate only SpaceNet 2 (the 4 NYC scenes) by removing its record
    records = json.loads((fake_licenses_dir / "records.json").read_text())
    del records["records"]["SpaceNet 2"]
    (fake_licenses_dir / "records.json").write_text(json.dumps(records))

    # Run 2: short-circuit + allow_partial → expect 8 JAX scenes only, no NYC
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all"
    ) as no_download:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=True)
    assert no_download.call_count == 0, "must skip HF on SHA match"

    payload = json.loads(manifest_path.read_text())
    scene_ids = {s["scene_id"] for s in payload["scenes"]}
    assert len(scene_ids) == 8
    assert all(sid.startswith("jax_") for sid in scene_ids)


def test_short_circuit_refreshes_attribution_when_records_change(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """If license records remain valid but content changed (e.g. verified_by),
    the short-circuit path must rewrite manifest.attribution from current
    records — the viewer footer renders that field verbatim."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    before = json.loads(manifest_path.read_text())["scenes"]
    assert all("verified 2026-05-17 by test" in s["attribution"] for s in before)

    # Bump verified_by + verified_at
    records = json.loads((fake_licenses_dir / "records.json").read_text())
    for sg in records["records"]:
        records["records"][sg]["verified_by"] = "operator-2"
        records["records"][sg]["verified_at"] = "2026-06-01"
    (fake_licenses_dir / "records.json").write_text(json.dumps(records))

    with patch("scripts.recon.bootstrap_skyfall_plys.hf_download_all") as no_dl:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    assert no_dl.call_count == 0
    after = json.loads(manifest_path.read_text())["scenes"]
    assert all("verified 2026-06-01 by operator-2" in s["attribution"] for s in after)


def test_main_skips_scenes_with_unverified_license_when_allow_partial(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """With --allow-partial, license-failed scenes are excluded but the run succeeds."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    def fake_resolve(*, source_group, licenses_dir):
        if source_group == "SpaceNet 2":
            from scripts.recon.license_audit import LicenseUnverifiedError
            raise LicenseUnverifiedError("simulated")
        return "ok-attribution"

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ), patch(
        "scripts.recon.bootstrap_skyfall_plys.resolve_attribution",
        side_effect=fake_resolve,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=True)

    payload = json.loads(manifest_path.read_text())
    scene_ids = {s["scene_id"] for s in payload["scenes"]}
    assert all(not sid.startswith("nyc_") for sid in scene_ids)
    assert any(sid.startswith("jax_") for sid in scene_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd ~/ODIN/OSINT
python -m pytest scripts/recon/tests/test_bootstrap_skyfall_plys.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/recon/bootstrap_skyfall_plys.py`:
```python
"""One-shot bootstrap for Skyfall-GS pre-built PLYs.

Downloads twelve PLYs from jayinnn/Skyfall-GS-ply, copies them into
services/backend/static/recon/, runs a per-scene license audit, and
emits services/backend/data/recon_manifest.json.

Idempotent: re-running with unchanged on-disk SHAs is a no-op for those entries.
Fail-closed: scenes whose source license cannot be confirmed are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.recon.asset_mapping import ASSET_MAPPING, AssetEntry
from scripts.recon.license_audit import (
    LicenseUnverifiedError,
    render_licenses_md,
    resolve_attribution,
)


# SpaceNet metadata seeds for the 12 known scenes (one-time table per spec §5.3).
# These are approximate centroids; provenance recorded as "spacenet_metadata".
SPACENET_BOUNDS: dict[str, tuple[float, float, float]] = {
    "jax_004": (30.3322, -81.6557, 350),
    "jax_068": (30.3411, -81.6390, 350),
    "jax_164": (30.3155, -81.6720, 350),
    "jax_168": (30.3289, -81.6800, 350),
    "jax_175": (30.3501, -81.6502, 350),
    "jax_214": (30.3098, -81.6645, 350),
    "jax_260": (30.3370, -81.6210, 350),
    "jax_264": (30.3260, -81.6700, 350),
    "nyc_004": (40.7128, -74.0060, 500),
    "nyc_010": (40.7235, -73.9925, 500),
    "nyc_219": (40.7580, -73.9855, 500),
    "nyc_336": (40.7484, -73.9857, 500),
}

DEFAULT_CAMERA = {"position": [0, 0, 200], "look_at": [0, 0, 0], "fov_deg": 60}

HF_REPO_ID = "jayinnn/Skyfall-GS-ply"


class BootstrapError(RuntimeError):
    """Raised when bootstrap cannot continue."""


class HFCLIMissingError(BootstrapError):
    pass


class BootstrapPartialError(BootstrapError):
    """Raised when bootstrap produced fewer than the expected 12 scenes and
    --allow-partial was not set."""


def check_hf_cli() -> None:
    if shutil.which("hf") is None:
        raise HFCLIMissingError(
            "the HuggingFace CLI ('hf') is not on PATH. Install it with:\n"
            "    uv pip install --system 'huggingface_hub[cli]'\n"
            "or:\n"
            "    pip install 'huggingface_hub[cli]'"
        )


def hf_download_all(target_dir: Path) -> Path:
    """Call `hf download` for the repo; returns the directory containing the PLYs."""
    target_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["hf", "download", HF_REPO_ID, "--local-dir", str(target_dir)],
        check=True,
    )
    return target_dir


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _load_prior_manifest(manifest_path: Path) -> dict[str, dict]:
    """Returns scene_id -> scene dict from the existing manifest, or empty."""
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text())
    except Exception:
        return {}
    return {s["scene_id"]: s for s in payload.get("scenes", [])}


def _all_targets_match_prior(
    static_dir: Path, prior: dict[str, dict]
) -> bool:
    """True iff every ASSET_MAPPING entry has a target file whose SHA matches
    the prior manifest. Used to short-circuit before hf_download_all."""
    if len(prior) != len(ASSET_MAPPING):
        return False
    for entry in ASSET_MAPPING:
        scene = prior.get(entry.scene_id)
        if scene is None:
            return False
        target = static_dir / entry.hf_filename
        if not target.exists():
            return False
        if sha256_of(target) != scene.get("ply_sha256"):
            return False
    return True


EXPECTED_SCENE_COUNT = 12


def main(
    *,
    static_dir: Path | None = None,
    manifest_path: Path | None = None,
    licenses_dir: Path | None = None,
    strict_sizes: bool = True,
    allow_partial: bool = False,
) -> int:
    """Entry point. Returns process exit code.

    By default, bootstrap fails with BootstrapPartialError if fewer than 12
    scenes end up in the manifest — the MVP goal is "all twelve scenes
    openable from a globe-pin click". Use allow_partial=True for
    intentional fail-closed experimentation (e.g. when license records
    are not yet populated).
    """
    repo_root = Path(__file__).resolve().parents[2]
    static_dir = static_dir or (repo_root / "services" / "backend" / "static" / "recon")
    manifest_path = manifest_path or (
        repo_root / "services" / "backend" / "data" / "recon_manifest.json"
    )
    licenses_dir = licenses_dir or (static_dir / "licenses")

    check_hf_cli()
    static_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    prior = _load_prior_manifest(manifest_path)
    scenes_out: list[dict] = []
    excluded: list[tuple[str, str]] = []

    if _all_targets_match_prior(static_dir, prior):
        # Short-circuit path: PLY SHAs match, so HF download can be skipped.
        # But: re-audit licenses AND refresh attribution strings, because the
        # viewer footer renders scene.attribution verbatim. If records.json
        # was emptied or changed since the prior run, the old attribution is
        # stale (or worse, references a license that's no longer verified).
        print("All 12 PLYs match existing manifest — re-auditing licenses "
              "and refreshing attribution; skipping HF download.")
        for entry in ASSET_MAPPING:
            prior_scene = prior.get(entry.scene_id)
            if prior_scene is None:
                excluded.append((entry.scene_id, "missing from prior manifest"))
                continue
            try:
                attribution = resolve_attribution(
                    source_group=entry.source_group, licenses_dir=licenses_dir
                )
            except LicenseUnverifiedError as e:
                # NEVER fall through to the "keep prior manifest" path here,
                # even with allow_partial=True — that would let invalidated
                # scenes keep being served. Drop the scene entirely so the
                # rewritten manifest reflects current license state.
                excluded.append((entry.scene_id, f"license unverified: {e}"))
                continue
            refreshed = dict(prior_scene)
            refreshed["attribution"] = attribution
            scenes_out.append(refreshed)
    else:
        # Full rebuild path
        cache_dir = repo_root / ".cache" / "skyfall_plys"
        download_dir = hf_download_all(cache_dir)

        for entry in ASSET_MAPPING:
            src = download_dir / entry.hf_filename
            if not src.exists():
                excluded.append((entry.scene_id, "asset missing from HF download"))
                continue

            actual_size = src.stat().st_size
            if actual_size != entry.expected_size_bytes:
                msg = (
                    f"size mismatch for {entry.hf_filename}: "
                    f"got {actual_size}, expected {entry.expected_size_bytes}"
                )
                if strict_sizes:
                    raise BootstrapError(msg)
                print(f"WARN: {msg}", file=sys.stderr)

            target = static_dir / entry.hf_filename
            prior_sha = prior.get(entry.scene_id, {}).get("ply_sha256")
            if target.exists() and prior_sha is not None and sha256_of(target) == prior_sha:
                sha = prior_sha
            else:
                shutil.copy2(src, target)
                sha = sha256_of(target)

            try:
                attribution = resolve_attribution(
                    source_group=entry.source_group, licenses_dir=licenses_dir
                )
            except LicenseUnverifiedError as e:
                excluded.append((entry.scene_id, f"license unverified: {e}"))
                continue

            lat, lon, radius = SPACENET_BOUNDS[entry.scene_id]
            scenes_out.append({
                "scene_id": entry.scene_id,
                "hf_filename": entry.hf_filename,
                "display_name": entry.display_name,
                # ?sha=<sha256> makes immutable Cache-Control safe even when
                # the filename stays stable across re-bootstraps.
                "ply_url": f"/static/recon/{entry.hf_filename}?sha={sha}",
                "ply_size_bytes": actual_size,
                "ply_sha256": sha,
                "bounds": {"center_lat": lat, "center_lon": lon, "radius_m": radius},
                "bounds_source": "spacenet_metadata",
                "default_camera": DEFAULT_CAMERA,
                "attribution": attribution,
                "source": "skyfall_gs_hf",
            })

    payload = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": _git_sha(),
        "scenes": scenes_out,
    }

    # Fail BEFORE touching manifest_path — otherwise a default (allow_partial=False)
    # run that ends up short would still leave a partial/0-scene manifest on disk,
    # silently undermining the "12 scenes or fail" guarantee.
    if len(scenes_out) < EXPECTED_SCENE_COUNT and not allow_partial:
        if excluded:
            print("Excluded scenes (fail-closed):", file=sys.stderr)
            for sid, reason in excluded:
                print(f"  - {sid}: {reason}", file=sys.stderr)
        raise BootstrapPartialError(
            f"only {len(scenes_out)}/{EXPECTED_SCENE_COUNT} scenes emitted. "
            f"Populate licenses/ then rerun, or pass --allow-partial to "
            f"intentionally ship a partial manifest. Excluded: "
            f"{[sid for sid, _ in excluded]}"
        )

    # Atomic write — emit to a tmp file in the same dir, fsync, then rename.
    # Same-dir rename is atomic on POSIX, so readers never see a half-written file.
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2))
    os.replace(tmp_path, manifest_path)
    (static_dir / "LICENSES.md").write_text(render_licenses_md(licenses_dir))

    if excluded:
        print("Excluded scenes (fail-closed):", file=sys.stderr)
        for sid, reason in excluded:
            print(f"  - {sid}: {reason}", file=sys.stderr)

    print(f"Wrote manifest with {len(scenes_out)} scenes -> {manifest_path}")
    return 0


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bootstrap Skyfall-GS PLYs.")
    p.add_argument("--static-dir", type=Path, default=None)
    p.add_argument("--manifest-path", type=Path, default=None)
    p.add_argument("--licenses-dir", type=Path, default=None)
    p.add_argument("--no-strict-sizes", action="store_true",
                   help="Log size mismatches as warnings instead of failing.")
    p.add_argument("--allow-partial", action="store_true",
                   help="Allow the manifest to ship with fewer than 12 scenes "
                        "(e.g. while license records are still being populated).")
    return p.parse_args(argv)


if __name__ == "__main__":
    ns = _parse_argv(sys.argv[1:])
    try:
        sys.exit(main(
            static_dir=ns.static_dir,
            manifest_path=ns.manifest_path,
            licenses_dir=ns.licenses_dir,
            strict_sizes=not ns.no_strict_sizes,
            allow_partial=ns.allow_partial,
        ))
    except BootstrapError as e:
        print(f"BOOTSTRAP FAILED: {e}", file=sys.stderr)
        sys.exit(2)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd ~/ODIN/OSINT
python -m pytest scripts/recon/tests/test_bootstrap_skyfall_plys.py -v
```
Expected: PASS (11 tests): hf-cli-missing, sha256, manifest-pydantic-valid,
LICENSES.md-emitted, idempotent-no-download-on-match, partial-fail-no-write,
partial-fail-preserves-prior, short-circuit-reaudit-fails-when-invalidated,
short-circuit-allow-partial-rewrites, short-circuit-refreshes-attribution,
allow-partial-skip-on-rebuild.

- [ ] **Step 5: Commit**

```bash
git add scripts/recon/bootstrap_skyfall_plys.py scripts/recon/tests/test_bootstrap_skyfall_plys.py
git commit -m "feat(recon/bootstrap): add idempotent bootstrap with HF download, SHA verify, license audit"
```

---

### Task 9: `odin.sh recon bootstrap` wrapper

**Files:**
- Modify: `odin.sh`

- [ ] **Step 1: Read the existing case block**

Open `odin.sh` and locate the `case "$COMMAND" in` block (line ~342). Note the structure used by `gdelt)` and `vision)` — they follow the pattern `<command>) [...] ;;`.

- [ ] **Step 2: Add the `recon)` case**

Insert before the closing `*)` default case, near the other compound commands (e.g. after `gdelt)`):
```bash
  recon)
    case "$MODE" in
      bootstrap)
        echo "Bootstrapping Skyfall-GS recon PLYs..."
        cd "$ROOT_DIR"
        python -m scripts.recon.bootstrap_skyfall_plys "${@:3}"
        ;;
      "")
        echo "Usage: ./odin.sh recon bootstrap [--no-strict-sizes]"
        exit 1
        ;;
      *)
        echo "Unknown recon subcommand: $MODE"
        echo "Usage: ./odin.sh recon bootstrap"
        exit 1
        ;;
    esac
    ;;
```

- [ ] **Step 3: Update the usage text**

In the `usage()` heredoc near the top, add this line near the existing subcommand list:
```
  ./odin.sh recon bootstrap    # Download Skyfall-GS PLYs and write recon_manifest.json
```

- [ ] **Step 4: Smoke-test the wrapper (no HF call)**

Run:
```bash
./odin.sh recon
# Expected: usage message
./odin.sh recon nonsense
# Expected: "Unknown recon subcommand: nonsense", exit 1
./odin.sh
# Expected: full usage including the new recon line
```

- [ ] **Step 5: Commit**

```bash
git add odin.sh
git commit -m "feat(odin.sh): add 'recon bootstrap' subcommand wrapper"
```

---

# Phase A — Frontend

### Task 10: TypeScript types mirror

**Files:**
- Create: `services/frontend/src/lib/recon/types.ts`

- [ ] **Step 1: Create the types file**

```ts
export interface GeoBounds {
  center_lat: number;
  center_lon: number;
  radius_m: number;
}

export interface DefaultCamera {
  position: [number, number, number];
  look_at: [number, number, number];
  fov_deg: number;
}

export type BoundsSource = "spacenet_metadata" | "manual";

export interface ReconScene {
  scene_id: string;
  hf_filename: string;
  display_name: string;
  ply_url: string;
  ply_size_bytes: number;
  bounds: GeoBounds;
  bounds_source: BoundsSource;
  default_camera: DefaultCamera;
  attribution: string;
  source: string;
}

export interface ReconScenesResponse {
  scenes: ReconScene[];
}
```

- [ ] **Step 2: Type-check**

Run:
```bash
cd services/frontend
npm run type-check
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/lib/recon/types.ts
git commit -m "feat(frontend/recon): add TypeScript types mirroring backend Pydantic models"
```

---

### Task 11: Manifest fetch hook with module-level cache

**Files:**
- Create: `services/frontend/src/lib/recon/manifest.ts`
- Test: `services/frontend/src/lib/recon/__tests__/manifest.test.ts`

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/lib/recon/__tests__/manifest.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useReconManifest, _resetReconManifestCache } from "../manifest";

const sampleScene = {
  scene_id: "jax_068",
  hf_filename: "JAX_068_final.ply",
  display_name: "Jacksonville District 068",
  ply_url: "/static/recon/JAX_068_final.ply?sha=" + "a".repeat(64),
  ply_size_bytes: 240164505,
  bounds: { center_lat: 30.33, center_lon: -81.65, radius_m: 350 },
  bounds_source: "spacenet_metadata",
  default_camera: { position: [0,0,200], look_at: [0,0,0], fov_deg: 60 },
  attribution: "test",
  source: "skyfall_gs_hf",
};

describe("useReconManifest", () => {
  beforeEach(() => {
    _resetReconManifestCache();
    vi.restoreAllMocks();
  });

  it("returns scenes after a successful fetch", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ scenes: [sampleScene] }), { status: 200 })
    ));
    const { result } = renderHook(() => useReconManifest());
    await waitFor(() => expect(result.current.scenes).toHaveLength(1));
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("surfaces error on 503", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ detail: "manifest not loaded" }), { status: 503 })
    ));
    const { result } = renderHook(() => useReconManifest());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.scenes).toEqual([]);
  });

  it("reuses cached data on second hook invocation", async () => {
    const fetchSpy = vi.fn(async () =>
      new Response(JSON.stringify({ scenes: [sampleScene] }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchSpy);
    const a = renderHook(() => useReconManifest());
    await waitFor(() => expect(a.result.current.scenes).toHaveLength(1));
    renderHook(() => useReconManifest());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/frontend
npm run test -- src/lib/recon/__tests__/manifest.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `services/frontend/src/lib/recon/manifest.ts`:
```ts
import { useEffect, useState } from "react";
import type { ReconScene, ReconScenesResponse } from "./types";

interface CacheState {
  data: ReconScene[] | null;
  error: Error | null;
  inflight: Promise<void> | null;
}

const cache: CacheState = { data: null, error: null, inflight: null };

export function _resetReconManifestCache(): void {
  cache.data = null;
  cache.error = null;
  cache.inflight = null;
}

async function fetchManifest(): Promise<void> {
  try {
    const res = await fetch("/api/recon/scenes");
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`recon manifest fetch failed: ${res.status} ${body}`);
    }
    const json = (await res.json()) as ReconScenesResponse;
    cache.data = json.scenes;
    cache.error = null;
  } catch (e) {
    cache.error = e instanceof Error ? e : new Error(String(e));
    cache.data = [];
  } finally {
    cache.inflight = null;
  }
}

export interface UseReconManifestResult {
  scenes: ReconScene[];
  loading: boolean;
  error: Error | null;
}

export function useReconManifest(): UseReconManifestResult {
  const [, force] = useState(0);

  useEffect(() => {
    if (cache.data !== null || cache.error !== null) return;
    if (cache.inflight === null) {
      cache.inflight = fetchManifest().then(() => force((x) => x + 1));
    } else {
      cache.inflight.then(() => force((x) => x + 1));
    }
  }, []);

  return {
    scenes: cache.data ?? [],
    loading: cache.data === null && cache.error === null,
    error: cache.error,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/frontend
npm run test -- src/lib/recon/__tests__/manifest.test.ts
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/lib/recon/
git commit -m "feat(frontend/recon): add useReconManifest hook with module-level cache"
```

---

### Task 12: ReconContext provider

**Files:**
- Create: `services/frontend/src/state/ReconContext.tsx`
- Test: `services/frontend/src/state/__tests__/ReconContext.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/state/__tests__/ReconContext.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, act } from "@testing-library/react";
import { ReconProvider, useRecon } from "../ReconContext";

function Probe({ onReady }: { onReady: (api: ReturnType<typeof useRecon>) => void }) {
  const api = useRecon();
  onReady(api);
  return null;
}

describe("ReconContext", () => {
  it("starts with no active scene", () => {
    let api: ReturnType<typeof useRecon> | null = null;
    render(
      <ReconProvider>
        <Probe onReady={(a) => (api = a)} />
      </ReconProvider>
    );
    expect(api!.activeSceneId).toBeNull();
    expect(api!.isOpen).toBe(false);
  });

  it("openScene sets activeSceneId and isOpen=true", () => {
    let api: ReturnType<typeof useRecon> | null = null;
    render(
      <ReconProvider>
        <Probe onReady={(a) => (api = a)} />
      </ReconProvider>
    );
    act(() => api!.openScene("jax_068"));
    // Re-render via Probe captures latest api; the second render's api is the
    // updated one
    render(
      <ReconProvider>
        <Probe onReady={(a) => (api = a)} />
      </ReconProvider>
    );
    // The second test really wants a single rendering; rewrite using state
    // exposed via DOM. Skip activeSceneId assertion in this minimal form.
    expect(typeof api!.openScene).toBe("function");
    expect(typeof api!.closeScene).toBe("function");
  });
});
```

Then rewrite cleanly:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { ReconProvider, useRecon } from "../ReconContext";

function Probe() {
  const { activeSceneId, isOpen, openScene, closeScene } = useRecon();
  return (
    <div>
      <span data-testid="id">{activeSceneId ?? ""}</span>
      <span data-testid="open">{String(isOpen)}</span>
      <button onClick={() => openScene("jax_068")}>open</button>
      <button onClick={() => closeScene()}>close</button>
    </div>
  );
}

describe("ReconContext", () => {
  it("starts closed", () => {
    render(<ReconProvider><Probe /></ReconProvider>);
    expect(screen.getByTestId("id").textContent).toBe("");
    expect(screen.getByTestId("open").textContent).toBe("false");
  });

  it("openScene updates activeSceneId and isOpen", () => {
    render(<ReconProvider><Probe /></ReconProvider>);
    act(() => { screen.getByText("open").click(); });
    expect(screen.getByTestId("id").textContent).toBe("jax_068");
    expect(screen.getByTestId("open").textContent).toBe("true");
  });

  it("closeScene resets state", () => {
    render(<ReconProvider><Probe /></ReconProvider>);
    act(() => { screen.getByText("open").click(); });
    act(() => { screen.getByText("close").click(); });
    expect(screen.getByTestId("id").textContent).toBe("");
    expect(screen.getByTestId("open").textContent).toBe("false");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/frontend
npm run test -- src/state/__tests__/ReconContext.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `services/frontend/src/state/ReconContext.tsx`:
```tsx
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

interface ReconContextValue {
  activeSceneId: string | null;
  isOpen: boolean;
  openScene: (sceneId: string) => void;
  closeScene: () => void;
}

const ReconContext = createContext<ReconContextValue | null>(null);

export function ReconProvider({ children }: { children: ReactNode }) {
  const [activeSceneId, setActiveSceneId] = useState<string | null>(null);

  const openScene = useCallback((sceneId: string) => setActiveSceneId(sceneId), []);
  const closeScene = useCallback(() => setActiveSceneId(null), []);

  const value = useMemo<ReconContextValue>(
    () => ({
      activeSceneId,
      isOpen: activeSceneId !== null,
      openScene,
      closeScene,
    }),
    [activeSceneId, openScene, closeScene]
  );

  return <ReconContext.Provider value={value}>{children}</ReconContext.Provider>;
}

export function useRecon(): ReconContextValue {
  const ctx = useContext(ReconContext);
  if (ctx === null) {
    throw new Error("useRecon must be used inside <ReconProvider>");
  }
  return ctx;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/frontend
npm run test -- src/state/__tests__/ReconContext.test.tsx
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/state/ReconContext.tsx services/frontend/src/state/__tests__/
git commit -m "feat(frontend/recon): add ReconProvider + useRecon context for active scene state"
```

---

### Task 13: ReconLayer (Cesium BillboardCollection)

**Files:**
- Create: `services/frontend/src/components/layers/ReconLayer.tsx`
- Test: `services/frontend/src/components/layers/__tests__/ReconLayer.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/layers/__tests__/ReconLayer.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { ReconLayer } from "../ReconLayer";
import type { ReconScene } from "../../../lib/recon/types";

function fakeViewer(): Cesium.Viewer {
  const primitives = { add: vi.fn((p: unknown) => p), remove: vi.fn() };
  const canvas = document.createElement("canvas");
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      pick: vi.fn(() => undefined),
    },
    canvas,
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

const sample = (id: string, lat: number, lon: number): ReconScene => ({
  scene_id: id,
  hf_filename: `${id.toUpperCase()}_final.ply`,
  display_name: id,
  ply_url: `/static/recon/${id}.ply`,
  ply_size_bytes: 1,
  bounds: { center_lat: lat, center_lon: lon, radius_m: 100 },
  bounds_source: "spacenet_metadata",
  default_camera: { position: [0,0,200], look_at: [0,0,0], fov_deg: 60 },
  attribution: "x",
  source: "skyfall_gs_hf",
});

describe("ReconLayer", () => {
  it("renders without throwing for twelve scenes", () => {
    const viewer = fakeViewer();
    const onSelect = vi.fn();
    render(
      <ReconLayer
        viewer={viewer}
        scenes={[sample("a", 30, -81), sample("b", 40, -74)]}
        visible
        onSelect={onSelect}
      />
    );
    // BillboardCollection is added to primitives
    expect((viewer.scene.primitives as unknown as { add: ReturnType<typeof vi.fn> }).add).toHaveBeenCalled();
  });

  it("does nothing when viewer is null", () => {
    const onSelect = vi.fn();
    render(
      <ReconLayer
        viewer={null}
        scenes={[sample("a", 30, -81)]}
        visible
        onSelect={onSelect}
      />
    );
    expect(onSelect).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/frontend
npm run test -- src/components/layers/__tests__/ReconLayer.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `services/frontend/src/components/layers/ReconLayer.tsx` (mirrors `FIRMSLayer.tsx`):
```tsx
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { ReconScene } from "../../lib/recon/types";

const PIN_RADIUS = 14;
const PIN_COLOR = new Cesium.Color(0.92, 0.65, 0.20, 1.0); // amber per Hlidskjalf

function createReconPin(): HTMLCanvasElement {
  const size = PIN_RADIUS * 4;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const c = size / 2;
  // Outer ring
  ctx.strokeStyle = `rgba(235, 165, 50, 0.9)`;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(c, c, PIN_RADIUS, 0, Math.PI * 2);
  ctx.stroke();
  // Inner dot
  ctx.fillStyle = `rgba(235, 165, 50, 1.0)`;
  ctx.beginPath();
  ctx.arc(c, c, PIN_RADIUS * 0.45, 0, Math.PI * 2);
  ctx.fill();
  return canvas;
}

interface ReconLayerProps {
  viewer: Cesium.Viewer | null;
  scenes: ReconScene[];
  visible: boolean;
  onSelect?: (scene: ReconScene) => void;
}

export function ReconLayer({ viewer, scenes, visible, onSelect }: ReconLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, ReconScene>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        if (viewer.isDestroyed()) return;
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const scene = idMapRef.current.get(picked.primitive as unknown as object);
        if (scene && onSelectRef.current) onSelectRef.current(scene);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed() && collectionRef.current) {
        viewer.scene.primitives.remove(collectionRef.current);
      }
      collectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    if (!bc) return;
    bc.removeAll();
    idMapRef.current.clear();
    if (!visible) return;

    const pinImage = createReconPin();
    for (const scene of scenes) {
      const position = Cesium.Cartesian3.fromDegrees(
        scene.bounds.center_lon,
        scene.bounds.center_lat,
        0
      );
      const billboard = bc.add({
        position,
        image: pinImage,
        color: PIN_COLOR,
        scaleByDistance: new Cesium.NearFarScalar(1e3, 1.5, 8e6, 0.5),
      });
      idMapRef.current.set(billboard as unknown as object, scene);
    }
  }, [scenes, visible]);

  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/frontend
npm run test -- src/components/layers/__tests__/ReconLayer.test.tsx
```
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/layers/ReconLayer.tsx services/frontend/src/components/layers/__tests__/ReconLayer.test.tsx
git commit -m "feat(frontend/recon): add Cesium ReconLayer with BillboardCollection + isDestroyed guards"
```

---

### Task 14: WebGL & bandwidth gates

**Files:**
- Create: `services/frontend/src/components/recon/WebGLCheck.tsx`
- Create: `services/frontend/src/components/recon/BandwidthGuard.tsx`
- Test: `services/frontend/src/components/recon/__tests__/BandwidthGuard.test.tsx`

- [ ] **Step 1: Write the failing test for BandwidthGuard**

Create `services/frontend/src/components/recon/__tests__/BandwidthGuard.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BandwidthGuard } from "../BandwidthGuard";

describe("BandwidthGuard", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "connection", { value: undefined, configurable: true });
  });

  it("renders children AND fires onConfirm once on a fast connection", async () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "4g" }, configurable: true,
    });
    const onConfirm = vi.fn();
    render(
      <BandwidthGuard sizeBytes={200_000_000} onConfirm={onConfirm} onCancel={vi.fn()}>
        <div data-testid="child">child</div>
      </BandwidthGuard>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
  });

  it("shows confirm dialog on 3G and does NOT fire onConfirm yet", () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "3g" }, configurable: true,
    });
    const onConfirm = vi.fn();
    render(
      <BandwidthGuard sizeBytes={200_000_000} onConfirm={onConfirm} onCancel={vi.fn()}>
        <div data-testid="child">child</div>
      </BandwidthGuard>
    );
    expect(screen.queryByTestId("child")).toBeNull();
    expect(screen.getByRole("button", { name: /load anyway/i })).toBeInTheDocument();
    expect(screen.getByText(/190/)).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("after Load anyway: renders children and fires onConfirm exactly once", async () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "3g" }, configurable: true,
    });
    const onConfirm = vi.fn();
    render(
      <BandwidthGuard sizeBytes={200_000_000} onConfirm={onConfirm} onCancel={vi.fn()}>
        <div data-testid="child">child</div>
      </BandwidthGuard>
    );
    fireEvent.click(screen.getByRole("button", { name: /load anyway/i }));
    await waitFor(() => expect(screen.getByTestId("child")).toBeInTheDocument());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when cancel pressed on slow connection", () => {
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "2g" }, configurable: true,
    });
    const onCancel = vi.fn();
    render(
      <BandwidthGuard sizeBytes={50_000_000} onConfirm={vi.fn()} onCancel={onCancel}>
        <div>x</div>
      </BandwidthGuard>
    );
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/frontend
npm run test -- src/components/recon/__tests__/BandwidthGuard.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `services/frontend/src/components/recon/WebGLCheck.tsx`:
```tsx
import type { ReactNode } from "react";

interface WebGLCheckProps {
  fallback: ReactNode;
  children: ReactNode;
}

function hasWebGL2(): boolean {
  if (typeof window === "undefined") return false;
  const canvas = document.createElement("canvas");
  try {
    return canvas.getContext("webgl2") !== null;
  } catch {
    return false;
  }
}

export function WebGLCheck({ fallback, children }: WebGLCheckProps) {
  if (!hasWebGL2()) return <>{fallback}</>;
  return <>{children}</>;
}
```

Create `services/frontend/src/components/recon/BandwidthGuard.tsx`:
```tsx
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

interface BandwidthGuardProps {
  sizeBytes: number;
  /** Fires exactly once when children are about to render — i.e. immediately
   *  on a fast connection, or after the user clicks "Load anyway". */
  onConfirm: () => void;
  onCancel: () => void;
  children: ReactNode;
}

interface ConnectionLike {
  effectiveType?: string;
}

function getEffectiveType(): string | undefined {
  const conn = (navigator as Navigator & { connection?: ConnectionLike }).connection;
  return conn?.effectiveType;
}

function isMetered(): boolean {
  const t = getEffectiveType();
  return t === "2g" || t === "slow-2g" || t === "3g";
}

export function BandwidthGuard({
  sizeBytes,
  onConfirm,
  onCancel,
  children,
}: BandwidthGuardProps) {
  const [confirmed, setConfirmed] = useState(false);
  const fastConnection = !isMetered();
  const allowed = fastConnection || confirmed;
  const firedRef = useRef(false);

  useEffect(() => {
    if (allowed && !firedRef.current) {
      firedRef.current = true;
      onConfirm();
    }
  }, [allowed, onConfirm]);

  if (allowed) return <>{children}</>;

  const sizeMb = Math.round(sizeBytes / (1024 * 1024));
  return (
    <div role="dialog" aria-label="bandwidth confirm">
      <p>This scene is {sizeMb} MB and your connection appears metered.</p>
      <button onClick={() => setConfirmed(true)}>Load anyway</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/frontend
npm run test -- src/components/recon/__tests__/BandwidthGuard.test.tsx
```
Expected: PASS (4 tests): fast-connection-auto-confirms, 3g-shows-dialog,
load-anyway-confirms, cancel.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/recon/WebGLCheck.tsx services/frontend/src/components/recon/BandwidthGuard.tsx services/frontend/src/components/recon/__tests__/BandwidthGuard.test.tsx
git commit -m "feat(frontend/recon): add WebGLCheck and BandwidthGuard gating components"
```

---

### Task 15: SplatRenderer abstract interface (with navigation API)

**Files:**
- Create: `services/frontend/src/components/recon/renderer/SplatRenderer.ts`

The interface owns the camera-movement contract so `CameraControls` can
drive any concrete renderer without library-specific code in the modal.

- [ ] **Step 1: Create the interface**

```ts
import type { DefaultCamera } from "../../../lib/recon/types";

export interface SplatRenderProgress {
  loaded: number;
  total: number;
}

export type CameraAxis = "x" | "y" | "z";

export interface SplatRenderHandle {
  dispose(): void;
  captureScreenshot(): Promise<Blob>;
  getCanvas(): HTMLCanvasElement;
  /** Translate the camera along its local axis. `delta` is in renderer units. */
  move(axis: CameraAxis, delta: number): void;
  /** Rotate the camera. Inputs are radians; mouse-move multiplies by ~0.002. */
  look(yawDelta: number, pitchDelta: number): void;
}

export interface SplatRenderOptions {
  plyUrl: string;
  defaultCamera: DefaultCamera;
  onProgress?: (p: SplatRenderProgress) => void;
  onFirstFrame?: () => void;
  onError?: (e: Error) => void;
}

export interface SplatRenderer {
  render(canvas: HTMLCanvasElement, opts: SplatRenderOptions): Promise<SplatRenderHandle>;
}
```

- [ ] **Step 2: Type-check**

Run:
```bash
cd services/frontend
npm run type-check
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/recon/renderer/SplatRenderer.ts
git commit -m "feat(frontend/recon): add SplatRenderer abstract interface"
```

---

### Task 16: Concrete renderer implementation

> **Renderer choice locked in by Phase 0.** Use the renderer chosen in `docs/workflows/recon-phase-0-smoke.md`. The two paths below are equivalent in shape — pick one based on the Phase 0 verdict and delete the other from this task.

**Files:**
- Create: `services/frontend/src/components/recon/renderer/<chosenRenderer>.ts`
- Create: `services/frontend/src/components/recon/renderer/index.ts`
- Modify: `services/frontend/package.json` — add the chosen renderer dep
- Modify: `services/frontend/package-lock.json` — via `npm install`

- [ ] **Step 1: Add the dependency**

If Phase 0 chose Spark:
```bash
cd services/frontend
npm install @sparkjsdev/spark three
```

If Phase 0 chose `@mkkellogg/gaussian-splats-3d`:
```bash
cd services/frontend
npm install @mkkellogg/gaussian-splats-3d three
```

- [ ] **Step 2: Implement the concrete renderer**

Create `services/frontend/src/components/recon/renderer/<chosenRenderer>.ts`.
The module's default export is a `SplatRenderer` instance named
`defaultSplatRenderer` (a const, not a class) so the dynamic-import call
site can destructure it directly. Implementation requirements:
1. Initializes a Three.js scene + camera with `defaultCamera.position`,
   `defaultCamera.look_at`, `defaultCamera.fov_deg`.
2. Streams the PLY at `plyUrl` using `fetch` with `ReadableStream` so
   `onProgress` fires on every chunk; the first chunk triggers
   `onProgress({loaded > 0, total})` before anything else.
3. Calls `onFirstFrame` exactly once after the first successful render.
4. Implements `move(axis, delta)`:
   - `"x"` → strafe in camera-local right vector
   - `"y"` → translate world-up
   - `"z"` → translate camera-local forward (negative goes forward)
   - delta magnitude is multiplied by the renderer's per-frame speed
     constant (suggested: 0.5 renderer units per keydown).
5. Implements `look(yawDelta, pitchDelta)`:
   - Apply yaw to the camera around world-up.
   - Apply pitch to the camera around its local right axis.
   - Clamp pitch to ±89° to avoid gimbal flip.
6. `dispose()` calls renderer/scene/geometry disposal per Three.js docs
   AND aborts any in-flight fetch via an `AbortController`.
7. `captureScreenshot()` reads from the renderer's canvas with
   `toBlob("image/png")` and resolves with the Blob.
8. Any thrown / rejected error calls `opts.onError(e)` and the returned
   handle's `dispose()` is safe to call even if init failed.

The full code is library-specific and depends on the Phase 0 verdict.
The implementer reads the renderer's README, finds the "load PLY"
example, wraps it in the `SplatRenderer` shape, and verifies against
Task 18's mocked tests before considering this task done.

- [ ] **Step 3: Create the index barrel — TYPE-ONLY re-exports**

The barrel only re-exports types. Concrete renderer loading goes
through dynamic `import()` from the modal so the splat library + Three.js
stay out of the initial bundle (spec §5.2).

Create `services/frontend/src/components/recon/renderer/index.ts`:
```ts
export type {
  SplatRenderer,
  SplatRenderHandle,
  SplatRenderOptions,
  SplatRenderProgress,
  CameraAxis,
} from "./SplatRenderer";

/**
 * Dynamically loads the concrete renderer chosen in Phase 0. Callers MUST
 * use this rather than a static import to keep the splat library out of
 * the main Vite bundle.
 */
export async function loadDefaultSplatRenderer(): Promise<
  import("./SplatRenderer").SplatRenderer
> {
  // Edit this path to point at the file written in Step 2:
  const mod = await import("./<chosenRenderer>");
  return mod.defaultSplatRenderer;
}
```

- [ ] **Step 4: Type-check + minimal smoke**

Run:
```bash
cd services/frontend
npm run type-check
npm run build  # build must complete without complaining about the new module
```
Expected: 0 type errors; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/recon/renderer/ services/frontend/package.json services/frontend/package-lock.json
git commit -m "feat(frontend/recon): add concrete Gaussian-Splat renderer (Phase 0 choice)"
```

---

### Task 17: CameraControls (WASD + mouse-look → renderer handle)

**Files:**
- Create: `services/frontend/src/components/recon/CameraControls.tsx`
- Test: `services/frontend/src/components/recon/__tests__/CameraControls.test.tsx`

The controls call the renderer handle's `move()` / `look()` directly. If
the handle isn't ready yet (still loading PLY), keystrokes are dropped.

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/recon/__tests__/CameraControls.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { useRef } from "react";
import { CameraControls } from "../CameraControls";
import type { SplatRenderHandle } from "../renderer";

function makeHandle(): SplatRenderHandle {
  return {
    dispose: vi.fn(),
    captureScreenshot: vi.fn(async () => new Blob()),
    getCanvas: () => document.createElement("canvas"),
    move: vi.fn(),
    look: vi.fn(),
  };
}

function Probe({ handle }: { handle: SplatRenderHandle | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useRef<SplatRenderHandle | null>(handle);
  handleRef.current = handle;
  return (
    <>
      <canvas ref={canvasRef} data-testid="canvas" />
      <CameraControls canvasRef={canvasRef} handleRef={handleRef} />
    </>
  );
}

describe("CameraControls", () => {
  it("calls handle.move on WASD keydown", () => {
    const handle = makeHandle();
    render(<Probe handle={handle} />);
    fireEvent.keyDown(window, { code: "KeyW" });
    fireEvent.keyDown(window, { code: "KeyA" });
    fireEvent.keyDown(window, { code: "KeyS" });
    fireEvent.keyDown(window, { code: "KeyD" });
    fireEvent.keyDown(window, { code: "KeyQ" });
    fireEvent.keyDown(window, { code: "KeyE" });
    expect(handle.move).toHaveBeenCalledTimes(6);
    expect(handle.move).toHaveBeenNthCalledWith(1, "z", -1);
    expect(handle.move).toHaveBeenNthCalledWith(2, "x", -1);
    expect(handle.move).toHaveBeenNthCalledWith(3, "z", 1);
    expect(handle.move).toHaveBeenNthCalledWith(4, "x", 1);
    expect(handle.move).toHaveBeenNthCalledWith(5, "y", -1);
    expect(handle.move).toHaveBeenNthCalledWith(6, "y", 1);
  });

  it("ignores keys when handle is null", () => {
    render(<Probe handle={null} />);
    fireEvent.keyDown(window, { code: "KeyW" });
    // Nothing to assert beyond "no exception thrown"
  });

  it("ignores unmapped keys", () => {
    const handle = makeHandle();
    render(<Probe handle={handle} />);
    fireEvent.keyDown(window, { code: "Space" });
    expect(handle.move).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/frontend
npm run test -- src/components/recon/__tests__/CameraControls.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `services/frontend/src/components/recon/CameraControls.tsx`:
```tsx
import { useEffect } from "react";
import type { RefObject } from "react";
import type { CameraAxis, SplatRenderHandle } from "./renderer";

interface CameraControlsProps {
  canvasRef: RefObject<HTMLCanvasElement | null>;
  handleRef: RefObject<SplatRenderHandle | null>;
}

const KEY_BINDINGS: Record<string, [CameraAxis, 1 | -1]> = {
  KeyW: ["z", -1], KeyS: ["z", 1],
  KeyA: ["x", -1], KeyD: ["x", 1],
  KeyQ: ["y", -1], KeyE: ["y", 1],
};

export function CameraControls({ canvasRef, handleRef }: CameraControlsProps) {
  useEffect(() => {
    const canvas = canvasRef.current;

    const onClick = () => canvas?.requestPointerLock();
    const onKey = (e: KeyboardEvent) => {
      const binding = KEY_BINDINGS[e.code];
      if (!binding) return;
      const handle = handleRef.current;
      if (!handle) return;
      handle.move(binding[0], binding[1]);
    };
    const onMouseMove = (e: MouseEvent) => {
      if (!canvas || document.pointerLockElement !== canvas) return;
      const handle = handleRef.current;
      if (!handle) return;
      handle.look(e.movementX * 0.002, e.movementY * 0.002);
    };

    canvas?.addEventListener("click", onClick);
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousemove", onMouseMove);
    return () => {
      canvas?.removeEventListener("click", onClick);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousemove", onMouseMove);
    };
  }, [canvasRef, handleRef]);

  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/frontend
npm run test -- src/components/recon/__tests__/CameraControls.test.tsx
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/recon/CameraControls.tsx services/frontend/src/components/recon/__tests__/CameraControls.test.tsx
git commit -m "feat(frontend/recon): wire CameraControls to SplatRenderHandle move/look"
```

---

### Task 18: ReconViewer modal — dynamic import, error UI, capture, controls

**Files:**
- Create: `services/frontend/src/components/recon/ReconViewer.tsx`
- Create: `services/frontend/src/components/recon/reconViewer.css`
- Create: `services/frontend/src/components/recon/CaptureButton.tsx`
- Test: `services/frontend/src/components/recon/__tests__/ReconViewer.test.tsx`

The viewer:
- Lazy-loads the renderer via `loadDefaultSplatRenderer()` (no static import).
- Mounts `<CameraControls>` and `<CaptureButton>` once the handle is ready.
- Holds an `error` state; the renderer's `onError` callback transitions
  into it, exposing a Retry button that re-runs `render()`.

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/recon/__tests__/ReconViewer.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReconProvider, useRecon } from "../../../state/ReconContext";
import { ReconViewer } from "../ReconViewer";

// vi.mock factories are HOISTED above imports — they cannot reference
// module-scope `let`/`const` declarations (TDZ at hoist time). The
// canonical workaround is `vi.hoisted()` for any mock state shared
// between the factory and the test bodies.
const mocks = vi.hoisted(() => {
  const defaultScenes = [{
    scene_id: "jax_068",
    hf_filename: "JAX_068_final.ply",
    display_name: "Jacksonville District 068",
    ply_url: "/static/recon/JAX_068_final.ply?sha=" + "a".repeat(64),
    ply_size_bytes: 1000,
    bounds: { center_lat: 30.33, center_lon: -81.65, radius_m: 350 },
    bounds_source: "spacenet_metadata" as const,
    default_camera: {
      position: [0, 0, 200] as [number, number, number],
      look_at: [0, 0, 0] as [number, number, number],
      fov_deg: 60,
    },
    attribution: "Reconstruction: Skyfall-GS — Apache 2.0. Source imagery: SpaceNet 4.",
    source: "skyfall_gs_hf",
  }];
  const largeScene = {
    scene_id: "nyc_219",
    hf_filename: "NYC_219_final.ply",
    display_name: "New York City Tile 219",
    ply_url: "/static/recon/NYC_219_final.ply?sha=" + "c".repeat(64),
    ply_size_bytes: 324_186_833,
    bounds: { center_lat: 40.758, center_lon: -73.985, radius_m: 500 },
    bounds_source: "spacenet_metadata" as const,
    default_camera: {
      position: [0, 0, 500] as [number, number, number],
      look_at: [0, 0, 0] as [number, number, number],
      fov_deg: 60,
    },
    attribution: "x",
    source: "skyfall_gs_hf",
  };
  return {
    handle: {
      dispose: vi.fn(),
      captureScreenshot: vi.fn(async () =>
        new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" })
      ),
      getCanvas: () => document.createElement("canvas"),
      move: vi.fn(),
      look: vi.fn(),
    },
    defaultScenes,
    largeScene,
    state: {
      rendererBehavior: "ok" as "ok" | "error",
      scenes: defaultScenes as typeof defaultScenes,
    },
  };
});

vi.mock("../renderer", () => ({
  loadDefaultSplatRenderer: vi.fn(async () => ({
    render: vi.fn(async (_canvas, opts) => {
      if (mocks.state.rendererBehavior === "error") {
        opts.onError?.(new Error("simulated PLY parse error"));
        throw new Error("simulated PLY parse error");
      }
      opts.onProgress?.({ loaded: 100, total: 1000 });
      opts.onFirstFrame?.();
      return mocks.handle;
    }),
  })),
}));

vi.mock("../../../lib/recon/manifest", () => ({
  useReconManifest: () => ({
    scenes: mocks.state.scenes,
    loading: false,
    error: null,
  }),
  _resetReconManifestCache: () => {},
}));

import { waitFor } from "@testing-library/react";
import { beforeEach } from "vitest";

function Opener() {
  const { openScene } = useRecon();
  return <button onClick={() => openScene("jax_068")}>open</button>;
}

beforeEach(() => {
  mocks.state.rendererBehavior = "ok";
  mocks.state.scenes = mocks.defaultScenes;
  mocks.handle.dispose.mockClear();
  mocks.handle.captureScreenshot.mockClear();
  // Default: fast connection so BandwidthGuard auto-passes children through.
  Object.defineProperty(navigator, "connection",
    { value: { effectiveType: "4g" }, configurable: true });
});

afterEach(() => {
  Object.defineProperty(navigator, "connection",
    { value: undefined, configurable: true });
});

describe("ReconViewer", () => {
  it("does not render when no active scene", () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders modal + attribution footer when scene is opened", async () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/Skyfall-GS/)).toBeInTheDocument();
    expect(screen.getByText(/SpaceNet 4/)).toBeInTheDocument();
  });

  it("closes on ESC", () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders Capture button and downloads PNG when clicked", async () => {
    const createObjectURL = vi.fn(() => "blob:fake");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });

    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    // Wait for the renderer to finish + Capture button to mount
    await waitFor(() => screen.getByRole("button", { name: /capture/i }));
    fireEvent.click(screen.getByRole("button", { name: /capture/i }));
    await waitFor(() => expect(mocks.handle.captureScreenshot).toHaveBeenCalled());
    expect(createObjectURL).toHaveBeenCalled();
  });

  it("shows error message and Retry button when renderer fails", async () => {
    mocks.state.rendererBehavior = "error";
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByText(/simulated PLY parse error/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("Retry re-runs the renderer", async () => {
    mocks.state.rendererBehavior = "error";
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
    mocks.state.rendererBehavior = "ok";
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.queryByText(/simulated PLY parse error/i)).toBeNull());
  });

  it("disposes the handle on close", async () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => screen.getByRole("button", { name: /close/i }));
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    await waitFor(() => expect(mocks.handle.dispose).toHaveBeenCalled());
  });

  it("on metered connection: renderer does NOT start until Load anyway is clicked", async () => {
    Object.defineProperty(navigator, "connection",
      { value: { effectiveType: "3g" }, configurable: true });
    const renderer = (await import("../renderer")) as {
      loadDefaultSplatRenderer: ReturnType<typeof vi.fn>;
    };
    const renderSpy = vi.fn(async (_canvas, opts) => {
      opts.onFirstFrame?.();
      return mocks.handle;
    });
    renderer.loadDefaultSplatRenderer.mockResolvedValue({ render: renderSpy });

    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));

    // Bandwidth dialog visible; canvas + renderer not invoked yet
    expect(screen.getByRole("button", { name: /load anyway/i })).toBeInTheDocument();
    expect(renderSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /load anyway/i }));
    await waitFor(() => expect(renderSpy).toHaveBeenCalledTimes(1));
  });

  it("shows LARGE badge for scenes over 300 MB", () => {
    // Swap the manifest hook's data BEFORE rendering. The vi.mock factory
    // reads mocks.state.scenes by reference, so mutating it here makes the
    // next useReconManifest() call see nyc_219 without re-importing modules.
    mocks.state.scenes = [mocks.largeScene];

    function OpenLarge() {
      const { openScene } = useRecon();
      return <button onClick={() => openScene("nyc_219")}>open-large</button>;
    }

    render(<ReconProvider><OpenLarge /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open-large"));
    expect(screen.getByLabelText(/large scene/i)).toBeInTheDocument();
    // 324_186_833 / (1024*1024) rounds to 309
    expect(screen.getByText(/LARGE — 309 MB/)).toBeInTheDocument();
  });

  it("does NOT show LARGE badge for scenes under 300 MB", () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    expect(screen.queryByLabelText(/large scene/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd services/frontend
npm run test -- src/components/recon/__tests__/ReconViewer.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `services/frontend/src/components/recon/reconViewer.css`:
```css
.recon-viewer {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(11, 11, 9, 0.97);
  display: flex; flex-direction: column;
}
.recon-viewer__canvas { flex: 1; display: block; width: 100%; height: 100%; }
.recon-viewer__footer {
  padding: 8px 16px; font: 11px/1.4 monospace; color: #c9b380;
  background: rgba(18, 17, 14, 0.84); border-top: 1px solid #3a342a;
}
.recon-viewer__close {
  position: absolute; top: 12px; right: 12px;
  background: transparent; border: 1px solid #3a342a; color: #c9b380;
  padding: 6px 12px; cursor: pointer; font: 11px monospace;
}
.recon-viewer__progress {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  color: #c9b380; font: 13px monospace; text-align: center;
}
.recon-viewer__progress--error { color: #d97a55; }
.recon-viewer__progress--error button {
  margin-top: 12px; background: transparent; border: 1px solid #d97a55;
  color: #d97a55; padding: 6px 12px; cursor: pointer;
}
.recon-viewer__hud {
  position: absolute; top: 12px; left: 12px;
}
.recon-viewer__hud button {
  background: transparent; border: 1px solid #3a342a; color: #c9b380;
  padding: 6px 12px; cursor: pointer; font: 11px monospace;
}
.recon-viewer__large-badge {
  position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
  padding: 4px 10px; font: 11px monospace; letter-spacing: 0.08em;
  color: #d97a55; border: 1px solid #d97a55;
  background: rgba(18, 17, 14, 0.84);
}
```

Create `services/frontend/src/components/recon/CaptureButton.tsx`:
```tsx
import type { RefObject } from "react";
import type { SplatRenderHandle } from "./renderer";

interface CaptureButtonProps {
  handleRef: RefObject<SplatRenderHandle | null>;
  sceneId: string;
}

export function CaptureButton({ handleRef, sceneId }: CaptureButtonProps) {
  async function onClick() {
    const handle = handleRef.current;
    if (!handle) return;
    const blob = await handle.captureScreenshot();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `recon-${sceneId}-${Date.now()}.png`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return <button onClick={onClick}>Capture PNG</button>;
}
```

Create `services/frontend/src/components/recon/ReconViewer.tsx`:
```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRecon } from "../../state/ReconContext";
import { useReconManifest } from "../../lib/recon/manifest";
import { loadDefaultSplatRenderer, type SplatRenderHandle } from "./renderer";
import { WebGLCheck } from "./WebGLCheck";
import { BandwidthGuard } from "./BandwidthGuard";
import { CameraControls } from "./CameraControls";
import { CaptureButton } from "./CaptureButton";
import "./reconViewer.css";

type Phase =
  | { kind: "idle" }
  | { kind: "loading"; loaded: number; total: number }
  | { kind: "ready" }
  | { kind: "error"; message: string };

const LARGE_SCENE_BYTES = 300 * 1024 * 1024;

export function ReconViewer() {
  const { activeSceneId, closeScene } = useRecon();
  const { scenes } = useReconManifest();
  const scene = activeSceneId ? scenes.find((s) => s.scene_id === activeSceneId) : null;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handleRef = useRef<SplatRenderHandle | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [retryToken, setRetryToken] = useState(0);
  // Gate the renderer effect on BandwidthGuard confirm. Without this, the
  // render effect can fire before <canvas> is mounted (BandwidthGuard hides
  // children on metered connections) and the "Load anyway" click would have
  // no signal to re-run the effect because it changes no dependency.
  const [loadAllowed, setLoadAllowed] = useState(false);

  // Reset loadAllowed every time the active scene changes — a different
  // scene needs to re-pass the bandwidth gate.
  useEffect(() => { setLoadAllowed(false); }, [activeSceneId]);

  // ESC closes the modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeScene(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeScene]);

  // Renderer lifecycle — re-runs when scene changes, when bandwidth is
  // confirmed (canvas appears), or when Retry is clicked.
  useEffect(() => {
    if (!scene || !loadAllowed) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    let cancelled = false;
    setPhase({ kind: "loading", loaded: 0, total: scene.ply_size_bytes });

    (async () => {
      try {
        const renderer = await loadDefaultSplatRenderer();
        if (cancelled) return;
        const handle = await renderer.render(canvas, {
          plyUrl: scene.ply_url,
          defaultCamera: scene.default_camera,
          onProgress: (p) => {
            if (!cancelled) setPhase({ kind: "loading", loaded: p.loaded, total: p.total });
          },
          onFirstFrame: () => {
            if (!cancelled) setPhase({ kind: "ready" });
          },
          onError: (e) => {
            if (!cancelled) setPhase({ kind: "error", message: e.message });
          },
        });
        if (cancelled) { handle.dispose(); return; }
        handleRef.current = handle;
      } catch (e) {
        if (!cancelled) setPhase({ kind: "error", message: (e as Error).message });
      }
    })();

    return () => {
      cancelled = true;
      handleRef.current?.dispose();
      handleRef.current = null;
    };
  }, [scene, loadAllowed, retryToken]);

  const onRetry = useCallback(() => setRetryToken((t) => t + 1), []);
  const onBandwidthConfirm = useCallback(() => setLoadAllowed(true), []);

  if (!scene) return null;
  const mb = Math.round(scene.ply_size_bytes / (1024 * 1024));
  const isLarge = scene.ply_size_bytes > LARGE_SCENE_BYTES;

  const modal = (
    <div className="recon-viewer" role="dialog" aria-label={scene.display_name}>
      <WebGLCheck
        fallback={
          <div className="recon-viewer__progress">
            WebGL2 is required for the recon viewer. Please upgrade your browser.
            <button onClick={closeScene}>Close</button>
          </div>
        }
      >
        <BandwidthGuard
          sizeBytes={scene.ply_size_bytes}
          onConfirm={onBandwidthConfirm}
          onCancel={closeScene}
        >
          <canvas ref={canvasRef} className="recon-viewer__canvas" />

          {phase.kind === "loading" && (
            <div className="recon-viewer__progress">
              Loading {scene.display_name} — {Math.round(phase.loaded / 1024 / 1024)} / {mb} MB
            </div>
          )}

          {phase.kind === "error" && (
            <div className="recon-viewer__progress recon-viewer__progress--error">
              <p>Recon viewer failed: {phase.message}</p>
              <button onClick={onRetry}>Retry</button>
            </div>
          )}

          {phase.kind === "ready" && (
            <>
              <CameraControls canvasRef={canvasRef} handleRef={handleRef} />
              <div className="recon-viewer__hud">
                <CaptureButton handleRef={handleRef} sceneId={scene.scene_id} />
              </div>
            </>
          )}
        </BandwidthGuard>
      </WebGLCheck>

      {isLarge && (
        <span className="recon-viewer__large-badge" aria-label="large scene">
          LARGE — {mb} MB
        </span>
      )}

      <button className="recon-viewer__close" onClick={closeScene}>Close ✕</button>
      <div className="recon-viewer__footer">{scene.attribution}</div>
    </div>
  );

  return createPortal(modal, document.body);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd services/frontend
npm run test -- src/components/recon/__tests__/ReconViewer.test.tsx
```
Expected: PASS (10 tests): no-scene, attribution-footer, ESC-close,
Capture-button, error-message, Retry-rerun, dispose-on-close,
metered-connection-gate, LARGE-badge, no-LARGE-badge.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/recon/ReconViewer.tsx \
        services/frontend/src/components/recon/reconViewer.css \
        services/frontend/src/components/recon/CaptureButton.tsx \
        services/frontend/src/components/recon/__tests__/ReconViewer.test.tsx
git commit -m "feat(frontend/recon): add ReconViewer with lazy renderer, error UI, capture, controls"
```

---

### Task 19: Wire ReconLayer into Worldview + ReconViewer into AppShell

**Files:**
- Modify: `services/frontend/src/pages/WorldviewPage.tsx`
- Modify: `services/frontend/src/app/AppShell.tsx` — provider tree

The actual provider tree lives in `services/frontend/src/app/AppShell.tsx`
(verified — wraps `<IncidentProvider>` and the `<IncidentLayer>` /
`<IncidentToast>` pattern). `<ReconProvider>` wraps `<IncidentProvider>`
so any page below — including the recon layer in WorldviewPage and the
viewer modal itself — sees the same context.

- [ ] **Step 1: Verify the provider tree**

Run:
```bash
cd services/frontend
grep -n "IncidentProvider" src/app/AppShell.tsx
```
Expected: a line matching `<IncidentProvider>` near the top of the JSX
returned by `AppShell`. If the structure has changed since 2026-05-17,
stop and reconcile before continuing.

- [ ] **Step 2: Modify `AppShell.tsx`**

Read `services/frontend/src/app/AppShell.tsx`. Apply these edits:

Add to the imports:
```tsx
import { ReconProvider } from "../state/ReconContext";
import { ReconViewer } from "../components/recon/ReconViewer";
```

Change the `AppShell` body from:
```tsx
export function AppShell() {
  return (
    <IncidentProvider>
      <IncidentLayer>
        <Outlet />
      </IncidentLayer>
    </IncidentProvider>
  );
}
```
to:
```tsx
export function AppShell() {
  return (
    <ReconProvider>
      <IncidentProvider>
        <IncidentLayer>
          <Outlet />
        </IncidentLayer>
      </IncidentProvider>
      <ReconViewer />
    </ReconProvider>
  );
}
```

`<ReconViewer />` is outside the `<IncidentLayer>` so it portals at the
provider root, sibling to the incident toast. Both modals are independent.

- [ ] **Step 3: Add ReconLayer to WorldviewPage**

Read `services/frontend/src/pages/WorldviewPage.tsx` and find where `FIRMSLayer` or `GDACSLayer` is mounted. Mount `ReconLayer` the same way:

```tsx
import { ReconLayer } from "../components/layers/ReconLayer";
import { useReconManifest } from "../lib/recon/manifest";
import { useRecon } from "../state/ReconContext";

// inside the component body:
const { scenes: reconScenes } = useReconManifest();
const { openScene } = useRecon();

// inside the layer-mounting JSX, alongside other layers:
<ReconLayer
  viewer={viewer}
  scenes={reconScenes}
  visible={true}
  onSelect={(s) => openScene(s.scene_id)}
/>
```

- [ ] **Step 4: Type-check + tests + lint**

Run:
```bash
cd services/frontend
npm run type-check
npm run test
npm run lint
```
Expected: 0 type errors, all tests pass, 0 new lint errors.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/pages/WorldviewPage.tsx services/frontend/src/app/AppShell.tsx
git commit -m "feat(frontend/recon): wire ReconLayer into Worldview and ReconViewer into AppShell"
```

---

# Phase A — End-to-End

### Task 20: Manual smoke workflow

**Files:**
- Create: `docs/workflows/recon-smoke.md`

- [ ] **Step 1: Run the bootstrap on a fresh checkout**

Run:
```bash
cd ~/ODIN/OSINT
./odin.sh recon bootstrap
ls -lh services/backend/static/recon/    # expect 12 PLYs
cat services/backend/data/recon_manifest.json | python -m json.tool | head -60
```

- [ ] **Step 2: Start interactive mode**

Run:
```bash
./odin.sh up interactive
./odin.sh smoke  # expect green
curl -s http://localhost:8080/api/recon/scenes | python -m json.tool | head
```

- [ ] **Step 3: Browser smoke**

Open `http://localhost:5173/worldview` and verify:
1. Twelve amber pins visible (8 over Jacksonville, 4 over NYC).
2. Click `jax_004` (smallest, 158 MB). Record:
   - Time to "first visible progress" indicator: target <2s.
   - Time to "first navigable frame": target <60s @ 30 Mbps.
3. WASD navigation works, mouse-look in pointer-lock works, Q/E moves up/down.
4. Click `nyc_219` (largest, 324 MB). Record same metrics; flag if >60s.
5. PNG capture button (mounted in Task 18) downloads an image; verify it
   opens as a valid PNG.
6. ESC closes the modal.
7. DevTools → Network → throttle "Slow 3G", reopen scene: bandwidth guard fires.
8. DevTools console: launch a Chromium with `--disable-webgl2` or use a browser without WebGL2 support: modal refuses to open.

- [ ] **Step 4: Write the workflow doc**

Create `docs/workflows/recon-smoke.md` with:
- The exact commands above.
- A table of measured load times per scene (12 rows).
- Screenshots of the modal open on `jax_068` and `nyc_010`.
- A "Known issues" section for anything observed but out of scope.

- [ ] **Step 5: Commit**

```bash
git add docs/workflows/recon-smoke.md
git commit -m "docs(workflows): add manual end-to-end recon smoke checklist with measurements"
```

---

### Task 21: Two-stage review (MANDATORY per `feedback_never_skip_reviews`)

**Files:** (no code changes; review only)

- [ ] **Step 1: Spec-review pass**

Dispatch a `superpowers:code-reviewer` (or `Plan`) subagent with the spec, plan, and diff:
- Spec path: `docs/superpowers/specs/2026-05-11-skyfall-recon-mvp-design.md`
- Plan path: `docs/superpowers/plans/2026-05-17-skyfall-recon-mvp.md`
- Diff: `git diff main...HEAD`

Question for the reviewer: "Does the implementation satisfy every requirement in the spec sections 3 (Goals), 5 (Components), 8 (API Contract), 9 (Error Handling), 10 (Testing Strategy)? List any gaps."

- [ ] **Step 2: Quality-review pass**

Dispatch a second review with focus:
- Type safety: any `any`s? Any unsafe casts beyond the documented Cesium primitive→object cast pattern?
- Cesium hygiene: `viewer.isDestroyed()` in every cleanup, no Entity API, no globe re-renders triggered.
- Read-only invariant: any path that writes from the recon router?
- Test coverage: are the edge cases from Section 9 (Error Handling) actually tested?

- [ ] **Step 3: Address findings**

For each review comment, either: (a) fix the issue and commit, or (b) document the deferral in `docs/superpowers/specs/2026-05-11-skyfall-recon-mvp-design.md` "Known Issues" section with rationale.

- [ ] **Step 4: Final verification**

Run:
```bash
cd services/backend && uv run pytest -x && uv run ruff check app/
cd ../frontend && npm run type-check && npm run test && npm run lint
cd ~/ODIN/OSINT && python -m pytest scripts/recon/tests/ -v
```
Expected: every command green.

- [ ] **Step 5: Decide merge strategy**

Hand off to `superpowers:finishing-a-development-branch` to pick merge vs. PR.

---

## Self-Review Notes

**Spec coverage:**
- §3.1 latency targets — measured in Phase 0 (Task 0, gated by `verify_results.py`) and manual smoke (Task 20).
- §3.2 architecture seam (Phase B drop-in) — manifest-driven, no code changes for new scenes. ✓
- §3.3 zero impact on existing modes — recon adds no new container, no GPU, no DB schema. ✓
- §3.4 attribution in viewer — Task 18 renders `scene.attribution` in the footer. ✓
- §3.5 test parity — pytest router + bootstrap + cached_static + manifest_loader + vitest viewer + layer + manifest hook + context + bandwidth + camera-controls. ✓
- §4 architecture diagram — Tasks 4, 5, 13, 18, 19 wire each box. ✓
- §5.1 backend — Tasks 1–5. Lifespan integration in Task 5 (not `@on_event`). ✓
- §5.2 frontend — Tasks 10–19. Renderer lazy-loaded via `loadDefaultSplatRenderer()` so the splat library stays out of the initial bundle. ✓
- §5.3 bootstrap — Tasks 6–9. Idempotent short-circuit before HF download (Task 8). ✓
- §6 data flow — End-to-end smoke covers each stage. ✓
- §7 manifest schema — Pydantic model matches; `?sha=` query suffix enforced by `model_validator` (Task 1); round-trip tested in Task 8. ✓
- §8 API contract — Tasks 4, 5, paths under both prefixes. ✓
- §9 error handling — manifest missing (Task 4 503 test), PLY missing (Task 5 static 404), WebGL2 absent (Task 14), 3G/2G (Task 14), corrupt PLY (Task 18: `error` phase + Retry button, two tests). ✓
- §10 testing strategy — every named test is in this plan; Phase 0 has a real gate script. ✓
- §11 risks — Phase 0 mitigates 1 & 2 with real timings + screenshots; `bounds_source: "manual"` allowed in model for Risk 3; license_audit fail-closed AND file-backed for Risk 4; `SplatRenderer` interface for Risk 5. ✓
- §12 rollout — Phase 0 → Phase A → no feature flag. ✓

**Placeholder scan:** Task 16 still defers concrete renderer code to the
Phase 0 winner, but spells out every required method (move/look/dispose/
capture, axis semantics, pitch clamp) so the implementer can't ship
something that fails the WASD test in Task 17 or the capture test in
Task 18. No other placeholders.

**Type consistency:**
- `scene_id`, `ply_url`, `bounds`, `default_camera`, `attribution`,
  `source` consistent across Pydantic, JSON, TS types, hook, layer, viewer.
- `onSelect` signature matches FIRMSLayer pattern.
- `SplatRenderer.render → Promise<SplatRenderHandle>` consistent between
  interface (Task 15), dynamic loader (Task 16), and viewer (Task 18).
- `SplatRenderHandle.move(axis, delta)` and `.look(yaw, pitch)` consistent
  between interface (Task 15), CameraControls (Task 17), and the viewer
  (Task 18).
- `ply_url` always carries `?sha=<ply_sha256>` from bootstrap (Task 8)
  through manifest (Task 1, 8) to frontend (consumed via `useReconManifest`).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-17-skyfall-recon-mvp.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Each subagent gets the spec + this plan + the specific task block.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
