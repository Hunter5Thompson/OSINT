# TASK-108: Submarine Cable Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a submarine cable layer to WorldView showing global undersea fiber optic cables from TeleGeography, with click-to-inspect metadata.

**Architecture:** Backend fetches TeleGeography GeoJSON (live with bundled fallback), caches in Redis for 24h, serves via REST. Frontend renders cables as colored PolylineCollection with landing point markers, label visibility gated by camera altitude via `moveEnd` event.

**Tech Stack:** FastAPI + Pydantic v2 + httpx (backend), React + CesiumJS PolylineCollection (frontend), Redis cache, TeleGeography public GeoJSON API.

**Spec:** `docs/superpowers/specs/2026-04-01-submarine-cable-layer-design.md`

---

### Task 1: Backend Model + Config

**Files:**
- Create: `services/backend/app/models/cable.py`
- Modify: `services/backend/app/config.py:42-51`
- Test: `services/backend/tests/unit/test_cable_service.py`

- [ ] **Step 1: Create cable model**

Create `services/backend/app/models/cable.py`:

```python
"""Submarine cable and landing point data models."""

from pydantic import BaseModel, Field


class SubmarineCable(BaseModel):
    id: str
    name: str
    color: str = "#00bcd4"
    is_planned: bool = False
    owners: str | None = None
    capacity_tbps: float | None = None
    length_km: float | None = None
    rfs: str | None = None
    url: str | None = None
    landing_point_ids: list[str] = Field(default_factory=list)
    coordinates: list[list[list[float]]]  # MultiLineString


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

- [ ] **Step 2: Add cable config fields**

In `services/backend/app/config.py`, add after line 51 (`aisstream_ws_url`):

```python
    cable_geo_url: str = "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json"
    landing_point_geo_url: str = "https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json"
    cable_cache_ttl_s: int = 86400  # 24 hours
```

- [ ] **Step 3: Write model unit test**

Create `services/backend/tests/unit/test_cable_service.py` with the model test only (service tests come in Task 2):

```python
"""Unit tests for submarine cable models and service."""

import pytest
from pydantic import ValidationError

from app.models.cable import CableDataset, LandingPoint, SubmarineCable


class TestSubmarineCableModel:
    def test_minimal_cable(self) -> None:
        cable = SubmarineCable(
            id="abc",
            name="Test Cable",
            coordinates=[[[0.0, 1.0], [2.0, 3.0]]],
        )
        assert cable.id == "abc"
        assert cable.color == "#00bcd4"
        assert cable.is_planned is False
        assert cable.landing_point_ids == []

    def test_full_cable(self) -> None:
        cable = SubmarineCable(
            id="xyz",
            name="Trans-Atlantic",
            color="#ff6600",
            is_planned=True,
            owners="Google, Meta",
            capacity_tbps=400.0,
            length_km=6500.0,
            rfs="2027",
            url="https://example.com",
            landing_point_ids=["lp1", "lp2"],
            coordinates=[[[10.0, 20.0], [30.0, 40.0]], [[50.0, 60.0], [70.0, 80.0]]],
        )
        assert cable.is_planned is True
        assert cable.capacity_tbps == 400.0
        assert len(cable.coordinates) == 2

    def test_cable_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            SubmarineCable(id="x", name="Y")  # type: ignore[call-arg]  # missing coordinates

    def test_landing_point(self) -> None:
        lp = LandingPoint(id="lp1", name="Marseille", country="France", latitude=43.3, longitude=5.4)
        assert lp.country == "France"

    def test_cable_dataset(self) -> None:
        ds = CableDataset(
            cables=[SubmarineCable(id="c1", name="C", coordinates=[[[0, 0], [1, 1]]])],
            landing_points=[LandingPoint(id="lp1", name="LP", latitude=0, longitude=0)],
            source="live",
        )
        assert ds.source == "live"
        assert len(ds.cables) == 1

    def test_mutable_default_isolation(self) -> None:
        a = SubmarineCable(id="a", name="A", coordinates=[[[0, 0], [1, 1]]])
        b = SubmarineCable(id="b", name="B", coordinates=[[[0, 0], [1, 1]]])
        a.landing_point_ids.append("x")
        assert b.landing_point_ids == []
```

- [ ] **Step 4: Run tests**

```bash
cd services/backend && uv run pytest tests/unit/test_cable_service.py::TestSubmarineCableModel -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/models/cable.py services/backend/app/config.py services/backend/tests/unit/test_cable_service.py
git commit -m "feat(backend): add submarine cable model + config fields"
```

---

### Task 2: Backend Service (GeoJSON Parser + Hybrid Fetch)

**Files:**
- Create: `services/backend/app/services/cable_service.py`
- Create: `services/backend/data/submarine-fallback.json`
- Modify: `services/backend/tests/unit/test_cable_service.py`

- [ ] **Step 1: Create fallback data file**

Create directory and minimal fallback:

```bash
mkdir -p services/backend/data
```

Create `services/backend/data/submarine-fallback.json`:

```json
{
  "cables_geojson": { "type": "FeatureCollection", "features": [] },
  "landing_points_geojson": { "type": "FeatureCollection", "features": [] }
}
```

(Raw GeoJSON format — same as the live data. Populated with a real snapshot in Task 9. Empty is a valid fallback — returns 0 cables.)

- [ ] **Step 2: Write the cable service**

Create `services/backend/app/services/cable_service.py`:

```python
"""Submarine cable data service — hybrid fetch with fallback."""

import json
import re
from pathlib import Path

import structlog

from app.config import settings
from app.models.cable import CableDataset, LandingPoint, SubmarineCable
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "submarine:dataset:v1"
FALLBACK_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "submarine-fallback.json"


async def get_cable_dataset(
    proxy: ProxyService,
    cache: CacheService,
) -> CableDataset:
    """Return cable dataset from cache, live fetch, or bundled fallback."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return CableDataset(**cached)

    dataset = await _fetch_live(proxy)
    if dataset is None:
        dataset = _load_fallback()

    await cache.set(CACHE_KEY, dataset.model_dump(mode="json"), settings.cable_cache_ttl_s)
    return dataset


async def _fetch_live(proxy: ProxyService) -> CableDataset | None:
    """Fetch both GeoJSON files from TeleGeography."""
    try:
        # ProxyService has 30s default timeout (>15s spec requirement)
        cable_geojson = await proxy.get_json(settings.cable_geo_url)
        lp_geojson = await proxy.get_json(settings.landing_point_geo_url)

        cables = _parse_cables(cable_geojson)
        landing_points = _parse_landing_points(lp_geojson)

        logger.info("cables_fetched_live", cable_count=len(cables), lp_count=len(landing_points))
        return CableDataset(cables=cables, landing_points=landing_points, source="live")
    except Exception:
        logger.warning("cables_live_fetch_failed")
        return None


def _load_fallback() -> CableDataset:
    """Load bundled fallback JSON (raw GeoJSON format, same as live)."""
    try:
        raw = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
        cables = _parse_cables(raw.get("cables_geojson", {}))
        landing_points = _parse_landing_points(raw.get("landing_points_geojson", {}))
        logger.info("cables_loaded_fallback", cable_count=len(cables), lp_count=len(landing_points))
        return CableDataset(cables=cables, landing_points=landing_points, source="fallback")
    except Exception:
        logger.error("cables_fallback_load_failed")
        return CableDataset(cables=[], landing_points=[], source="fallback")


def _parse_cables(geojson: dict) -> list[SubmarineCable]:
    """Parse TeleGeography cable GeoJSON into model list."""
    cables: list[SubmarineCable] = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        geom_type = geom.get("type")
        coords = geom.get("coordinates")

        if not coords:
            continue

        # Normalize LineString to MultiLineString
        if geom_type == "LineString":
            coords = [coords]
        elif geom_type != "MultiLineString":
            continue

        cables.append(
            SubmarineCable(
                id=str(props.get("id", "")),
                name=props.get("name", "Unknown"),
                color=_parse_color(props.get("color")),
                is_planned=bool(props.get("is_planned", False)),
                owners=props.get("owners"),
                capacity_tbps=_parse_capacity(props.get("capacity")),
                length_km=_parse_length(props.get("length")),
                rfs=str(props.get("rfs")) if props.get("rfs") else None,
                url=props.get("url"),
                landing_point_ids=[str(lp) for lp in props.get("landing_points", [])],
                coordinates=coords,
            )
        )
    return cables


def _parse_landing_points(geojson: dict) -> list[LandingPoint]:
    """Parse TeleGeography landing point GeoJSON into model list."""
    points: list[LandingPoint] = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates")

        if not coords or geom.get("type") != "Point" or len(coords) < 2:
            continue

        points.append(
            LandingPoint(
                id=str(props.get("id", "")),
                name=props.get("name", "Unknown"),
                country=props.get("country"),
                latitude=float(coords[1]),
                longitude=float(coords[0]),
            )
        )
    return points


def _parse_length(raw: object) -> float | None:
    """Parse length string like '1,234 km' or '1234' to float km."""
    if raw is None:
        return None
    text = str(raw).lower().replace(",", "").replace("km", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_capacity(raw: object) -> float | None:
    """Parse capacity to float Tbps. Best-effort."""
    if raw is None:
        return None
    text = str(raw).lower().replace(",", "").replace("tbps", "").replace("tb/s", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _parse_color(raw: object) -> str:
    """Validate hex color, return default on invalid."""
    if raw and isinstance(raw, str) and _HEX_RE.match(raw):
        return raw
    return "#00bcd4"
```

- [ ] **Step 3: Write service tests**

Append to `services/backend/tests/unit/test_cable_service.py`:

```python
import json
from unittest.mock import AsyncMock, patch

from app.services.cable_service import (
    _load_fallback,
    _parse_cables,
    _parse_capacity,
    _parse_color,
    _parse_landing_points,
    _parse_length,
    get_cable_dataset,
)


class TestParsers:
    def test_parse_length_normal(self) -> None:
        assert _parse_length("1234") == 1234.0

    def test_parse_length_with_comma_and_unit(self) -> None:
        assert _parse_length("1,234 km") == 1234.0

    def test_parse_length_none(self) -> None:
        assert _parse_length(None) is None

    def test_parse_length_garbage(self) -> None:
        assert _parse_length("not a number") is None

    def test_parse_capacity_normal(self) -> None:
        assert _parse_capacity("400") == 400.0

    def test_parse_capacity_with_unit(self) -> None:
        assert _parse_capacity("200 Tbps") == 200.0

    def test_parse_capacity_none(self) -> None:
        assert _parse_capacity(None) is None

    def test_parse_color_valid(self) -> None:
        assert _parse_color("#ff6600") == "#ff6600"

    def test_parse_color_invalid(self) -> None:
        assert _parse_color("not-a-color") == "#00bcd4"

    def test_parse_color_none(self) -> None:
        assert _parse_color(None) == "#00bcd4"

    def test_parse_color_short_hex(self) -> None:
        assert _parse_color("#f60") == "#f60"


class TestParseCables:
    def test_multilinestring(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "1", "name": "Test", "color": "#aabbcc"},
                    "geometry": {"type": "MultiLineString", "coordinates": [[[0, 1], [2, 3]]]},
                }
            ]
        }
        cables = _parse_cables(geo)
        assert len(cables) == 1
        assert cables[0].name == "Test"

    def test_linestring_normalized(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "2", "name": "LS"},
                    "geometry": {"type": "LineString", "coordinates": [[0, 1], [2, 3]]},
                }
            ]
        }
        cables = _parse_cables(geo)
        assert len(cables) == 1
        assert cables[0].coordinates == [[[0, 1], [2, 3]]]

    def test_skip_missing_coordinates(self) -> None:
        geo = {"features": [{"properties": {"id": "3", "name": "X"}, "geometry": {"type": "MultiLineString"}}]}
        assert _parse_cables(geo) == []

    def test_skip_unknown_geometry_type(self) -> None:
        geo = {"features": [{"properties": {"id": "4"}, "geometry": {"type": "Polygon", "coordinates": [[[0, 1]]]}}]}
        assert _parse_cables(geo) == []

    def test_is_planned_flag(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "5", "name": "P", "is_planned": True},
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                }
            ]
        }
        assert _parse_cables(geo)[0].is_planned is True


class TestParseLandingPoints:
    def test_valid_point(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "lp1", "name": "Marseille", "country": "France"},
                    "geometry": {"type": "Point", "coordinates": [5.4, 43.3]},
                }
            ]
        }
        pts = _parse_landing_points(geo)
        assert len(pts) == 1
        assert pts[0].latitude == 43.3
        assert pts[0].longitude == 5.4

    def test_skip_non_point(self) -> None:
        geo = {"features": [{"properties": {"id": "x"}, "geometry": {"type": "LineString", "coordinates": [[0, 0]]}}]}
        assert _parse_landing_points(geo) == []


class TestFallback:
    def test_fallback_returns_dataset(self) -> None:
        ds = _load_fallback()
        assert ds.source == "fallback"
        assert isinstance(ds.cables, list)

    def test_fallback_missing_file(self) -> None:
        with patch("app.services.cable_service.FALLBACK_PATH") as mock_path:
            mock_path.read_text.side_effect = FileNotFoundError
            ds = _load_fallback()
            assert ds.source == "fallback"
            assert ds.cables == []

    def test_fallback_parses_raw_geojson(self) -> None:
        raw = json.dumps({
            "cables_geojson": {
                "features": [
                    {"properties": {"id": "1", "name": "FB"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}
                ]
            },
            "landing_points_geojson": {
                "features": [
                    {"properties": {"id": "lp1", "name": "LP"}, "geometry": {"type": "Point", "coordinates": [5.0, 43.0]}}
                ]
            },
        })
        with patch("app.services.cable_service.FALLBACK_PATH") as mock_path:
            mock_path.read_text.return_value = raw
            ds = _load_fallback()
            assert len(ds.cables) == 1
            assert len(ds.landing_points) == 1
            assert ds.cables[0].name == "FB"


class TestGetCableDataset:
    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = {"cables": [], "landing_points": [], "source": "live"}
        proxy = AsyncMock()

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "live"
        proxy.get_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_live_fetch(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        proxy = AsyncMock()
        proxy.get_json.side_effect = [
            {"features": [{"properties": {"id": "1", "name": "C"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]},
            {"features": []},
        ]

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "live"
        assert len(ds.cables) == 1
        cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_live_fails_uses_fallback(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        proxy = AsyncMock()
        proxy.get_json.side_effect = Exception("network error")

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "fallback"
```

- [ ] **Step 4: Run all cable tests**

```bash
cd services/backend && uv run pytest tests/unit/test_cable_service.py -v
```

Expected: all passed (~20 tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/services/cable_service.py services/backend/data/submarine-fallback.json services/backend/tests/unit/test_cable_service.py
git commit -m "feat(backend): add cable service with hybrid fetch + GeoJSON parser"
```

---

### Task 3: Backend Router + Registration + Contract Test

**Files:**
- Create: `services/backend/app/routers/cables.py`
- Create: `services/backend/tests/unit/test_cables_router.py`
- Modify: `services/backend/app/main.py:14,67-74`

- [ ] **Step 1: Create cables router**

Create `services/backend/app/routers/cables.py`:

```python
"""Submarine cable data endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.cable import CableDataset
from app.models.intel import APIError
from app.services import cable_service

router = APIRouter(prefix="/cables", tags=["cables"])


@router.get("", response_model=CableDataset)
async def get_cables(request: Request) -> CableDataset | JSONResponse:
    try:
        return await cable_service.get_cable_dataset(
            request.app.state.proxy,
            request.app.state.cache,
        )
    except Exception:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Cable data unavailable",
                detail="Failed to load submarine cable data",
                code="CABLE_FETCH_ERROR",
                timestamp=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        )
```

- [ ] **Step 2: Register router in main.py**

In `services/backend/app/main.py`, add `cables` to the import on line 14:

```python
from app.routers import cables, earthquakes, flights, graph, hotspots, intel, rag, satellites, vessels
```

Add after line 74 (after graph router):

```python
app.include_router(cables.router, prefix="/api/v1")
```

Update the `client_config` endpoint `default_layers` dict (around line 107-114) to include cables:

```python
        default_layers={
            "flights": True,
            "satellites": True,
            "earthquakes": True,
            "vessels": False,
            "cctv": False,
            "events": False,
            "cables": False,
        },
```

- [ ] **Step 3: Write router contract test**

Create `services/backend/tests/unit/test_cables_router.py`:

```python
"""Contract tests for /api/v1/cables endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.cable import CableDataset, LandingPoint, SubmarineCable


@pytest.fixture
def mock_cable_dataset() -> CableDataset:
    return CableDataset(
        cables=[
            SubmarineCable(
                id="1",
                name="Test Cable",
                color="#ff6600",
                coordinates=[[[0.0, 1.0], [2.0, 3.0]]],
                landing_point_ids=["lp1"],
            )
        ],
        landing_points=[
            LandingPoint(id="lp1", name="Marseille", country="France", latitude=43.3, longitude=5.4)
        ],
        source="live",
    )


class TestCablesRouter:
    @pytest.mark.asyncio
    async def test_get_cables_returns_200(self, mock_cable_dataset: CableDataset) -> None:
        with patch("app.services.cable_service.get_cable_dataset", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = mock_cable_dataset
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/cables")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_cables_response_shape(self, mock_cable_dataset: CableDataset) -> None:
        with patch("app.services.cable_service.get_cable_dataset", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = mock_cable_dataset
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/cables")
            body = resp.json()
            assert "cables" in body
            assert "landing_points" in body
            assert "source" in body
            assert isinstance(body["cables"], list)
            assert body["cables"][0]["name"] == "Test Cable"
            assert body["source"] == "live"

    @pytest.mark.asyncio
    async def test_get_cables_502_on_error(self) -> None:
        with patch("app.services.cable_service.get_cable_dataset", new_callable=AsyncMock) as mock_fn:
            mock_fn.side_effect = Exception("boom")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/cables")
            assert resp.status_code == 502
```

- [ ] **Step 4: Run full backend test suite**

```bash
cd services/backend && uv run pytest -v
```

Expected: all tests pass (existing + new cable + router tests).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/cables.py services/backend/tests/unit/test_cables_router.py services/backend/app/main.py
git commit -m "feat(backend): add /api/v1/cables endpoint with contract tests"
```

---

### Task 4: Frontend Types + API

**Files:**
- Modify: `services/frontend/src/types/index.ts:93-125`
- Modify: `services/frontend/src/services/api.ts:6-17,49-51`

- [ ] **Step 1: Add TypeScript types**

In `services/frontend/src/types/index.ts`, add after the `IntelEvent` interface (after line 92):

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
  coordinates: number[][][];
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

Add `cables: boolean;` to `LayerVisibility` (after line 107, the `events` entry):

```typescript
  cables: boolean;
```

Add `cables: Date | null;` to `DataFreshness` (after line 123, the `events` entry):

```typescript
  cables: Date | null;
```

- [ ] **Step 2: Add API function**

In `services/frontend/src/services/api.ts`, add `CableDataset` to the import block (line 6-17):

```typescript
import type {
  Aircraft,
  CableDataset,
  ClientConfig,
  Earthquake,
  GeoEventsResponse,
  Hotspot,
  IntelAnalysis,
  IntelEvent,
  IntelQuery,
  Satellite,
  Vessel,
} from "../types";
```

Add after `getVessels` (after line 51):

```typescript
export async function getCables(): Promise<CableDataset> {
  return fetchJSON<CableDataset>("/cables");
}
```

- [ ] **Step 3: Run frontend type check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/types/index.ts services/frontend/src/services/api.ts
git commit -m "feat(frontend): add submarine cable types + API client"
```

---

### Task 5: Frontend Hook

**Files:**
- Create: `services/frontend/src/hooks/useCables.ts`

- [ ] **Step 1: Create useCables hook**

Create `services/frontend/src/hooks/useCables.ts`:

```typescript
import { useState, useEffect, useRef, useCallback } from "react";
import type { SubmarineCable, LandingPoint } from "../types";
import { getCables } from "../services/api";

const POLL_INTERVAL = 3_600_000; // 1 hour — cable data rarely changes

export function useCables(enabled: boolean) {
  const [cables, setCables] = useState<SubmarineCable[]>([]);
  const [landingPoints, setLandingPoints] = useState<LandingPoint[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await getCables();
      setCables(data.cables);
      setLandingPoints(data.landing_points);
      setSource(data.source);
      setLastUpdate(new Date());
    } catch {
      // keep stale data on error
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setCables([]);
      setLandingPoints([]);
      setSource(null);
      return;
    }

    void fetchData();
    timerRef.current = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, fetchData]);

  return { cables, landingPoints, source, loading, lastUpdate };
}
```

- [ ] **Step 2: Type check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/hooks/useCables.ts
git commit -m "feat(frontend): add useCables hook with 1h polling"
```

---

### Task 6: Frontend CableLayer Component

**Files:**
- Create: `services/frontend/src/components/layers/CableLayer.tsx`

- [ ] **Step 1: Create CableLayer**

Create `services/frontend/src/components/layers/CableLayer.tsx`:

```typescript
import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { SubmarineCable, LandingPoint } from "../../types";

interface CableLayerProps {
  viewer: Cesium.Viewer | null;
  cables: SubmarineCable[];
  landingPoints: LandingPoint[];
  visible: boolean;
}

const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

export function CableLayer({ viewer, cables, landingPoints, visible }: CableLayerProps) {
  const polylineCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const labelsVisibleRef = useRef(false);

  // Setup/teardown collections
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!polylineCollectionRef.current) {
      polylineCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(polylineCollectionRef.current);
    }
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }

    return () => {
      if (polylineCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(polylineCollectionRef.current);
        polylineCollectionRef.current = null;
      }
      if (billboardCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(billboardCollectionRef.current);
        billboardCollectionRef.current = null;
      }
      if (labelCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(labelCollectionRef.current);
        labelCollectionRef.current = null;
      }
    };
  }, [viewer]);

  // Camera-based label visibility (moveEnd, not per-frame)
  const updateLabelVisibility = useCallback(() => {
    const lc = labelCollectionRef.current;
    if (!lc || !viewer || viewer.isDestroyed()) return;

    const carto = viewer.camera.positionCartographic;
    const shouldShow = carto.height < LABEL_ALTITUDE_THRESHOLD;

    if (shouldShow !== labelsVisibleRef.current) {
      labelsVisibleRef.current = shouldShow;
      lc.show = shouldShow && visible;
    }
  }, [viewer, visible]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const removeListener = viewer.camera.moveEnd.addEventListener(updateLabelVisibility);
    return () => removeListener();
  }, [viewer, updateLabelVisibility]);

  // Render cables + landing points
  useEffect(() => {
    const pc = polylineCollectionRef.current;
    const bc = billboardCollectionRef.current;
    const lc = labelCollectionRef.current;
    if (!pc || !bc || !lc) return;

    pc.removeAll();
    bc.removeAll();
    lc.removeAll();

    pc.show = visible;
    bc.show = visible;
    // Label visibility managed by camera listener
    lc.show = visible && labelsVisibleRef.current;

    if (!visible) return;

    // Draw cables
    for (const cable of cables) {
      const alpha = cable.is_planned ? 0.3 : 0.8;
      const width = cable.is_planned ? 1.5 : 2.0;
      const cableColor = hexToCesiumColor(cable.color, alpha);

      for (const segment of cable.coordinates) {
        if (segment.length < 2) continue;

        const positions = segment.map(([lon, lat]) =>
          Cesium.Cartesian3.fromDegrees(lon, lat, 0),
        );

        pc.add({
          positions,
          width,
          material: Cesium.Material.fromType("Color", { color: cableColor }),
        });
      }

      // Midpoint billboard for click handling (first segment)
      const firstSeg = cable.coordinates[0];
      if (firstSeg && firstSeg.length >= 2) {
        const midIdx = Math.floor(firstSeg.length / 2);
        const [midLon, midLat] = firstSeg[midIdx];
        const midPos = Cesium.Cartesian3.fromDegrees(midLon, midLat, 0);

        const billboard = bc.add({
          position: midPos,
          image: createCableDotCanvas(cable.color),
          scale: 0.4,
          eyeOffset: new Cesium.Cartesian3(0, 0, -50),
        });
        // Resolve landing point names for click panel
        const lpNames = cable.landing_point_ids
          .map((lpId) => landingPoints.find((lp) => lp.id === lpId)?.name)
          .filter((n): n is string => n != null);

        (billboard as unknown as Record<string, unknown>)._cableData = {
          id: cable.id,
          name: cable.name,
          owners: cable.owners,
          capacity_tbps: cable.capacity_tbps,
          length_km: cable.length_km,
          rfs: cable.rfs,
          is_planned: cable.is_planned,
          url: cable.url,
          landing_points: lpNames,
          lat: midLat,
          lon: midLon,
        };

        // Label at midpoint
        lc.add({
          position: midPos,
          text: cable.name.length > 25 ? cable.name.substring(0, 22) + "..." : cable.name,
          font: "10px monospace",
          fillColor: cableColor,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -12),
          eyeOffset: new Cesium.Cartesian3(0, 0, -50),
        });
      }
    }

    // Draw landing points
    for (const lp of landingPoints) {
      bc.add({
        position: Cesium.Cartesian3.fromDegrees(lp.longitude, lp.latitude, 0),
        image: createLandingPointCanvas(),
        scale: 0.3,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
      });
    }
  }, [cables, landingPoints, visible]);

  return null;
}

function hexToCesiumColor(hex: string, alpha: number): Cesium.Color {
  try {
    const c = Cesium.Color.fromCssColorString(hex);
    return c.withAlpha(alpha);
  } catch {
    return Cesium.Color.CYAN.withAlpha(alpha);
  }
}

const cableDotCache = new Map<string, string>();

function createCableDotCanvas(color: string): string {
  const cached = cableDotCache.get(color);
  if (cached) return cached;

  const size = 12;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }
  const dataUrl = canvas.toDataURL();
  cableDotCache.set(color, dataUrl);
  return dataUrl;
}

let landingPointDataUrl: string | null = null;

function createLandingPointCanvas(): string {
  if (landingPointDataUrl) return landingPointDataUrl;

  const size = 10;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
    ctx.fillStyle = "#ffd600";
    ctx.fill();
  }
  landingPointDataUrl = canvas.toDataURL();
  return landingPointDataUrl;
}
```

- [ ] **Step 2: Type check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/layers/CableLayer.tsx
git commit -m "feat(frontend): add CableLayer with PolylineCollection + click data"
```

---

### Task 7: EntityClickHandler — Cable Support

**Files:**
- Modify: `services/frontend/src/components/globe/EntityClickHandler.tsx:27-44`

- [ ] **Step 1: Add cable click detection**

In `services/frontend/src/components/globe/EntityClickHandler.tsx`, add a new guard block after the `_eventData` guard (after line 44, before the `// Guard 2` comment):

```typescript
      // Guard 2: Cable billboard (custom _cableData property)
      const cableData = (picked?.primitive as Record<string, unknown>)?._cableData as
        | {
            id: string;
            name: string;
            owners: string | null;
            capacity_tbps: number | null;
            length_km: number | null;
            rfs: string | null;
            is_planned: boolean;
            url: string | null;
            landing_points: string[];
            lat: number;
            lon: number;
          }
        | undefined;

      if (cableData) {
        const props: Record<string, string> = {};
        if (cableData.owners) props.owners = cableData.owners;
        if (cableData.capacity_tbps != null) props.capacity = `${cableData.capacity_tbps} Tbps`;
        if (cableData.length_km != null) props.length = `${Math.round(cableData.length_km).toLocaleString()} km`;
        if (cableData.rfs) props.rfs = cableData.rfs;
        props.status = cableData.is_planned ? "PLANNED" : "ACTIVE";
        if (cableData.landing_points.length > 0) props.landings = cableData.landing_points.join(", ");
        if (cableData.url) props.info = cableData.url;

        setSelected({
          id: cableData.id,
          name: cableData.name,
          type: "submarine_cable",
          position: { lat: cableData.lat, lon: cableData.lon },
          properties: props,
        });
        return;
      }
```

Rename the existing `// Guard 2` comment to `// Guard 3`:

```typescript
      // Guard 3: Existing Cesium Entity logic
```

- [ ] **Step 2: Type check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/globe/EntityClickHandler.tsx
git commit -m "feat(frontend): add cable click detection to EntityClickHandler"
```

---

### Task 8: App + UI Integration

**Files:**
- Modify: `services/frontend/src/App.tsx:1-168`
- Modify: `services/frontend/src/components/ui/OperationsPanel.tsx:16`
- Modify: `services/frontend/src/components/ui/StatusBar.tsx:4-86`

- [ ] **Step 1: Wire hook + layer into App.tsx**

In `services/frontend/src/App.tsx`:

Add import after line 10 (after EventLayer import):

```typescript
import { CableLayer } from "./components/layers/CableLayer";
```

Add import after line 19 (after useEvents import):

```typescript
import { useCables } from "./hooks/useCables";
```

Update the initial `layers` state (line 29-36) to include cables:

```typescript
  const [layers, setLayers] = useState<LayerVisibility>({
    flights: true,
    satellites: true,
    earthquakes: true,
    vessels: false,
    cctv: false,
    events: false,
    cables: false,
  });
```

Add hook call after line 43 (after useEvents):

```typescript
  const { cables, landingPoints, lastUpdate: cablesUpdate } = useCables(layers.cables);
```

Update `default_layers` in the config fallback (line 56):

```typescript
          default_layers: { flights: true, satellites: true, earthquakes: true, vessels: false, cctv: false, events: false, cables: false },
```

Add `<CableLayer>` after `<EventLayer>` (after line 128):

```typescript
      <CableLayer viewer={viewer} cables={cables} landingPoints={landingPoints} visible={layers.cables} />
```

Update `<StatusBar>` freshness prop (line 152-159) to include cables:

```typescript
        freshness={{
          flights: flightsUpdate,
          satellites: satellitesUpdate,
          earthquakes: earthquakesUpdate,
          vessels: vesselsUpdate,
          events: eventsUpdate,
          cables: cablesUpdate,
        }}
```

Add `cableCount` prop after `eventCount` (after line 164):

```typescript
        cableCount={cables.length}
```

- [ ] **Step 2: Add CABLES toggle to OperationsPanel**

In `services/frontend/src/components/ui/OperationsPanel.tsx`, add after line 16 (after events entry):

```typescript
  { key: "cables", label: "CABLES", icon: "#" },
```

- [ ] **Step 3: Update StatusBar**

In `services/frontend/src/components/ui/StatusBar.tsx`:

Add `cableCount` to the interface (after line 10, after `eventCount`):

```typescript
  cableCount: number;
```

Add `cableCount` to the destructured props (after line 27, after `eventCount`):

```typescript
  cableCount,
```

Add cables display after the EVENTS span (after line 74):

```typescript
        <span>
          CABLES <span className="text-green-300">{cableCount}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.cables)}]</span>
        </span>
```

- [ ] **Step 4: Type check + lint**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/App.tsx services/frontend/src/components/ui/OperationsPanel.tsx services/frontend/src/components/ui/StatusBar.tsx
git commit -m "feat(frontend): integrate cable layer into App + UI panels"
```

---

### Task 9: Full Test Suite + Populate Fallback

**Files:**
- Modify: `services/backend/data/submarine-fallback.json`

- [ ] **Step 1: Run full backend tests**

```bash
cd services/backend && uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend type check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Populate fallback with real data**

Fetch a real snapshot to serve as fallback data:

```bash
cd services/backend && python -c "
import json, urllib.request

cables_url = 'https://www.submarinecablemap.com/api/v3/cable/cable-geo.json'
lp_url = 'https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json'

with urllib.request.urlopen(cables_url, timeout=30) as r:
    cables_geo = json.loads(r.read())
with urllib.request.urlopen(lp_url, timeout=30) as r:
    lp_geo = json.loads(r.read())

# Minimal transform: just store raw features for the parser
fallback = {
    'cables_geojson': cables_geo,
    'landing_points_geojson': lp_geo
}
with open('data/submarine-fallback.json', 'w') as f:
    json.dump(fallback, f, separators=(',', ':'))
print(f'Saved: {len(cables_geo.get(\"features\",[]))} cables, {len(lp_geo.get(\"features\",[]))} landing points')
"
```

- [ ] **Step 4: Re-run backend tests**

```bash
cd services/backend && uv run pytest tests/unit/test_cable_service.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/backend/data/submarine-fallback.json
git commit -m "feat(backend): populate submarine cable fallback data"
```

---
