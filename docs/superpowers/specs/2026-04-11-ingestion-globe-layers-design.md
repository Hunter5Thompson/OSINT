# Ingestion Globe Layers — FIRMS Hotspots & Military Aircraft Tracks

**Date:** 2026-04-11
**Status:** Design approved, ready for implementation plan
**Scope:** Backend routers + Frontend layers + Layer-Panel + Info-Panel for FIRMS thermal anomalies and Military Aircraft tracks collected by the Hugin P0 ingestion sprint.

## Motivation

The Hugin P0 collectors (FIRMS, Military Aircraft) write data to Qdrant and Neo4j every ingestion cycle. As of 2026-04-10 the stack holds 187 FIRMS hotspots and several MilitaryAircraft nodes with SPOTTED_AT edges, but **none of this data is visible on the CesiumJS globe**. Without a visual layer the ingestion value is invisible to the operator.

This sprint closes that gap for the two most-valuable Hugin sources. USGS, correlation matches, and future P1 sources are out of scope.

## Non-Goals

- Filter UI (explosion-only toggle, time-slider, active-only) — YAGNI until requested
- Clustering or LOD thinning — current volumes do not warrant it
- WebSocket / SSE streams — polling is sufficient, both feeds are ingestion-driven
- New SVG asset files — all icons rendered inline to HTML canvas
- Changes to collectors — read-only consumers of existing data
- USGS, Correlation, or Sprint 2 sources — separate spec
- Typ-specific aircraft icons — generic jet silhouette, type in tooltip

## Architecture Overview

```
Qdrant (odin_intel)          Neo4j
  source=firms                 (:MilitaryAircraft)-[:SPOTTED_AT]->(:Location)
       |                              |
       v                              v
+----------------------------------------------+
|  Backend (FastAPI, :8080)                    |
|  /api/v1/firms/hotspots  /api/v1/aircraft/tracks |
|    (Qdrant scroll)       (Cypher read-only)  |
|    Redis cache 60s       Redis cache 30s     |
+----------------------------------------------+
       |                              |
       v                              v
+----------------------------------------------+
|  Frontend (React + Cesium, :5173)            |
|  FIRMSLayer            MilAircraftLayer      |
|    BillboardColl         BillboardColl       |
|                          + PolylineColl      |
|          \               /                   |
|           v             v                    |
|    OperationsPanel "Ingestion" sub-section   |
|    Click -> SelectionPanel (bottom-left)     |
+----------------------------------------------+
```

- Backend owns the translation from storage-native shapes (Qdrant payload, Neo4j rows) to lean JSON the globe can consume directly.
- Frontend layers follow the established `BillboardCollection` pattern (see `EarthquakeLayer.tsx`).
- Polling intervals: **60 s** for FIRMS, **30 s** for Aircraft.
- Polling pauses when `document.hidden`.
- No WebSockets; the data pipeline is batch-ingestion driven, so real-time push has no value here.

## Backend — Infrastructure prerequisites

The current backend has `app.state.proxy` and `app.state.cache` only. Qdrant and Neo4j are not initialized at startup. This spec adds the minimum wiring needed.

### Dependencies

Add to `services/backend/pyproject.toml`:

```toml
dependencies = [
  ...,
  "qdrant-client>=1.13",
]
```

### Qdrant client

Follow the existing `graph.py` pattern (lazy module-global) rather than lifespan init — no changes to `main.py` lifespan required.

**New file:** `services/backend/app/services/qdrant_client.py`

```python
from qdrant_client import AsyncQdrantClient
from app.config import settings

_client: AsyncQdrantClient | None = None

async def get_qdrant_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client
```

`settings.qdrant_url` must be added to `app/config.py` if missing (default `http://qdrant:6333` for Docker, `http://localhost:6333` for local).

### Neo4j reader helper

Reuse the existing `_read_query(cypher, params)` helper already implemented in `services/backend/app/routers/graph.py:32-37`. Extract it into `services/backend/app/services/neo4j_client.py` so both `graph.py` and the new `aircraft.py` can import it without cross-router dependencies. `graph.py` is refactored to import from the new module — a pure move, no behavior change.

## Backend — FIRMS Router

**New file:** `services/backend/app/routers/firms.py`

### Endpoint

```
GET /api/v1/firms/hotspots?since_hours=24
```

- Router is mounted with `prefix="/api/v1"` in `main.py` like all existing routers
- `since_hours` is an int query parameter, default 24, minimum 1, maximum 168 (7 days); values outside the range produce HTTP 422 via `Query(ge=1, le=168)`
- Uses `get_qdrant_client()` to fetch the async Qdrant client
- Returns `list[FIRMSHotspot]`

### Qdrant query (with pagination)

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

cutoff = int(time.time()) - since_hours * 3600
flt = Filter(must=[
    FieldCondition(key="source", match=MatchValue(value="firms")),
    FieldCondition(key="ingested_epoch", range=Range(gte=cutoff)),
])

results: list[dict] = []
next_offset = None
page_size = 512
max_total = 5000   # safety ceiling
while True:
    points, next_offset = await qdrant.scroll(
        collection_name="odin_intel",
        scroll_filter=flt,
        limit=page_size,
        offset=next_offset,
        with_payload=True,
        with_vectors=False,
    )
    results.extend(points)
    if next_offset is None or len(results) >= max_total:
        break
```

- `ingested_epoch` is guaranteed on FIRMS payloads (added in the 2026-04-10 correlation sprint)
- Loop protects against silent truncation; `max_total` is a hard ceiling to prevent runaway responses if the filter degenerates

### Response model

```python
class FIRMSHotspot(BaseModel):
    id: str
    latitude: float
    longitude: float
    frp: float               # Fire Radiative Power (MW)
    brightness: float        # Kelvin
    confidence: str          # "l" | "n" | "h"
    acq_date: str            # "2026-04-11"
    acq_time: str            # "1423"
    satellite: str           # "VIIRS_SNPP_NRT" | ...
    bbox_name: str           # "ukraine" | ...
    possible_explosion: bool
    firms_map_url: str       # computed server-side, see below
```

**`firms_map_url` is computed server-side** from payload fields — the collector currently does not persist the URL into the Qdrant payload (only the `row` dict reaches `_build_point`, and `row` has no `url` key). The URL format is deterministic:

```python
firms_map_url = (
    f"https://firms.modaps.eosdis.nasa.gov/map/#d:{acq_date};"
    f"@{longitude:.4f},{latitude:.4f},10z"
)
```

No collector change is needed.

### Caching & errors

- Redis key `firms:hotspots:{since_hours}h`, TTL 60 s (shorter than FIRMS collection cadence). Cache protects Qdrant under multi-client polling.
- Qdrant unreachable → HTTP 503, no fallback to defaults. Cache is not served when stale.

### Tests — `test_firms_router.py`

- Qdrant client mocked via `AsyncMock`.
- Cases:
  1. Happy path — 3 points with mixed `possible_explosion` values → 3 normalized items returned.
  2. Empty result → `[]`.
  3. `since_hours` param passed into `Range(gte=...)` computation.
  4. `possible_explosion` flag propagated unchanged.
  5. `firms_map_url` is computed correctly from lat/lon/acq_date.
  6. Redis cache hit short-circuits Qdrant call.
  7. **Pagination** — mocked scroll returns `(page1, next_offset=token)`, then `(page2, None)`; router concatenates both pages.
  8. **Boundary 422** — `since_hours=0` and `since_hours=169` return HTTP 422 (FastAPI validation).
  9. **max_total ceiling** — scroll keeps returning pages; loop stops at `max_total` without infinite iteration.

## Backend — Aircraft Router

**New file:** `services/backend/app/routers/aircraft.py`

### Endpoint

```
GET /api/v1/aircraft/tracks?since_hours=24
```

- Router mounted with `prefix="/api/v1"` in `main.py`
- `since_hours` is `Query(default=24, ge=1, le=72)` — values outside the range return HTTP 422
- Uses the extracted `_read_query(cypher, params)` helper from `app/services/neo4j_client.py`
- Returns `list[AircraftTrack]`

### Cypher — verified against `military_aircraft_collector.py`

```cypher
MATCH (a:MilitaryAircraft)-[r:SPOTTED_AT]->()
WHERE r.timestamp >= $since_epoch
  AND r.latitude IS NOT NULL
  AND r.longitude IS NOT NULL
WITH a, r ORDER BY r.timestamp ASC
WITH a,
     collect({
       lat: r.latitude,
       lon: r.longitude,
       altitude_m: r.altitude_m,
       speed_ms: r.speed_ms,
       heading: r.heading,
       timestamp: r.timestamp
     }) AS points
WHERE size(points) >= 1
RETURN a.icao24          AS icao24,
       a.callsign        AS callsign,
       a.type_code       AS type_code,
       a.military_branch AS military_branch,
       a.registration    AS registration,
       points
ORDER BY points[-1].timestamp DESC
LIMIT 500
```

Parameters:
- `$since_epoch = int(time.time()) - since_hours * 3600`

Mandatory per `CLAUDE.md`: parameter binding, read-only session, no LLM-generated Cypher.

### Schema notes (verified 2026-04-11)

- `Location` nodes are keyed by **region name** (e.g. `"ukraine"`), not coordinate. Actual lat/lon lives on the `SPOTTED_AT` edge. We ignore the Location node entirely in this query.
- `SPOTTED_AT` dedup key is `"icao24|15-minute-bucket"`, so each aircraft has at most ~96 edges per 24 h. Tracks are inherently 15-min-resolution — polylines will look stepped, which is acceptable for intel "where was it" use rather than flight-sim accuracy.
- Edge properties use metric units (`altitude_m`, `speed_ms`). Aircraft node has `type_code`, not `aircraft_type`, and `military_branch`, not `operator`.

### Response model

```python
class AircraftPoint(BaseModel):
    lat: float
    lon: float
    altitude_m: float | None
    speed_ms: float | None
    heading: float | None
    timestamp: int   # epoch seconds

class AircraftTrack(BaseModel):
    icao24: str
    callsign: str | None
    type_code: str | None
    military_branch: str | None
    registration: str | None
    points: list[AircraftPoint]
```

### Caching & errors

- Redis key `aircraft:tracks:{since_hours}h`, TTL 30 s.
- Neo4j unreachable → HTTP 503.

### Tests — `test_aircraft_router.py`

- `_read_query` patched to return canned records.
- Cases:
  1. Happy path — two aircraft, one with 5 points, one with 1 point, verify ordering (points asc, tracks by newest last-point desc).
  2. Empty result → `[]`.
  3. `since_hours` param translates to correct `$since_epoch` (mock `time.time()` for determinism).
  4. Record with null lat/lon is filtered out at the Cypher layer (assert the query string contains `IS NOT NULL`).
  5. Redis cache hit short-circuits Neo4j call.
  6. **Boundary 422** — `since_hours=0` and `since_hours=73` return HTTP 422.

## Frontend — FIRMS Layer

**New file:** `services/frontend/src/components/layers/FIRMSLayer.tsx`

### Shape

```tsx
interface FIRMSHotspot {
  id: string;
  latitude: number;
  longitude: number;
  frp: number;
  brightness: number;
  confidence: string;
  acq_date: string;
  acq_time: string;
  satellite: string;
  bbox_name: string;
  possible_explosion: boolean;
}

interface FIRMSLayerProps {
  viewer: Cesium.Viewer | null;
  hotspots: FIRMSHotspot[];
  visible: boolean;
  onSelect?: (h: FIRMSHotspot) => void;
}
```

### Rendering

- One `BillboardCollection` added as a scene primitive, mirroring `EarthquakeLayer.tsx`.
- Per hotspot: a dot billboard with size + color driven by FRP.
  - Size: `6 + min(frp / 4, 16)` px → range 6..22.
  - Color: linear interpolation `YELLOW → ORANGE → RED` across `frp ∈ [0, 100]`, clamped. Alpha boosted slightly by brightness relative to 300–420 K range.
  - Dot drawn via inline canvas helper `createFIRMSDot(size, color)` using a radial gradient for glow, following the same pattern as `createQuakeDot`.
- `possible_explosion === true` adds a second ring-billboard at the same position with a permanent pulse animation:
  - Phase `(now * 0.003) % (2π)`
  - Scale 1.0..1.5 (`1.0 + 0.5 * sin(phase)`)
  - Alpha 0.4..0.8 (`0.8 - 0.4 * sin(phase)`)
  - Same easing constants as `EarthquakeLayer` M ≥ 7 case, for visual consistency.
- EyeOffset `(0, 0, -45)` so FIRMS renders below aircraft icons but above terrain features.
- Pulse loop uses `requestAnimationFrame`, respects `PerformanceGuard` degradation level (skip animation when `degradation >= 2`).

### Click / hover

- App.tsx installs a `ScreenSpaceEventHandler` (or extends an existing one) that picks on `LEFT_CLICK`.
- If the picked primitive is a FIRMS billboard, look up the hotspot by id in a ref map and call `props.onSelect(hotspot)`.

### Data fetch — `hooks/useFIRMSHotspots.ts` (new)

```tsx
export function useFIRMSHotspots(sinceHours = 24): FIRMSHotspot[] {
  const [data, setData] = useState<FIRMSHotspot[]>([]);
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (document.hidden) return;
      try {
        const res = await fetch(`${API_BASE}/api/v1/firms/hotspots?since_hours=${sinceHours}`);
        if (!res.ok) return;
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (err) {
        console.warn("FIRMS fetch failed", err);
      }
    };
    tick();
    const id = setInterval(tick, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [sinceHours]);
  return data;
}
```

### Tests — `FIRMSLayer.test.tsx` + `useFIRMSHotspots.test.ts`

- Unit: `createFIRMSDot(frp)` returns canvas with expected dimensions for FRP = 0, 50, 200.
- Component: mount with 3 mock hotspots (one flagged explosion) against a fake Cesium viewer, assert billboard collection size === 4 (3 dots + 1 ring).
- Hook: `vi.useFakeTimers()` + mocked `fetch` — verify initial call, interval call at 60 s, pause when `document.hidden = true`.

## Frontend — Military Aircraft Layer

**New file:** `services/frontend/src/components/layers/MilAircraftLayer.tsx`

### Shape

```tsx
interface AircraftPoint {
  lat: number;
  lon: number;
  altitude_m: number | null;
  speed_ms: number | null;
  heading: number | null;
  timestamp: number;
}

interface AircraftTrack {
  icao24: string;
  callsign: string | null;
  type_code: string | null;
  military_branch: string | null;
  registration: string | null;
  points: AircraftPoint[];
}

interface MilAircraftLayerProps {
  viewer: Cesium.Viewer | null;
  tracks: AircraftTrack[];
  visible: boolean;
  onSelect?: (t: AircraftTrack) => void;
}
```

### Rendering — two collections

**1. `PolylineCollection`** — one polyline per track with `points.length >= 2`:

- Positions: `Cesium.Cartesian3.fromDegreesArrayHeights([lon, lat, alt_m, ...])`. Missing `altitude_m` defaults to 0.
- Polylines render at **true altitude**, so tanker orbits and AWACS racetracks are recognizable as 3D shapes.
- Material: uniform per-polyline color via `Cesium.Material.fromType("Color", { color: branchColorWithAlpha })` — the same pattern used by `FlightLayer.tsx:247-255`. `PolylineCollection.add()` does not accept `PolylineColorAppearance`; per-vertex coloring would require per-segment Primitive geometry, which is out of scope for v1.
- Alpha: uniform 0.6 per polyline. Age-based fade is deferred to a later iteration.
- Width 1.5.

**2. `BillboardCollection`** — one icon per track at the **latest** point:

- Generic military jet silhouette drawn by inline canvas helper `createJetIcon(color, size=24)`. Simple angular silhouette (fuselage + swept wings + tail), solid fill plus 1 px dark outline. No external asset.
- Rotation: `Cesium.Math.toRadians(-(heading ?? 0) + 90)` — Cesium billboard rotation 0° points east, aviation heading 0° points north.
- Color by `military_branch`:
  - `USAF` → cyan `#66e6ff`
  - `USN` / `USMC` → blue `#4d9fff`
  - `RUAF` / `VKS` → red `#ff5050`
  - any other known branch → amber `#ffaa33`
  - unknown/null → white
- Scale 0.8, EyeOffset `(0, 0, -40)`.

### Edge cases

- Track with only 1 point: skip polyline, render billboard only.
- Track with all `altitude_m` null: polyline at ground level (all zeros), still renders.
- `heading` null: billboard uses rotation 0 (points east), acceptable fallback.

### Click / hover

- `LEFT_CLICK` pick on billboard **or** any polyline segment: look up the track via an `icao24 → AircraftTrack` ref map and call `props.onSelect(track)`.

### Data fetch — `hooks/useAircraftTracks.ts` (new)

Same shape as `useFIRMSHotspots`, 30 s interval, `GET ${API_BASE}/api/v1/aircraft/tracks?since_hours=24`.

Both hooks should import and reuse the existing `api.ts` client (`services/frontend/src/api.ts`) if it exposes a base or helper; otherwise call `fetch` directly against the URL derived from the same environment variable `api.ts` uses, to keep a single source of truth for the API base.

### Tests — `MilAircraftLayer.test.tsx` + `useAircraftTracks.test.ts`

- Unit: `trackToPolylinePositions(points)` returns a flat Cartesian3 array of expected length.
- Unit: `createJetIcon(color)` returns canvas with non-transparent silhouette.
- Component: two mock tracks (5-point, 1-point) → polyline collection length === 1, billboard collection length === 2.
- Hook: fake timers, mocked fetch, 30 s interval.

## Operations Panel — "Ingestion" sub-section

**Modified file:** `services/frontend/src/components/ui/OperationsPanel.tsx`

The existing `OperationsPanel` (left-docked, header "OPERATIONS") holds layer toggles driven by a `LAYER_CONFIG` array of `{key, label, color}` with matching `LayerIcon` cases. The new layers extend this structure rather than introducing a new component.

### Changes

- Add a "INGESTION" section header inside `OperationsPanel`, visually separated from the existing `DATA LAYERS` block by a thin border and small header label (`text-[10px] tracking-widest text-green-500/60`).
- Add two new entries to `LAYER_CONFIG`:

```tsx
{ key: "firmsHotspots", label: "FIRMS HOTSPOTS", color: "#ff7a33" },
{ key: "milAircraft",   label: "MIL AIRCRAFT",   color: "#66e6ff" },
```

- Extend `LayerIcon` `switch` with two new cases drawing a small flame glyph for `firmsHotspots` and a jet silhouette for `milAircraft`.
- Render the INGESTION entries in a separate `.map()` pass below the existing `LAYER_CONFIG` loop, so they appear grouped.
- Counter badges: append `({count})` to the label when the count is > 0. Counts come from new props `firmsCount`/`milAircraftCount` passed down by `App.tsx`. These are derived from hook data — no extra requests.

### LayerVisibility type extension

`services/frontend/src/types/index.ts` — `LayerVisibility` interface gains two fields:

```tsx
interface LayerVisibility {
  flights: boolean;
  satellites: boolean;
  // ... existing ...
  firmsHotspots: boolean;   // new
  milAircraft: boolean;     // new
}
```

Default values in `App.tsx` initial state: both `true`. `main.py` `client_config()` endpoint's `default_layers` dict is extended with the same two keys to stay in sync with the frontend default.

- The `visible` prop on each new layer is wired to `layers.firmsHotspots` / `layers.milAircraft`.

## Info Panel — Click details

**Placement decision:** The right side of the screen is already occupied by `RightPanel.tsx` (Intel + Graph tabs). Adding another right-docked panel would overlap. The selection-details panel instead docks **bottom-left**, below `OperationsPanel`, as a floating card. This keeps both side rails free and matches Cesium-operator UI conventions where a selected-feature readout sits near the map controls.

### New file

```
services/frontend/src/components/ui/SelectionPanel.tsx
```

- Bottom-left floating card, `absolute left-3 bottom-16`, ~300 px wide, max-height `40vh` with internal scroll, semi-transparent dark background matching `OperationsPanel` styling.
- Close button (×) top right.
- Returns `null` when `selected === null`.
- Discriminated union for typed content:

```tsx
type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: AircraftTrack };
```

### FIRMS content

- Title: "Thermal Anomaly"
- Grid rows: FRP (MW) • Brightness (K) • Confidence • Satellite • Acq (date + time) • BBox • Position (lat, lon)
- Red warning badge when `possible_explosion === true`: "POSSIBLE EXPLOSION"
- Link "View on FIRMS Map" opens `firms_map_url` (server-computed from acq_date/lat/lon, see Response Model section)

### Aircraft content

- Title: `{callsign}` (fallback `{icao24}`)
- Subtitle: `{type_code}` • `{military_branch}` • `{registration}`
- Grid rows: ICAO24 • Points in window • Latest position (lat, lon) • Altitude (m) • Speed (m/s) • Heading (°)
- Button "Center on track": computes `BoundingSphere.fromPoints(cartesians)` from track points, calls `viewer.camera.flyToBoundingSphere`.

### Wiring in App.tsx

```tsx
const [selected, setSelected] = useState<Selected | null>(null);

<FIRMSLayer ... onSelect={(h) => setSelected({ type: "firms", data: h })} />
<MilAircraftLayer ... onSelect={(t) => setSelected({ type: "aircraft", data: t })} />
<SelectionPanel selected={selected} onClose={() => setSelected(null)} viewer={viewer} />
```

## Data Flow Summary

```
FIRMSLayer        useFIRMSHotspots    /api/v1/firms/hotspots    Redis 60s
    ^                  |                    |                      |
    |   60s poll       v                    v                      v
    +- hotspots[] <-- setState <-- JSON <-- Qdrant scroll (source+time, paginated)

MilAircraftLayer  useAircraftTracks   /api/v1/aircraft/tracks   Redis 30s
    ^                  |                    |                      |
    |   30s poll       v                    v                      v
    +- tracks[] <---- setState <-- JSON <-- Neo4j _read_query (since_epoch)
```

- Fetch failures: hook keeps previous state, logs a warning, retries on next tick.
- Polling paused while `document.hidden`.
- Backend cache TTL < poll interval so clients always get fresh data while the DB is shielded from multi-client amplification.

## Testing Strategy

### Backend (pytest)

- `services/backend/tests/test_firms_router.py` — 5 cases (see FIRMS Router section).
- `services/backend/tests/test_aircraft_router.py` — 5 cases (see Aircraft Router section).
- Ruff + mypy clean on new files.

### Frontend (vitest + @testing-library/react)

- `FIRMSLayer.test.tsx`, `MilAircraftLayer.test.tsx` — mount with fake viewer.
- `useFIRMSHotspots.test.ts`, `useAircraftTracks.test.ts` — fake timers, mocked fetch.
- `SelectionPanel.test.tsx` — render both variants of the discriminated union.
- Type-check + ESLint clean.

### Manual smoke

1. `./odin.sh up ingestion` — wait for FIRMS + Military Aircraft to write data.
2. Verify Qdrant has `source=firms` points and Neo4j has `SPOTTED_AT` edges with recent `timestamp`.
3. `./odin.sh swap interactive` — start backend + frontend.
4. `curl localhost:8080/api/v1/firms/hotspots?since_hours=24 | jq length`
5. `curl localhost:8080/api/v1/aircraft/tracks?since_hours=24 | jq length`
6. `curl localhost:8080/api/v1/firms/hotspots?since_hours=0` → expect HTTP 422 (boundary check).
7. Open browser, toggle both layers in the Ingestion sub-section of OperationsPanel, verify counts match curl.
8. Click a FIRMS dot → SelectionPanel shows thermal anomaly details, "View on FIRMS Map" opens the computed URL.
9. Click an aircraft icon → SelectionPanel shows track details, "Center on track" flies the camera.
10. Find a `possible_explosion` hotspot (if any) and confirm the pulse ring renders.

## File Inventory

### New

- `services/backend/app/routers/firms.py`
- `services/backend/app/routers/aircraft.py`
- `services/backend/app/services/qdrant_client.py` — lazy async Qdrant client getter
- `services/backend/app/services/neo4j_client.py` — extracted `_read_query` helper
- `services/backend/tests/test_firms_router.py`
- `services/backend/tests/test_aircraft_router.py`
- `services/frontend/src/components/layers/FIRMSLayer.tsx`
- `services/frontend/src/components/layers/MilAircraftLayer.tsx`
- `services/frontend/src/components/ui/SelectionPanel.tsx` — bottom-left selection details
- `services/frontend/src/hooks/useFIRMSHotspots.ts`
- `services/frontend/src/hooks/useAircraftTracks.ts`
- `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx`
- `services/frontend/src/components/layers/__tests__/MilAircraftLayer.test.tsx`
- `services/frontend/src/hooks/__tests__/useFIRMSHotspots.test.ts`
- `services/frontend/src/hooks/__tests__/useAircraftTracks.test.ts`

### Modified

- `services/backend/pyproject.toml` — add `qdrant-client>=1.13` dependency
- `services/backend/app/config.py` — add `qdrant_url` setting if missing
- `services/backend/app/main.py` — register `firms` and `aircraft` routers with `/api/v1` prefix; extend `client_config.default_layers` with `firmsHotspots` and `milAircraft`
- `services/backend/app/routers/graph.py` — refactor to import `_read_query` from `app/services/neo4j_client.py` (pure move, no behavior change)
- `services/frontend/src/App.tsx` — new state, hooks, layer mounts, SelectionPanel wiring
- `services/frontend/src/components/ui/OperationsPanel.tsx` — Ingestion sub-section, extended `LAYER_CONFIG`, new `LayerIcon` cases, new props for counts
- `services/frontend/src/types/index.ts` — add `FIRMSHotspot`, `AircraftPoint`, `AircraftTrack`; extend `LayerVisibility` with `firmsHotspots` and `milAircraft`

## Open Verification Steps (before implementation)

- Confirm `ingested_epoch` is present on FIRMS payloads in production Qdrant (was added 2026-04-10; sanity check with a scroll query against the running stack).
- Confirm `services/frontend/src/api.ts` exports an API-base value or helper the new hooks can reuse (expected, since existing code uses `/api/v1`). If not, add one.
- Confirm that `qdrant_url` is already present in `services/backend/app/config.py` — if not, add it.

These checks happen during Task 1 of the implementation plan.

## Changes from initial review (2026-04-11)

This spec was reviewed and revised after a high-signal code review. Changes:

1. **All endpoints mounted under `/api/v1`** to match the existing backend router prefix.
2. **Backend infrastructure section added**: `qdrant-client` dependency, lazy Qdrant client getter in `app/services/qdrant_client.py`, Neo4j `_read_query` extracted from `graph.py` into `app/services/neo4j_client.py`.
3. **FIRMS `firms_map_url` is computed server-side** from payload fields — the collector does not persist a URL into the Qdrant payload.
4. **Aircraft polylines use uniform per-track color** via `Material.fromType("Color", ...)` — matches existing `FlightLayer` pattern. Per-vertex alpha fade dropped from v1 because `PolylineCollection.add()` does not accept `PolylineColorAppearance`.
5. **`OperationsPanel.tsx` is the real file**; `LayerPanel.tsx` does not exist. Two new entries added to its `LAYER_CONFIG` plus a new grouped "INGESTION" section below the existing layer block. `LayerVisibility` type extended. `client_config.default_layers` dict extended to stay in sync.
6. **Selection details panel docks bottom-left** as `SelectionPanel.tsx` because `RightPanel.tsx` already occupies the right side.
7. **Qdrant scroll is paginated** via `next_offset` loop with a safety ceiling of 5000 results.
8. **Tests cover boundary cases** — HTTP 422 for `since_hours=0` and above-max, pagination across multiple pages, `max_total` ceiling.
