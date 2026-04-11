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
|  /firms/hotspots       /aircraft/tracks      |
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
|      LayerPanel "Ingestion" sub-section      |
|      Click -> InfoPanel (typed details)      |
+----------------------------------------------+
```

- Backend owns the translation from storage-native shapes (Qdrant payload, Neo4j rows) to lean JSON the globe can consume directly.
- Frontend layers follow the established `BillboardCollection` pattern (see `EarthquakeLayer.tsx`).
- Polling intervals: **60 s** for FIRMS, **30 s** for Aircraft.
- Polling pauses when `document.hidden`.
- No WebSockets; the data pipeline is batch-ingestion driven, so real-time push has no value here.

## Backend — FIRMS Router

**New file:** `services/backend/app/routers/firms.py`

### Endpoint

```
GET /firms/hotspots?since_hours=24
```

- `since_hours` is an int query parameter, default 24, max 168 (7 days)
- Reads from the Qdrant client on `app.state`
- Returns `list[FIRMSHotspot]`

### Qdrant query

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

cutoff = int(time.time()) - since_hours * 3600
flt = Filter(must=[
    FieldCondition(key="source", match=MatchValue(value="firms")),
    FieldCondition(key="ingested_epoch", range=Range(gte=cutoff)),
])
points, _ = await qdrant.scroll(
    collection_name="odin_intel",
    scroll_filter=flt,
    limit=2000,
    with_payload=True,
    with_vectors=False,
)
```

`ingested_epoch` is guaranteed on FIRMS payloads (added in the 2026-04-10 correlation sprint).

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
```

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
  5. Redis cache hit short-circuits Qdrant call.

## Backend — Aircraft Router

**New file:** `services/backend/app/routers/aircraft.py`

### Endpoint

```
GET /aircraft/tracks?since_hours=24
```

- `since_hours` default 24, max 72
- Read-only Neo4j session from `app.state.neo4j_driver`
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

- Neo4j driver mocked via `AsyncMock` returning canned records.
- Cases:
  1. Happy path — two aircraft, one with 5 points, one with 1 point, verify ordering (points asc, tracks by newest last-point desc).
  2. Empty result → `[]`.
  3. `since_hours` param translates to correct `$since_epoch`.
  4. Record with null lat/lon is filtered out at the Cypher layer (unit-test the query string contains `IS NOT NULL`).
  5. Redis cache hit short-circuits Neo4j call.

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
        const res = await fetch(`${API_BASE}/firms/hotspots?since_hours=${sinceHours}`);
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
- Material: `PolylineColorAppearance` with per-vertex colors, base RGB from branch palette, alpha interpolated over timestamp — newest segment alpha 1.0, oldest point within window alpha 0.2. Linear fade based on `(timestamp - oldest) / (newest - oldest)`.
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

Same shape as `useFIRMSHotspots`, 30 s interval, `GET /aircraft/tracks?since_hours=24`.

### Tests — `MilAircraftLayer.test.tsx` + `useAircraftTracks.test.ts`

- Unit: `trackToPolylinePositions(points)` returns a flat Cartesian3 array of expected length.
- Unit: alpha-fade helper assigns 1.0 to newest and 0.2 to oldest vertex.
- Unit: `createJetIcon(color)` returns canvas with non-transparent silhouette.
- Component: two mock tracks (5-point, 1-point) → polyline collection length === 1, billboard collection length === 2.
- Hook: fake timers, mocked fetch, 30 s interval.

## Layer Panel — "Ingestion" sub-section

**Modified file:** `services/frontend/src/components/ui/LayerPanel.tsx`

- New section header "INGESTION" with a thin separator above, placed after the existing layer toggles.
- Two new checkboxes: `firmsHotspots`, `milAircraft`. Default **on**.
- Each label shows a live count badge: e.g. `FIRMS Hotspots (187)` and `Mil Aircraft (23)`. Counts derived from the hook data passed down by App.tsx, no extra requests.
- App state:

```tsx
const [layers, setLayers] = useState({
  flights: true,
  satellites: true,
  earthquakes: true,
  // ... existing ...
  firmsHotspots: true,
  milAircraft: true,
});
```

- The `visible` prop on each new layer is wired to `layers.firmsHotspots` / `layers.milAircraft`.

## Info Panel — Click details

**Strategy:** Check for existing `InfoPanel.tsx` first. If present, extend its renderer. If not, create it.

### New or extended file

```
services/frontend/src/components/ui/InfoPanel.tsx
```

- Right-docked fixed panel, 320 px wide, semi-transparent dark background consistent with `LayerPanel`.
- Close button (×) top right.
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
- Link "View on FIRMS Map" opens the FIRMS URL embedded in the point (built by the collector)

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
<InfoPanel selected={selected} onClose={() => setSelected(null)} viewer={viewer} />
```

## Data Flow Summary

```
FIRMSLayer        useFIRMSHotspots    /firms/hotspots        Redis 60s
    ^                  |                    |                   |
    |   60s poll       v                    v                   v
    +- hotspots[] <-- setState <-- JSON <-- Qdrant scroll (source+time)

MilAircraftLayer  useAircraftTracks   /aircraft/tracks       Redis 30s
    ^                  |                    |                   |
    |   30s poll       v                    v                   v
    +- tracks[] <---- setState <-- JSON <-- Neo4j Cypher (since_epoch)
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
- `InfoPanel.test.tsx` — render both variants of the discriminated union.
- Type-check + ESLint clean.

### Manual smoke

1. `./odin.sh up ingestion` — wait for FIRMS + Military Aircraft to write data.
2. Verify Qdrant has `source=firms` points and Neo4j has `SPOTTED_AT` edges with recent `timestamp`.
3. `./odin.sh swap interactive` — start backend + frontend.
4. `curl localhost:8080/firms/hotspots?since_hours=24 | jq length`
5. `curl localhost:8080/aircraft/tracks?since_hours=24 | jq length`
6. Open browser, toggle both layers in the Ingestion sub-panel, verify counts match curl.
7. Click a FIRMS dot → InfoPanel shows thermal anomaly details.
8. Click an aircraft icon → InfoPanel shows track details, "Center on track" flies the camera.
9. Find a `possible_explosion` hotspot (if any) and confirm the pulse ring renders.

## File Inventory

### New

- `services/backend/app/routers/firms.py`
- `services/backend/app/routers/aircraft.py`
- `services/backend/tests/test_firms_router.py`
- `services/backend/tests/test_aircraft_router.py`
- `services/frontend/src/components/layers/FIRMSLayer.tsx`
- `services/frontend/src/components/layers/MilAircraftLayer.tsx`
- `services/frontend/src/components/ui/InfoPanel.tsx` (unless already exists, then extend)
- `services/frontend/src/hooks/useFIRMSHotspots.ts`
- `services/frontend/src/hooks/useAircraftTracks.ts`
- `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx`
- `services/frontend/src/components/layers/__tests__/MilAircraftLayer.test.tsx`
- `services/frontend/src/hooks/__tests__/useFIRMSHotspots.test.ts`
- `services/frontend/src/hooks/__tests__/useAircraftTracks.test.ts`

### Modified

- `services/backend/app/main.py` — register `firms` and `aircraft` routers
- `services/frontend/src/App.tsx` — new state, hooks, layer mounts, InfoPanel wiring
- `services/frontend/src/components/ui/LayerPanel.tsx` — Ingestion sub-section + two toggles with counters
- `services/frontend/src/types/index.ts` (or equivalent) — add `FIRMSHotspot`, `AircraftPoint`, `AircraftTrack`

## Open Verification Steps (before implementation)

- Confirm whether `services/frontend/src/components/ui/InfoPanel.tsx` already exists; if yes, reuse, if no, create.
- Confirm the Qdrant client is exposed on `app.state` under an attribute name the new routers can import (mirror whatever `rag.py` uses).
- Confirm the Neo4j driver is exposed on `app.state` (check `intel.py` / `graph.py`).
- Confirm `ingested_epoch` is present on FIRMS payloads in production Qdrant (was added 2026-04-10; sanity check with a scroll query).

These checks happen during Task 1 of the implementation plan — they may trigger tiny adjustments but will not change the overall design.
