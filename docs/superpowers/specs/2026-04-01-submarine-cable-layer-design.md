# TASK-108: Submarine Cable Layer — Design Spec

**Date:** 2026-04-01
**Status:** Approved
**Effort:** 1-2 days
**Blocked by:** Nothing
**Blocks:** Nothing

---

## Overview

Add a submarine cable layer to WorldView showing the global undersea fiber optic cable network. Data sourced from TeleGeography's public GeoJSON dataset, with bundled fallback for offline/failure scenarios. Cables rendered as colored polylines with landing point markers. Click interaction shows cable metadata (name, owners, capacity, length, status).

## Data Source

**Primary:** TeleGeography GitHub — live fetch
- Cables: `https://www.submarinecablemap.com/api/v3/cable/cable-geo.json`
- Landing Points: `https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json`

**Fallback:** Bundled file `services/backend/data/submarine-fallback.json` containing both cables and landing points in a single JSON structure:
```json
{
  "cables": [ ... ],
  "landing_points": [ ... ]
}
```

**Hybrid Strategy:**
1. Check Redis cache: `submarine:dataset:v1` (24h TTL)
2. Cache hit: return immediately
3. Cache miss: fetch both GeoJSONs from GitHub (timeout 15s)
4. Fetch failure: load `services/backend/data/submarine-fallback.json` from disk
5. Cache write + return with `source: "live" | "fallback"` flag

Both cables and landing points are cached together under a single key to prevent mixed states.

## Backend

### Models — `services/backend/app/models/cable.py`

```python
class SubmarineCable(BaseModel):
    id: str
    name: str
    color: str = "#00bcd4"           # TeleGeography hex color, fallback cyan
    is_planned: bool = False
    owners: str | None = None
    capacity_tbps: float | None = None
    length_km: float | None = None
    rfs: str | None = None           # Ready-for-service year
    url: str | None = None
    landing_point_ids: list[str] = Field(default_factory=list)
    coordinates: list[list[list[float]]]  # MultiLineString: [[[lon,lat], ...], ...]

class LandingPoint(BaseModel):
    id: str
    name: str
    country: str | None = None
    latitude: float
    longitude: float

class CableDataset(BaseModel):
    cables: list[SubmarineCable]
    landing_points: list[LandingPoint]
    source: str  # "live" | "fallback"
```

### Service — `services/backend/app/services/cable_service.py`

**GeoJSON Parsing (defensive):**
- `LineString` geometry: wrap into `MultiLineString` (`[coordinates]`)
- `length_km`: string normalization (`"1,234 km"` -> `1234.0`, parse failures -> `None`)
- `color`: validate hex format, invalid -> default `#00bcd4`
- Features without coordinates: skip with warning log
- `capacity_tbps`: parse from `capacity` field if present, normalize string -> float, failures -> `None`

**Function signature:**
```python
async def get_cable_dataset(
    proxy: ProxyService,
    cache: CacheService,
) -> CableDataset:
```

### Router — `services/backend/app/routers/cables.py`

```
GET /api/v1/cables -> CableDataset
```

Single endpoint returning cables + landing points + source flag.

### Config additions — `services/backend/app/config.py`

```python
cable_geo_url: str = "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json"
landing_point_geo_url: str = "https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json"
cable_cache_ttl_s: int = 86400  # 24 hours
```

### Registration — `services/backend/app/main.py`

```python
from app.routers import cables
app.include_router(cables.router, prefix="/api/v1")
```

### Fallback file — `services/backend/data/submarine-fallback.json`

Complete snapshot of both datasets. Created once by fetching from GitHub and saved. Structure matches `CableDataset` serialization (cables + landing_points arrays).

## Frontend

### Types — `services/frontend/src/types/index.ts`

Add interfaces:
```typescript
export interface SubmarineCable {
  id: string;
  name: string;
  color: string;
  is_planned: boolean;
  owners: string | null;
  capacity_tbps: number | null;
  length_km: number | null;
  rfs: string | null;
  url: string | null;
  landing_point_ids: string[];
  coordinates: number[][][];  // MultiLineString
}

export interface LandingPoint {
  id: string;
  name: string;
  country: string | null;
  latitude: number;
  longitude: number;
}

export interface CableDataset {
  cables: SubmarineCable[];
  landing_points: LandingPoint[];
  source: string;
}
```

Update `LayerVisibility`:
```typescript
export interface LayerVisibility {
  flights: boolean;
  satellites: boolean;
  earthquakes: boolean;
  vessels: boolean;
  cctv: boolean;
  events: boolean;
  cables: boolean;       // NEW
}
```

Update `DataFreshness`:
```typescript
export interface DataFreshness {
  flights: Date | null;
  satellites: Date | null;
  earthquakes: Date | null;
  vessels: Date | null;
  events: Date | null;
  cables: Date | null;    // NEW
}
```

### API — `services/frontend/src/services/api.ts`

```typescript
export async function getCables(): Promise<CableDataset> {
  return fetchJSON<CableDataset>("/cables");
}
```

### Hook — `services/frontend/src/hooks/useCables.ts`

- Fetch once on mount, re-fetch every 1 hour (3_600_000ms)
- Returns `{ cables, landingPoints, source, loading, lastUpdate }`
- Follows existing hook pattern (useFlights/useEarthquakes)

### Layer — `services/frontend/src/components/layers/CableLayer.tsx`

**Props:** `viewer`, `cables: SubmarineCable[]`, `landingPoints: LandingPoint[]`, `visible: boolean`

**Primitives:**
- `PolylineCollection` for cable lines
- `BillboardCollection` for landing point dots
- `LabelCollection` for cable names at midpoint

**Color scheme:**

| Status | Color | Width | Alpha |
|--------|-------|-------|-------|
| Active cable | TeleGeography hex color | 2.0 | 0.8 |
| Planned cable | TeleGeography hex color | 1.5 | 0.3 |
| Landing point | #ffd600 (yellow) | — | 0.9 |

**Label visibility:** Based on camera height, toggled on `camera.moveEnd` event (not per-frame). Labels visible when camera altitude < 5,000,000m. This avoids per-frame computation and prevents label spam at globe-level zoom.

**Click handling:** Midpoint billboard per cable with `_cableData` property (same pattern as `_eventData` in EventLayer). `EntityClickHandler.tsx` must be extended to detect `_cableData` alongside `_eventData` and render a cable-specific info panel showing: name, owners, capacity, length, RFS year, landing point names, active/planned status, and TeleGeography link.

### App integration — `services/frontend/src/App.tsx`

- Add `cables: false` to initial `layers` state
- Add `useCables` hook
- Render `<CableLayer viewer={viewer} cables={cables} landingPoints={landingPoints} visible={layers.cables} />`
- Wire freshness + count to StatusBar

### OperationsPanel — `services/frontend/src/components/ui/OperationsPanel.tsx`

Add to `LAYER_CONFIG`:
```typescript
{ key: "cables", label: "CABLES", icon: "#" },
```

## Testing

### Backend — `services/backend/tests/unit/`

**test_cable_service.py:**
- GeoJSON parsing: valid MultiLineString
- GeoJSON parsing: LineString normalized to MultiLineString
- `length_km` parsing: `"1,234 km"` -> `1234.0`
- `length_km` parsing: invalid string -> `None`
- `color` parsing: invalid hex -> default `#00bcd4`
- Feature without coordinates: skipped
- Cache hit returns cached data (no fetch)
- Cache miss triggers fetch + cache write
- Live fetch failure: fallback.json loaded
- Invalid/empty fallback file: returns empty dataset, no crash
- `source` field: `"live"` when fetched, `"fallback"` when from disk

**test_cables_router.py:**
- `GET /api/v1/cables` returns 200
- Response shape matches `CableDataset` (cables array, landing_points array, source string)

### Frontend
- `tsc --noEmit` covers type integration (LayerVisibility, Props, Hook return types)

## Files Changed / Created

**New files (7):**
1. `services/backend/app/models/cable.py`
2. `services/backend/app/services/cable_service.py`
3. `services/backend/app/routers/cables.py`
4. `services/backend/data/submarine-fallback.json`
5. `services/backend/tests/unit/test_cable_service.py`
6. `services/frontend/src/hooks/useCables.ts`
7. `services/frontend/src/components/layers/CableLayer.tsx`

**Modified files (8):**
1. `services/backend/app/config.py` — cable URLs + TTL
2. `services/backend/app/main.py` — register cables router
3. `services/frontend/src/types/index.ts` — SubmarineCable, LandingPoint, CableDataset, LayerVisibility, DataFreshness
4. `services/frontend/src/services/api.ts` — getCables()
5. `services/frontend/src/App.tsx` — hook + layer + state
6. `services/frontend/src/components/ui/OperationsPanel.tsx` — CABLES toggle
7. `services/frontend/src/components/ui/StatusBar.tsx` — cable count + freshness
8. `services/frontend/src/components/globe/EntityClickHandler.tsx` — detect `_cableData` + render cable info panel

**Total:** 7 new, 8 modified = 15 files
