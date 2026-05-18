# Skyfall Recon MVP — Design Spec

**Date:** 2026-05-11
**Revision:** v2 (2026-05-11) — addresses internal review (asset scope, API
convention, cache implementation, layer placement, license provenance, paper
version)
**Status:** Phase 0 (renderer + load-time smoke) gates Phase A implementation
**Scope:** Phase A — globe-driven 3D Gaussian Splatting reconnaissance modal
using the twelve pre-built scenes (8 Jacksonville + 4 New York City) published
by the Skyfall-GS authors on Hugging Face. No own training in this phase.
**Out of scope (future phases):** Custom training pipeline for additional
SpaceNet cities (Phase B), Spark-based industrial training service (Phase C),
commercial satellite imagery procurement (Up42 / Maxar), live on-demand AOI
training, 4D / time-lapse scenes.

---

## 1. Motivation

ODIN/WorldView's globe today gives operative situational awareness — pins,
hotspots, live data layers — but every drill-in is text-and-graph. Analysts
cannot see the *ground reality* of a location while staying inside the tool.
Existing alternatives (Google Earth tab-switch, third-party 3D viewers, manual
screenshots from news photos) break flow and produce no reusable artifact.

Skyfall-GS (Lee et al., 2025; arXiv:2510.15869v3, revised March 2026)
demonstrates that satellite imagery alone — without LiDAR, ground capture, or
NeRF rigs — is enough to synthesize photorealistic, free-flyable 3D urban
scenes via 3D Gaussian Splatting plus an iterative diffusion-based texture
refinement (FlowEdit). The authors publish twelve ready-to-use PLY models on
Hugging Face — eight for Jacksonville districts, four for New York City —
under the Apache 2.0 license for the model artifacts (source-imagery licenses
audited at bootstrap, see Section 5.3 and Risk 4).

That gives WorldView a low-risk path to add a "ground reconnaissance"
capability to the existing globe with no own training required: download the
twelve PLYs, expose them through the backend, render them in a modal opened
from globe hotspots. If the user-experience proves valuable, Phase B adds
custom training for additional SpaceNet cities; if not, the sunk cost is two
days of work.

---

## 2. Decision

Add a new "Recon Viewer" capability that:

1. Pre-bundles the twelve PLY assets (8 JAX `JAX_NNN_final.ply` + 4 NYC
   `NYC_NNN_final.ply`) through a one-time bootstrap script.
2. Serves them as static files via the existing FastAPI backend with HTTP Range
   request support.
3. Exposes a small JSON metadata API listing available scenes, their geographic
   bounds, and default cameras, registered under both `/api/recon/...` and
   `/api/v1/recon/...` per the existing `app/main.py` routing convention.
4. Renders a globe overlay layer (sibling to FIRMSLayer / GDACSLayer in
   `components/layers/`) marking which hotspots have a recon scene available.
5. Opens a full-screen React modal on click, lazy-loads a Three.js / WebGL2
   Gaussian-Splatting renderer, streams the PLY, and offers WASD + mouse-look
   navigation plus a PNG screenshot capture.

No database schema changes. No new Docker services. No multi-tenancy. No
authentication on the recon endpoints (single-user platform, internal LAN).

---

## 3. Goals

1. All twelve scenes openable from a globe-pin click. Two distinct latency
   targets (validated in the Phase 0 smoke test, see Section 12):
   - **First visible progress** (loading indicator with byte-progress, no
     blank screen): under two seconds.
   - **First navigable frame** (camera responds to input, scene visually
     coherent): under sixty seconds on a 30 Mbps connection for a 250 MB
     PLY. Scenes above 300 MB explicitly tagged "large" in the UI.
2. Architecture seam clean enough that Phase B (own training output) drops in
   by adding entries to the manifest and PLYs to the static directory — no
   frontend or backend code changes required.
3. Zero impact on existing WorldView modes (ingestion / interactive / NLM /
   Voxtral). Recon adds no GPU load, no new model, no extra container.
4. Per-scene attribution and license terms (Skyfall-GS Apache 2.0 +
   per-dataset source-imagery license, audited at bootstrap) shown inside the
   viewer modal.
5. Test coverage parity with rest of backend: pytest router tests, vitest
   component tests, bootstrap-script tests (filename mapping, manifest schema,
   idempotency, missing-CLI handling), manual end-to-end smoke documented in
   workflows.

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
│  │  + ReconLayer    │ recon hotspot  │  full-screen modal   │  │
│  │  (NEW, lives in  │ ──onSelect────▶│  Three.js + gsplat   │  │
│  │  components/     │                │  WASD + capture      │  │
│  │  layers/)        │                │                      │  │
│  └──────────────────┘                └──────────┬───────────┘  │
│         ▲                                       │              │
│         │ manifest                              │ PLY stream   │
└─────────┼───────────────────────────────────────┼──────────────┘
          │                                       │
          │ GET /api/recon/scenes  (primary)      │ GET /static/recon/*.ply
          │ GET /api/v1/recon/scenes (alias)      │ (HTTP Range, immutable)
          │ GET /api/recon/scenes/{id}            │
          ▼                                       ▼
┌────────────────────────────────────────────────────────────────┐
│ Backend  (FastAPI, Port 8080)                                  │
│                                                                │
│  app/routers/recon.py            (NEW, READ-ONLY)              │
│  app/models/recon.py             (NEW, Pydantic schemas)       │
│  app/static/cached_static.py     (NEW, StaticFiles subclass    │
│                                   with immutable Cache-Control)│
│  data/recon_manifest.json        (NEW, source of truth)        │
│  static/recon/JAX_NNN_final.ply  (Bootstrap-populated, 8 files)│
│  static/recon/NYC_NNN_final.ply  (Bootstrap-populated, 4 files)│
└────────────────────────────────────────────────────────────────┘
                              ▲
                              │ writes
                              │
┌────────────────────────────────────────────────────────────────┐
│ One-Time Bootstrap                                             │
│  scripts/recon/bootstrap_skyfall_plys.py    (NEW)              │
│   - hf download jayinnn/Skyfall-GS-ply      (cached)           │
│   - copy/symlink JAX_*_final.ply / NYC_*_final.ply into        │
│       services/backend/static/recon/                           │
│   - emit recon_manifest.json with mapping table:               │
│       hf_filename ↔ scene_id ↔ display_name ↔ bounds           │
│   - SHA256 verify each PLY                                     │
│   - audit per-dataset source-imagery license (see Risk 4)      │
│  Runnable via: ./odin.sh recon bootstrap  (NEW thin wrapper)   │
└────────────────────────────────────────────────────────────────┘
```

Three new modules in three existing services. Bootstrap runs once per fresh
checkout (or whenever HF asset hashes change).

---

## 5. Components

### 5.1 Backend

**Path:** `services/backend/app/routers/recon.py`

Two endpoints, both READ-ONLY, registered with the same dual-prefix idiom
already used in `services/backend/app/main.py:111-112` for back-compat
routers:

```python
# in app/main.py, alongside the existing dual-prefix block
app.include_router(recon.router, prefix="/api")
app.include_router(recon.router, prefix="/api/v1")
```

The router itself declares no prefix; the registration determines the URLs.
Resulting paths:

- `GET /api/recon/scenes` (primary) — returns the manifest as JSON.
- `GET /api/v1/recon/scenes` (alias) — same response, kept for back-compat.
- `GET /api/recon/scenes/{scene_id}` (primary) — returns one scene, or 404.
- `GET /api/v1/recon/scenes/{scene_id}` (alias) — same response.

The manifest is loaded once at app startup (`recon_manifest.json`) into an
in-memory dict keyed by `scene_id`. No per-request file I/O on the metadata
path.

**Static-file serving:** PLY bytes are served by a small `StaticFiles`
subclass at `services/backend/app/static/cached_static.py`:

```python
from starlette.staticfiles import StaticFiles
from starlette.responses import Response

class CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that adds immutable Cache-Control headers.
    Range requests work as in the parent class (Starlette FileResponse
    already returns 206 Partial Content when a Range header is present)."""
    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 206):
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )
        return response
```

Mount in `app/main.py`:

```python
app.mount(
    "/static/recon",
    CachedStaticFiles(directory="static/recon"),
    name="recon_static",
)
```

Range-request behavior is inherited from Starlette's `FileResponse` (which
`StaticFiles` uses internally) and is verified by the
`test_ply_range_request_returns_206_with_correct_bytes` test (Section 10).

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
    scene_id: str          # e.g. "jax_068" (canonical, lowercase)
    hf_filename: str       # e.g. "JAX_068_final.ply" (verbatim from HF repo)
    display_name: str      # e.g. "Jacksonville District 068"
    ply_url: str           # e.g. "/static/recon/JAX_068_final.ply"
    ply_size_bytes: int
    ply_sha256: str
    bounds: GeoBounds
    bounds_source: Literal["spacenet_metadata", "manual"]  # provenance
    default_camera: DefaultCamera
    attribution: str       # populated from per-dataset license audit
    source: Literal["skyfall_gs_hf"] | str  # extensible for Phase B
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

- `manifest.ts` — typed fetch + in-memory cache for `/api/recon/scenes`,
  exposes `useReconManifest()` React hook (TanStack Query if already in repo,
  otherwise plain hook with SWR-style cache).
- `types.ts` — TypeScript mirrors of backend Pydantic models.

**Path:** `services/frontend/src/components/layers/` *(sibling to FIRMSLayer,
GDACSLayer, EONETLayer, etc. — this is where every other Cesium billboard
layer lives in the codebase; not `components/globe/`)*

- `ReconLayer.tsx` — Cesium imperative `BillboardCollection` layer (per
  existing pattern: never Entity API). Props mirror the
  `services/frontend/src/components/layers/FIRMSLayer.tsx:58,66` shape:

  ```ts
  interface ReconLayerProps {
    viewer: Cesium.Viewer;
    scenes: ReconScene[];
    visible: boolean;
    onSelect?: (scene: ReconScene) => void;
  }
  ```

  Internal `onSelectRef = useRef(onSelect)` keeps the picker callback stable
  across re-renders, mirroring `FIRMSLayer.tsx:72-73` and
  `GDACSLayer.tsx:101-102`. The parent (`pages/WorldviewPage.tsx`) wires
  `onSelect` to `reconContext.openScene(scene.scene_id)`. The shared
  `components/globe/EntityClickHandler.tsx` is **not** used — it routes to
  the Knowledge Graph entity panel, which is the wrong destination here. The
  per-layer `onSelect` keeps recon's UX completely separate.

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

**Path:** `scripts/recon/bootstrap_skyfall_plys.py`

Idempotent Python script. Steps:

1. Verify `hf` CLI (HuggingFace) is on PATH; exit non-zero with actionable
   error message if not.
2. `hf download jayinnn/Skyfall-GS-ply` into `~/.cache/huggingface/...`
   (default cache path).
3. For each entry in the **Asset Mapping Table** (below), copy or symlink the
   downloaded file into `services/backend/static/recon/<hf_filename>`.
4. Compute SHA256 per PLY, compare against expected size from the table, log
   any mismatches (do not silently accept).
5. For each scene, write a `default_camera` derived from the Skyfall-GS
   author-supplied JSON metadata in `Skyfall-GS-datasets`, falling back to a
   sensible orbit-style default if no per-scene file ships.
6. Run **license audit** for each scene's source dataset (see Risk 4) and
   embed the resulting attribution string into the manifest.
7. Write `services/backend/data/recon_manifest.json`.

Re-running the script is idempotent: if the SHA in the manifest matches the
on-disk file, that step is skipped.

#### Asset Mapping Table

Source: `https://huggingface.co/api/models/jayinnn/Skyfall-GS-ply/tree/main`
(verified 2026-05-11). Sizes in bytes from the HF API; SHAs are populated by
the bootstrap step. Bounds are seeded from SpaceNet metadata; one-time manual
review during bootstrap may refine them.

| `scene_id`  | `hf_filename`           | size (bytes)  | display name                  | source group |
|-------------|-------------------------|---------------|-------------------------------|--------------|
| `jax_004`   | `JAX_004_final.ply`     | 158,510,569   | Jacksonville District 004     | SpaceNet 4   |
| `jax_068`   | `JAX_068_final.ply`     | 240,164,505   | Jacksonville District 068     | SpaceNet 4   |
| `jax_164`   | `JAX_164_final.ply`     | 290,453,497   | Jacksonville District 164     | SpaceNet 4   |
| `jax_168`   | `JAX_168_final.ply`     | 265,047,857   | Jacksonville District 168     | SpaceNet 4   |
| `jax_175`   | `JAX_175_final.ply`     | 232,601,521   | Jacksonville District 175     | SpaceNet 4   |
| `jax_214`   | `JAX_214_final.ply`     | 222,097,625   | Jacksonville District 214     | SpaceNet 4   |
| `jax_260`   | `JAX_260_final.ply`     | 227,118,225   | Jacksonville District 260     | SpaceNet 4   |
| `jax_264`   | `JAX_264_final.ply`     | 272,916,913   | Jacksonville District 264     | SpaceNet 4   |
| `nyc_004`   | `NYC_004_final.ply`     | 243,791,921   | New York City Tile 004        | SpaceNet 2   |
| `nyc_010`   | `NYC_010_final.ply`     | 320,689,209   | New York City Tile 010        | SpaceNet 2   |
| `nyc_219`   | `NYC_219_final.ply`     | 324,186,833   | New York City Tile 219        | SpaceNet 2   |
| `nyc_336`   | `NYC_336_final.ply`     | 213,483,617   | New York City Tile 336        | SpaceNet 2   |

Total: 12 PLYs, ~3.0 GB on disk after bootstrap. Geographic bounds are
populated from SpaceNet metadata (a small lookup table embedded in the
bootstrap script) since the Skyfall-GS PLYs use a local metric coordinate
frame, not WGS84 — see Risk 3.

**Wrapper:** `odin.sh recon bootstrap` adds a thin shell wrapper following the
existing `odin.sh` subcommand convention.

---

## 6. Data Flow

```
[install]   developer runs: ./odin.sh recon bootstrap
            -> 12 PLYs land in services/backend/static/recon/
            -> recon_manifest.json written

[startup]   FastAPI loads manifest into memory
            Frontend GET /api/recon/scenes -> client-side cache

[browse]    Globe renders ReconLayer using manifest bounds
            12 visible billboard pins (8 over Jacksonville, 4 over NYC)

[click]     User clicks pin
            -> ReconLayer.onSelect(scene)
            -> reconContext.openScene("jax_068")
            -> ReconViewer modal mounts via portal
            -> WebGLCheck passes
            -> BandwidthGuard passes (or user confirms)

[load]      Modal lazy-imports Spark / gaussian-splats-3d module
            fetch /static/recon/JAX_068_final.ply  (HTTP Range, streaming)
            "first visible progress" target: <2s (loading bar w/ bytes)
            renderer initializes scene, applies default_camera
            "first navigable frame" target: <60s on 30 Mbps for 250 MB

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
  "version": 2,
  "generated_at": "2026-05-11T00:00:00Z",
  "source_commit": "<git sha of bootstrap script at run time>",
  "scenes": [
    {
      "scene_id": "jax_068",
      "hf_filename": "JAX_068_final.ply",
      "display_name": "Jacksonville District 068",
      "ply_url": "/static/recon/JAX_068_final.ply",
      "ply_size_bytes": 240164505,
      "ply_sha256": "<populated by bootstrap>",
      "bounds": {
        "center_lat": 30.3322,
        "center_lon": -81.6557,
        "radius_m": 350
      },
      "bounds_source": "spacenet_metadata",
      "default_camera": {
        "position": [0, 0, 200],
        "look_at": [0, 0, 0],
        "fov_deg": 60
      },
      "attribution": "<populated by bootstrap license-audit step; e.g. 'Reconstruction: Skyfall-GS (Lee et al., 2025; arXiv:2510.15869v3) — Apache 2.0. Source imagery: SpaceNet 4 Off-Nadir Buildings (license verified at bootstrap, see LICENSES.md).'>",
      "source": "skyfall_gs_hf"
    }
  ]
}
```

Phase B adds entries with `"source": "spacenet_local_train"` (or other tag)
and a different `ply_url` pointing at locally trained PLYs — no schema
change required. Bumping `version` is the contract for breaking schema
changes.

---

## 8. API Contract

### `GET /api/recon/scenes`  (alias: `GET /api/v1/recon/scenes`)

Returns the entire manifest minus the `source_commit` and internal fields.

```json
{
  "scenes": [
    {
      "scene_id": "jax_068",
      "hf_filename": "JAX_068_final.ply",
      "display_name": "Jacksonville District 068",
      "ply_url": "/static/recon/JAX_068_final.ply",
      "ply_size_bytes": 240164505,
      "bounds": {"center_lat": 30.3322, "center_lon": -81.6557, "radius_m": 350},
      "default_camera": {"position": [0,0,200], "look_at": [0,0,0], "fov_deg": 60},
      "attribution": "Reconstruction: Skyfall-GS ... Source imagery: SpaceNet 4 ...",
      "source": "skyfall_gs_hf"
    }
  ]
}
```

### `GET /api/recon/scenes/{scene_id}`  (alias: `GET /api/v1/recon/scenes/{scene_id}`)

Returns a single `ReconScene` or HTTP 404 with `{"detail": "scene not found"}`.

### `GET /static/recon/{HF_FILENAME}`

Examples: `JAX_068_final.ply`, `NYC_010_final.ply`. Served by the
`CachedStaticFiles` subclass defined in Section 5.1; returns 200 for full
requests, 206 for Range requests. Sets `Cache-Control: public,
max-age=31536000, immutable` on every successful response.

### Error responses

All recon endpoints return JSON `{"detail": "<reason>"}` on error, status codes
follow FastAPI defaults.

---

## 9. Error Handling

| Condition                              | Behavior                                                                      |
|----------------------------------------|-------------------------------------------------------------------------------|
| Manifest missing at startup            | Log error, mount router but every request returns 503 with explanation.       |
| PLY file missing (manifest references) | `/api/recon/scenes/{id}` succeeds, static file 404, frontend shows retry.    |
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
  - `test_list_scenes_under_v1_alias_matches_primary`
  - `test_get_scene_by_id`
  - `test_get_scene_404_for_unknown_id`
  - `test_router_503_when_manifest_missing`
- `test_recon_static.py`
  - `test_ply_full_request_returns_200_with_immutable_cache_control`
  - `test_ply_range_request_returns_206_with_correct_bytes`
  - `test_ply_unknown_filename_returns_404`
- Fixtures use a tiny synthetic PLY (~1 KB) and a 2-scene manifest stub.

### Bootstrap script (pytest, scripts/recon/tests/)

- `test_bootstrap_skyfall_plys.py`
  - `test_hf_filename_to_scene_id_mapping_table_complete` — every entry in
    the mapping table has a unique `scene_id`, lowercase, matches HF
    filename pattern.
  - `test_manifest_schema_validates_against_pydantic` — the emitted manifest
    can be parsed back via the backend Pydantic models.
  - `test_idempotent_rerun_skips_unchanged` — running twice with no changes
    on disk yields a manifest with identical SHA fields and no PLY-copy
    operations.
  - `test_missing_hf_cli_exits_with_actionable_message` — script exits
    non-zero with a message naming the install command when `hf` is not on
    PATH.
  - `test_size_mismatch_logs_warning` — mocked HF download produces a file
    with unexpected size; bootstrap logs and continues but flags the entry.
- HF interaction mocked; tests run without network.

### Frontend (vitest, services/frontend/src/)

- `recon/ReconViewer.test.tsx`
  - renders modal when context flag set
  - calls `closeScene` on ESC
  - shows attribution footer
- `recon/manifest.test.ts`
  - hook returns scenes after fetch (against `/api/recon/scenes`)
  - hook surfaces error on 503
- `layers/ReconLayer.test.tsx`
  - creates billboard per manifest entry
  - calls `onSelect` with the right scene on click
  - mirrors `layers/__tests__/FIRMSLayer.test.tsx` structure
- Renderer module is mocked in component tests; integration tested manually.

### End-to-End (manual, documented in `docs/workflows/recon-smoke.md`)

1. Fresh checkout, run `./odin.sh recon bootstrap`.
2. `./odin.sh up interactive`.
3. Browser to `http://localhost:5173`.
4. Verify twelve Recon pins visible (8 over Jacksonville, 4 over NYC).
5. For each scene tier (smallest ~150 MB JAX, mid ~250 MB JAX, largest
   ~325 MB NYC): click pin, measure (a) "first visible progress" time,
   (b) "first navigable frame" time. Record both into the workflow doc.
6. Verify WASD navigation, PNG capture, ESC close.
7. Run on a Chromium build with WebGL2 disabled, verify graceful refusal.
8. Throttle DevTools to "Slow 3G", verify bandwidth guard fires.

### Phase 0 Smoke — Renderer + Load Time Gate (blocks Phase A)

This is a **gate**, not just a test. Before any production code is written:

1. **Renderer parity:** one-page HTML harness loads `JAX_068_final.ply` in
   both Spark and `@mkkellogg/gaussian-splats-3d`, side-by-side with the
   reference render from Skyfall-GS's official Mip-Splatting demo URL.
   Visual parity (no obvious blur / aliasing differences) is the first
   condition.
2. **Load-time measurement:** for the same PLY, on the developer's local
   network, record:
   - Time to first byte from the local cache.
   - Time to "first visible progress" event (loading bar appears with a
     non-zero byte count) — must be under 2 s.
   - Time to "first navigable frame" — must be under 60 s on a 30 Mbps
     throttled connection (using DevTools throttling).
3. **Decision artifact:** results land in
   `docs/workflows/recon-phase-0-smoke.md` with screenshots and chosen
   renderer. If neither renderer meets parity or the timing budget on a
   representative PLY, Phase A is paused and the spec is revisited.

---

## 11. Risks and Mitigations

### Risk 1 — Mip-Splatting PLY format mismatch

Skyfall-GS PLYs encode Mip-Splatting kernel parameters that not every Web
3DGS renderer interprets. A naive renderer may produce noticeably blurrier or
aliased output. **Mitigation:** the pre-implementation smoke test (Section 10)
runs before any backend or frontend code is written. Renderer choice is locked
in based on visual parity with the official Skyfall-GS demo.

### Risk 2 — PLY bandwidth on first load

PLYs in this set range from 158 MB (`JAX_004_final.ply`) to 324 MB
(`NYC_219_final.ply`). On residential broadband (~30 Mbps) that is roughly 40
to 90 seconds to fully transferred. **HTTP Range alone does not guarantee an
early frame** — that depends entirely on the renderer's progressive-decode
behavior. The Phase 0 smoke test (Section 10) measures both "first visible
progress" and "first navigable frame" on a representative PLY before any
production code is written; the Goals (Section 3) state the two distinct
budgets and the smoke gates them. **Mitigations:** `Cache-Control: immutable`
makes second views instant; the bandwidth guard warns on metered connections;
scenes >300 MB are tagged "large" in the UI so the user can choose. A public
demo would need WebTransport or mesh LoD which is out of scope.

### Risk 3 — Globe coordinate mapping is manual

Skyfall-GS PLYs use a local right-handed metric coordinate frame, not WGS84.
Pin placement depends on the manually populated `bounds` field in the
manifest, with `bounds_source` recording provenance ("spacenet_metadata" or
"manual"). For the twelve known scenes this is a one-time table seeded from
SpaceNet metadata; for arbitrary Phase B AOIs an automated pipeline will be
needed (SatelliteSfM emits WGS84 geo-anchors that can be reused).
**Mitigation:** Phase A accepts the seeded-from-metadata-plus-manual-review
table as documented technical debt; Phase B's SatelliteSfM run derives bounds
automatically.

### Risk 4 — License / attribution provenance is not yet fully audited

Verified at spec time:

- **Skyfall-GS code (this paper's repo):** Apache 2.0 — confirmed from the HF
  model card.
- **Skyfall-GS PLY assets on `jayinnn/Skyfall-GS-ply`:** the HF repo declares
  `apache-2.0` as the model license — confirmed.

**Not yet verified at spec time** (must be done at bootstrap):

- The exact license of the **source satellite imagery** behind each scene.
  The JAX scenes correspond to SpaceNet 4 (Off-Nadir Buildings); the NYC
  scenes correspond to SpaceNet 2. Historically SpaceNet datasets have been
  released under CC-BY-SA-4.0, but **per-dataset terms vary** (the SpaceNet
  site itself notes this) and Maxar/DigitalGlobe imagery has had additional
  redistribution clauses. The previously-asserted blanket "CC-BY-SA-4.0" was
  premature.

**Mitigation:** the bootstrap script's license-audit step (Section 5.3, step
6) is responsible for:

1. Pulling the canonical license text for each source dataset (SpaceNet 2,
   SpaceNet 4) from the upstream source.
2. Writing the per-scene attribution string into the manifest based on that
   audit.
3. Writing a top-level `services/backend/static/recon/LICENSES.md` linking
   to the upstream license documents.
4. Failing closed: if a per-dataset license cannot be confirmed, the
   corresponding scene is **excluded** from the manifest rather than served
   with a guess. The script logs which scenes were excluded and why.

The viewer modal's footer renders the `attribution` field verbatim, so
whatever the audit produces is what the user sees.

### Risk 5 — Renderer drops support / library churn

Web 3DGS renderers are young (Spark, gsplat.js, others). A library could be
abandoned. **Mitigation:** the renderer is encapsulated behind a thin
interface (`renderScene(canvas, plyUrl, defaultCamera) -> Disposer`). Swapping
it requires touching one module.

---

## 12. Rollout

### Phase 0 — Smoke Gate (blocks Phase A; see Section 10)

Before any production code is written:

1. Renderer parity check (Spark vs `@mkkellogg/gaussian-splats-3d` vs
   official Skyfall-GS Mip-Splatting demo) — pick a winner.
2. Load-time measurement on a representative PLY — confirm the two
   latency budgets in Goal 1 are achievable.

Output: `docs/workflows/recon-phase-0-smoke.md` with screenshots and chosen
renderer. If neither candidate meets parity or budget, the spec is paused
and revisited.

### Phase A — MVP

Ships in a single feature branch (`feature/skyfall-recon-mvp`) and merges to
`main` once Phase 0 has produced a renderer decision, all backend / frontend
/ bootstrap tests pass, and the manual end-to-end smoke is documented in the
workflows directory.

No feature flag — recon is additive, hidden behind globe pins that only
appear when the manifest contains scenes. If bootstrap is not run, no pins
appear and the rest of WorldView is unaffected.

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
  from Satellite Imagery*, arXiv:2510.15869v3 (submitted 2025, last revised
  18 March 2026). https://arxiv.org/abs/2510.15869
- **Code:** https://github.com/jayin92/skyfall-gs (Apache 2.0)
- **Pre-built PLYs:** https://huggingface.co/jayinnn/Skyfall-GS-ply
  (Apache 2.0; verified against
  https://huggingface.co/api/models/jayinnn/Skyfall-GS-ply/tree/main on
  2026-05-11)
- **Datasets:** https://huggingface.co/datasets/jayinnn/Skyfall-GS-datasets
- **SpaceNet (data origin, license per-dataset, audited at bootstrap):**
  https://spacenet.ai/datasets/
- **Mip-Splatting:** https://github.com/autonomousvision/mip-splatting
- **Spark renderer (candidate):** https://github.com/sparkjs/spark
- **gaussian-splats-3d (fallback candidate):** https://github.com/mkkellogg/GaussianSplats3D
- **Starlette `FileResponse` Range support:** https://www.starlette.io/responses/
- **WorldView CLAUDE.md:** `~/ODIN/OSINT/CLAUDE.md`
- **Existing layer pattern:** `services/frontend/src/components/layers/FIRMSLayer.tsx`
- **Existing dual-prefix routing:** `services/backend/app/main.py:111-117`
