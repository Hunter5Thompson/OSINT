# Skyfall Recon MVP — Design Spec

**Date:** 2026-05-11
**Status:** Brainstormed, awaiting TASK registration before plan execution
**Scope:** Phase A — globe-driven 3D Gaussian Splatting reconnaissance modal using
the five pre-built Jacksonville (JAX) fused PLY assets published by the Skyfall-GS
authors. No own training in this phase.
**Out of scope (future phases):** Custom training pipeline for SpaceNet cities
(Phase B), Spark-based industrial training service (Phase C), commercial
satellite imagery procurement (Up42 / Maxar), live on-demand AOI training,
4D / time-lapse scenes.

---

## 1. Motivation

ODIN/WorldView's globe today gives operative situational awareness — pins,
hotspots, live data layers — but every drill-in is text-and-graph. Analysts
cannot see the *ground reality* of a location while staying inside the tool.
Existing alternatives (Google Earth tab-switch, third-party 3D viewers, manual
screenshots from news photos) break flow and produce no reusable artifact.

Skyfall-GS (Lee et al., 2025) demonstrates that satellite imagery alone — without
LiDAR, ground capture, or NeRF rigs — is enough to synthesize photorealistic,
free-flyable 3D urban scenes via 3D Gaussian Splatting plus an iterative
diffusion-based texture refinement (FlowEdit). The authors publish ready-to-use
fused PLY models for five Jacksonville districts on Hugging Face under
Apache 2.0.

That gives WorldView a low-risk path to add a "ground reconnaissance" capability
to the existing globe with no own training required: download five PLYs,
expose them through the backend, render them in a modal opened from globe
hotspots. If the user-experience proves valuable, Phase B adds custom training
for additional SpaceNet cities; if not, the sunk cost is two days of work.

---

## 2. Decision

Add a new "Recon Viewer" capability that:

1. Pre-bundles the five JAX fused-PLY assets through a one-time bootstrap script.
2. Serves them as static files via the existing FastAPI backend with HTTP Range
   support.
3. Exposes a small JSON metadata API listing available scenes, their geographic
   bounds, and default cameras.
4. Renders a globe overlay layer marking which hotspots have a recon scene
   available.
5. Opens a full-screen React modal on click, lazy-loads a Three.js / WebGL2
   Gaussian-Splatting renderer, streams the PLY, and offers WASD + mouse-look
   navigation plus a PNG screenshot capture.

No database schema changes. No new Docker services. No multi-tenancy. No
authentication on the recon endpoints (single-user platform, internal LAN).

---

## 3. Goals

1. Five JAX scenes browsable in under thirty seconds from globe-pin click to
   first frame on a desktop with a residential broadband connection.
2. Architecture seam clean enough that Phase B (own training output) drops in
   by adding entries to the manifest and PLYs to the static directory — no
   frontend or backend code changes required.
3. Zero impact on existing WorldView modes (ingestion / interactive / NLM /
   Voxtral). Recon adds no GPU load, no new model, no extra container.
4. Attribution and license terms for SpaceNet imagery and Skyfall-GS code shown
   inside the viewer modal.
5. Test coverage parity with rest of backend: pytest router tests, vitest
   component tests, manual end-to-end smoke documented in workflows.

## 3a. Non-Goals

- Live training of new scenes from arbitrary coordinates.
- Procurement of commercial satellite imagery.
- Mobile-first experience. Desktop with WebGL2 is the target. Mobile gets a
  bandwidth warning and degrades gracefully.
- Editing or annotating the splat scenes inside WorldView.
- Multi-user concurrency, auth, or per-user state.

---

## 4. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│ Frontend  (React 19 + Vite 6 + Cesium 1.132, Port 5173)        │
│                                                                │
│  ┌──────────────────┐                ┌──────────────────────┐  │
│  │ Globe (existing) │ click          │ ReconViewer (NEW)    │  │
│  │  + Recon         │ recon hotspot  │  full-screen modal   │  │
│  │  Hotspot Layer   │ ──────────────▶│  Three.js + gsplat   │  │
│  │  (NEW)           │                │  WASD + capture      │  │
│  └──────────────────┘                └──────────┬───────────┘  │
│         ▲                                       │              │
│         │ manifest                              │ PLY stream   │
└─────────┼───────────────────────────────────────┼──────────────┘
          │                                       │
          │ GET /api/v1/recon/scenes              │ GET /static/recon/*.ply
          │ GET /api/v1/recon/scenes/{id}         │ (HTTP Range)
          ▼                                       ▼
┌────────────────────────────────────────────────────────────────┐
│ Backend  (FastAPI, Port 8080)                                  │
│                                                                │
│  app/routers/recon.py            (NEW, READ-ONLY)              │
│  app/models/recon.py             (NEW, Pydantic schemas)       │
│  data/recon_manifest.json        (NEW, source of truth)        │
│  static/recon/*.ply              (Bootstrap-populated)         │
│  StaticFiles mount under /static/recon (Range requests)        │
└────────────────────────────────────────────────────────────────┘
                              ▲
                              │ writes
                              │
┌────────────────────────────────────────────────────────────────┐
│ One-Time Bootstrap                                             │
│  scripts/recon/bootstrap_jax_plys.py        (NEW)              │
│   - hf hub download jayinnn/Skyfall-GS-ply  (cached)           │
│   - copy/symlink into services/backend/static/recon/           │
│   - emit recon_manifest.json from cam-JSONs + hardcoded geo    │
│   - SHA256 verify each PLY                                     │
│  Runnable via: ./odin.sh recon bootstrap  (NEW thin wrapper)   │
└────────────────────────────────────────────────────────────────┘
```

Three new modules in three existing services. Bootstrap runs once per fresh
checkout (or whenever HF asset hashes change).

---

## 5. Components

### 5.1 Backend

**Path:** `services/backend/app/routers/recon.py`

Two endpoints, both READ-ONLY:

- `GET /api/v1/recon/scenes` — returns the full manifest as JSON.
- `GET /api/v1/recon/scenes/{scene_id}` — returns one scene's metadata, or 404.

The manifest is loaded once at app startup (`recon_manifest.json`) into an
in-memory dict keyed by `scene_id`. No per-request file I/O on the metadata
path. PLY bytes are served directly by FastAPI's `StaticFiles` mount under
`/static/recon/`, with Range support enabled (FastAPI / Starlette gives this for
free for `StaticFiles`).

**Pydantic models:** `services/backend/app/models/recon.py`

```python
class GeoBounds(BaseModel):
    center_lat: float
    center_lon: float
    radius_m: float        # rough AOI radius for globe-pin placement

class DefaultCamera(BaseModel):
    position: tuple[float, float, float]   # local Skyfall-GS coords
    look_at: tuple[float, float, float]
    fov_deg: float

class ReconScene(BaseModel):
    scene_id: str          # e.g. "jax_068"
    display_name: str      # e.g. "Jacksonville District 068"
    ply_url: str           # e.g. "/static/recon/jax_068_fused.ply"
    ply_size_bytes: int
    ply_sha256: str
    bounds: GeoBounds
    default_camera: DefaultCamera
    attribution: str       # "© DigitalGlobe via SpaceNet, Skyfall-GS, Lee et al. 2025"
    source: Literal["skyfall_gs_jax_hf"] | str  # extensible for Phase B
```

**No write endpoints. No DB writes. No LLM calls. Hard READ-ONLY surface.**

### 5.2 Frontend

**Path:** `services/frontend/src/components/recon/`

- `ReconViewer.tsx` — full-screen modal, mounted via portal at `<App>` root,
  controlled through a `ReconProvider` React Context following the existing
  `state/IncidentProvider.tsx` and `components/globe/spotlight/SpotlightContext.tsx`
  patterns. Lazy-imports the Gaussian-Splat renderer module via dynamic
  `import()` so the initial bundle is unaffected. Shows attribution footer,
  capture button, ESC closes.
- `CameraControls.tsx` — WASD + mouse-look + scroll-zoom + Q/E for vertical
  movement. Pointer-locked when active.
- `BandwidthGuard.tsx` — pre-load gate; if `navigator.connection?.effectiveType`
  is `2g` or `3g`, shows confirm dialog with size in MB. Otherwise transparent.
- `WebGLCheck.tsx` — verifies `WebGL2RenderingContext`; if missing, modal
  refuses to open and shows an explanation.

**Path:** `services/frontend/src/lib/recon/`

- `manifest.ts` — typed fetch + in-memory cache for `/api/v1/recon/scenes`,
  exposes `useReconManifest()` React hook (TanStack Query if already in repo,
  otherwise plain hook with SWR-style cache).
- `types.ts` — TypeScript mirrors of backend Pydantic models.

**Path:** `services/frontend/src/components/globe/`

- `ReconHotspotLayer.tsx` — new Cesium imperative layer (per existing
  CesiumJS pattern: `BillboardCollection`, not Entity API). For each manifest
  entry, place a billboard at `bounds.center_lat / center_lon` with a "Recon"
  icon. On click, dispatch to `reconContext.openScene(scene_id)`.

**Renderer choice:**

- **Primary candidate:** [Spark](https://github.com/sparkjs/spark) — Three.js
  3D Gaussian Splatting renderer with documented Mip-Splatting compatibility.
  Active development, MIT license, npm-available.
- **Fallback:** [@mkkellogg/gaussian-splats-3d](https://github.com/mkkellogg/GaussianSplats3D)
  — battle-tested, supports anti-aliasing modes that approximate Mip-Splatting.
- **Decision criterion:** see Risk 1, Section 11. A pre-implementation smoke
  test renders one JAX PLY in both candidates side-by-side; the renderer that
  visually matches the Skyfall-GS reference renders is chosen and locked in.

### 5.3 Bootstrap Script

**Path:** `scripts/recon/bootstrap_jax_plys.py`

Idempotent Python script. Steps:

1. Verify `hf` CLI (HuggingFace) is on PATH.
2. `hf download jayinnn/Skyfall-GS-ply` into `~/.cache/huggingface/...` (default).
3. For each expected JAX PLY, copy or symlink into
   `services/backend/static/recon/<scene_id>_fused.ply`.
4. Compute SHA256 per PLY and write to manifest.
5. For each scene, read the corresponding JAX cam JSON (from the dataset on HF
   or hardcoded local copy) to derive a sensible `default_camera`.
6. Write `services/backend/data/recon_manifest.json`.

Geographic bounds (`center_lat`, `center_lon`, `radius_m`) for each JAX scene
are hardcoded in a small lookup table inside the script, derived from the
SpaceNet metadata for Jacksonville. They are not a runtime concern — they live
in the manifest after bootstrap.

**Wrapper:** `odin.sh recon bootstrap` adds a thin shell wrapper following the
existing `odin.sh` subcommand convention.

---

## 6. Data Flow

```
[install]   developer runs: ./odin.sh recon bootstrap
            -> 5 PLYs land in services/backend/static/recon/
            -> recon_manifest.json written

[startup]   FastAPI loads manifest into memory
            Frontend GET /api/v1/recon/scenes -> client-side cache

[browse]    Globe renders ReconHotspotLayer using manifest bounds
            5 visible billboard pins over Jacksonville

[click]     User clicks pin
            -> reconContext.openScene("jax_068")
            -> ReconViewer modal mounts via portal
            -> WebGLCheck passes
            -> BandwidthGuard passes (or user confirms)

[load]      Modal lazy-imports Spark / gaussian-splats-3d module
            fetch /static/recon/jax_068_fused.ply  (HTTP Range, streaming)
            renderer initializes scene, applies default_camera

[view]      Pointer-lock on canvas; WASD navigates, mouse looks,
            ESC unlocks pointer; close-X unmounts modal

[capture]   "Capture" button reads canvas to PNG, triggers download

[close]     Modal unmounts -> renderer.dispose() frees VRAM
```

All client state for an open scene lives inside the modal. Closing the modal
fully releases GPU memory. No global VRAM accounting needed because Recon does
not coexist with anything heavy on the client GPU (the Cesium globe behind it
is rendered to a separate WebGL context and remains live but idle).

---

## 7. Manifest Schema

`services/backend/data/recon_manifest.json` is the single source of truth.

```json
{
  "version": 1,
  "generated_at": "2026-05-11T00:00:00Z",
  "source_commit": "<git sha of bootstrap script when run>",
  "scenes": [
    {
      "scene_id": "jax_068",
      "display_name": "Jacksonville District 068",
      "ply_url": "/static/recon/jax_068_fused.ply",
      "ply_size_bytes": 268435456,
      "ply_sha256": "abc123...",
      "bounds": {
        "center_lat": 30.3322,
        "center_lon": -81.6557,
        "radius_m": 350
      },
      "default_camera": {
        "position": [0, 0, 200],
        "look_at": [0, 0, 0],
        "fov_deg": 60
      },
      "attribution": "Imagery © DigitalGlobe via SpaceNet (CC-BY-SA-4.0). Reconstruction: Skyfall-GS, Lee et al. 2025 (Apache 2.0).",
      "source": "skyfall_gs_jax_hf"
    }
  ]
}
```

Phase B adds entries with `"source": "spacenet_local_train"` and a different
`ply_url` pointing at locally trained PLYs — no schema change required.

---

## 8. API Contract

### `GET /api/v1/recon/scenes`

Returns the entire manifest minus the `source_commit` and internal fields.

```json
{
  "scenes": [
    {
      "scene_id": "jax_068",
      "display_name": "Jacksonville District 068",
      "ply_url": "/static/recon/jax_068_fused.ply",
      "ply_size_bytes": 268435456,
      "bounds": {"center_lat": 30.3322, "center_lon": -81.6557, "radius_m": 350},
      "default_camera": {"position": [0,0,200], "look_at": [0,0,0], "fov_deg": 60},
      "attribution": "Imagery © DigitalGlobe via SpaceNet ...",
      "source": "skyfall_gs_jax_hf"
    }
  ]
}
```

### `GET /api/v1/recon/scenes/{scene_id}`

Returns a single `ReconScene` or HTTP 404 with `{"detail": "scene not found"}`.

### `GET /static/recon/{scene_id}_fused.ply`

Standard FastAPI static-file response with Range-request support. Cached
indefinitely client-side (immutable filename per content). `Cache-Control:
public, max-age=31536000, immutable` set via static-files middleware.

### Error responses

All recon endpoints return JSON `{"detail": "<reason>"}` on error, status codes
follow FastAPI defaults.

---

## 9. Error Handling

| Condition                              | Behavior                                                                      |
|----------------------------------------|-------------------------------------------------------------------------------|
| Manifest missing at startup            | Log error, mount router but every request returns 503 with explanation.       |
| PLY file missing (manifest references) | `/api/v1/recon/scenes/{id}` succeeds, static file 404, frontend shows retry.  |
| WebGL2 unavailable                     | Modal refuses to open, shows browser-upgrade message.                          |
| Slow connection (3G/2G)                | Pre-load confirm dialog with PLY size in MB.                                   |
| PLY bytes corrupt / parse error        | Renderer error -> modal shows message, log full error to console, retry btn. |
| Bootstrap script run twice             | Idempotent: skips downloads if SHA matches manifest.                          |
| HF download failure                    | Bootstrap exits non-zero with actionable error (rate limit, auth, network).  |

No automatic retries inside the running app — bootstrap is a developer action,
runtime errors surface immediately for diagnosis.

---

## 10. Testing Strategy

### Backend (pytest, services/backend/tests/)

- `test_recon_router.py`
  - `test_list_scenes_returns_manifest_shape`
  - `test_get_scene_by_id`
  - `test_get_scene_404_for_unknown_id`
  - `test_router_503_when_manifest_missing`
- `test_recon_static.py`
  - `test_ply_range_request_returns_206_with_correct_bytes`
  - `test_ply_full_request_returns_200`
- Fixtures use a tiny synthetic PLY (~1 KB) and a 2-scene manifest stub.

### Frontend (vitest, services/frontend/src/)

- `recon/ReconViewer.test.tsx`
  - renders modal when store flag set
  - calls `closeScene` on ESC
  - shows attribution footer
- `recon/manifest.test.ts`
  - hook returns scenes after fetch
  - hook surfaces error on 503
- `globe/ReconHotspotLayer.test.tsx`
  - creates billboard per manifest entry
  - dispatches `openScene` on click
- Renderer module is mocked in component tests; integration tested manually.

### End-to-End (manual, documented in `docs/workflows/recon-smoke.md`)

1. Fresh checkout, run `./odin.sh recon bootstrap`.
2. `./odin.sh up interactive`.
3. Browser to `http://localhost:5173`.
4. Verify five Recon pins visible over Jacksonville.
5. Click each pin, verify PLY loads in under thirty seconds, WASD navigates,
   capture downloads PNG, ESC closes.
6. Run on a Chromium build with WebGL2 disabled, verify graceful refusal.

### Pre-Implementation Smoke (Risk-1 mitigation, see Section 11)

Before any production code is written, a one-page HTML harness loads one JAX
PLY in both Spark and `@mkkellogg/gaussian-splats-3d`, side-by-side with a
reference render from Skyfall-GS's own Mip-Splatting demo. Renderer that
matches visually wins.

---

## 11. Risks and Mitigations

### Risk 1 — Mip-Splatting PLY format mismatch

Skyfall-GS PLYs encode Mip-Splatting kernel parameters that not every Web
3DGS renderer interprets. A naive renderer may produce noticeably blurrier or
aliased output. **Mitigation:** the pre-implementation smoke test (Section 10)
runs before any backend or frontend code is written. Renderer choice is locked
in based on visual parity with the official Skyfall-GS demo.

### Risk 2 — PLY bandwidth on first load

Fused PLYs are 100 to 500 MB each. On residential broadband (~30 Mbps) that is
~30–130 seconds to first frame. **Mitigation:** HTTP Range support enables
streaming-style progressive load in capable renderers; bandwidth guard warns
on metered connections; `Cache-Control: immutable` makes second views instant.
Acceptable for an analyst tool; a public demo would need WebTransport / mesh
LoD which is out of scope.

### Risk 3 — Globe coordinate mapping is manual

Skyfall-GS PLYs use a local right-handed metric coordinate frame, not WGS84.
Pin placement depends on the manually populated `bounds` field in the manifest.
For five known Jacksonville scenes this is a one-time table; for arbitrary
Phase B AOIs an automated pipeline will be needed (SatelliteSfM emits WGS84
geo-anchors that can be reused). **Mitigation:** Phase A accepts the manual
table as documented technical debt; Phase B's SatelliteSfM run derives bounds
automatically.

### Risk 4 — License / attribution compliance

SpaceNet imagery is CC-BY-SA-4.0; Skyfall-GS is Apache 2.0. Both require
attribution. **Mitigation:** every scene's `attribution` field is rendered in
the modal footer; the bootstrap script writes a `LICENSES.md` next to the PLY
files; project README links to source datasets and paper.

### Risk 5 — Renderer drops support / library churn

Web 3DGS renderers are young (Spark, gsplat.js, others). A library could be
abandoned. **Mitigation:** the renderer is encapsulated behind a thin
interface (`renderScene(canvas, plyUrl, defaultCamera) -> Disposer`). Swapping
it requires touching one module.

---

## 12. Rollout

Phase A (this spec) ships in a single feature branch
(`feature/skyfall-recon-mvp`) and merges to `main` once smoke tests pass and
the bootstrap script is documented in the workflows directory.

No feature flag — recon is additive, hidden behind globe pins that only appear
when the manifest contains scenes. If bootstrap is not run, no pins appear and
the rest of WorldView is unaffected.

### Future Phases (out of scope here, listed for context only)

- **Phase B — Custom Training Pipeline:** SatelliteSfM + Skyfall-GS Stage 1+2
  on additional SpaceNet cities (Khartoum, Atlanta, Shanghai, Paris, Rio etc.),
  trained on RTX 5090 or DGX Spark. Outputs land in `static/recon/` with new
  manifest entries; no frontend / backend code changes needed.
- **Phase C — Industrial Training Service:** Spark integrated into `odin.sh`
  as `odin recon train <city>`, support for arbitrary AOIs from commercial
  imagery (Up42 / Maxar), per-scene training metadata and quality metrics.
- **Phase D — Time-lapse / "before-after" pairs:** two scenes for one location
  at different timestamps, cross-faded in the viewer. (Not 4D — distinct scenes
  with a comparison UI on top.)

Each future phase gets its own brainstorm and spec.

---

## 13. References

- **Paper:** Lee et al., *Skyfall-GS: Synthesizing Immersive 3D Urban Scenes
  from Satellite Imagery*, arXiv:2510.15869, 2025.
- **Code:** https://github.com/jayin92/skyfall-gs (Apache 2.0)
- **Pre-built PLYs:** https://huggingface.co/jayinnn/Skyfall-GS-ply
- **Datasets:** https://huggingface.co/datasets/jayinnn/Skyfall-GS-datasets
- **SpaceNet (data origin):** https://spacenet.ai/datasets/ (CC-BY-SA-4.0)
- **Mip-Splatting:** https://github.com/autonomousvision/mip-splatting
- **Spark renderer (candidate):** https://github.com/sparkjs/spark
- **gaussian-splats-3d (fallback candidate):** https://github.com/mkkellogg/GaussianSplats3D
- **WorldView CLAUDE.md:** `~/ODIN/OSINT/CLAUDE.md`
- **Existing globe layer pattern:** `services/frontend/src/components/globe/`
