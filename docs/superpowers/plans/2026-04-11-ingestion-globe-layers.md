# Ingestion Globe Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface FIRMS thermal anomalies and Military Aircraft tracks from the Hugin P0 ingestion pipeline onto the CesiumJS globe with click-for-details.

**Architecture:** Two new read-only backend routers (`/api/v1/firms/hotspots`, `/api/v1/aircraft/tracks`) translate Qdrant scroll results and Neo4j Cypher rows into lean JSON. Two new frontend layers render the data via `BillboardCollection` + `PolylineCollection`, polled at 60 s / 30 s respectively. A bottom-left `SelectionPanel` shows click details.

**Tech Stack:** FastAPI + Pydantic v2, qdrant-client async, neo4j async driver, React 19, CesiumJS Billboards/Polylines, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-04-11-ingestion-globe-layers-design.md`

---

## Phase A — Backend infrastructure

### Task 1: Add qdrant-client dependency and lazy client getter

**Files:**
- Modify: `services/backend/pyproject.toml`
- Create: `services/backend/app/services/qdrant_client.py`
- Create: `services/backend/tests/unit/test_qdrant_client.py`

- [ ] **Step 1: Add dep to pyproject.toml**

In `services/backend/pyproject.toml`, append `qdrant-client>=1.13` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.128.0",
    "uvicorn[standard]>=0.34.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "httpx>=0.28.0",
    "redis[hiredis]>=5.0",
    "structlog>=25.0",
    "sse-starlette>=2.0",
    "neo4j>=5.0",
    "websockets>=13.0",
    "qdrant-client>=1.13",
]
```

- [ ] **Step 2: Install the new dep**

Run: `cd services/backend && uv sync`
Expected: `qdrant-client` resolves and installs.

- [ ] **Step 3: Write failing test for get_qdrant_client singleton**

Create `services/backend/tests/unit/test_qdrant_client.py`:

```python
"""Tests for the lazy Qdrant client getter."""

from unittest.mock import patch

import pytest

from app.services import qdrant_client as qc


@pytest.mark.asyncio
async def test_get_qdrant_client_returns_singleton() -> None:
    """Second call returns the same instance — module-level cache."""
    qc._client = None  # reset module state
    with patch("app.services.qdrant_client.AsyncQdrantClient") as mock_cls:
        mock_cls.return_value = object()
        first = await qc.get_qdrant_client()
        second = await qc.get_qdrant_client()
        assert first is second
        assert mock_cls.call_count == 1
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_qdrant_client.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.qdrant_client'`

- [ ] **Step 5: Write minimal implementation**

Create `services/backend/app/services/qdrant_client.py`:

```python
"""Lazy async Qdrant client singleton."""

from qdrant_client import AsyncQdrantClient

from app.config import settings

_client: AsyncQdrantClient | None = None


async def get_qdrant_client() -> AsyncQdrantClient:
    """Return a module-cached async Qdrant client."""
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_qdrant_client.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add services/backend/pyproject.toml services/backend/uv.lock \
        services/backend/app/services/qdrant_client.py \
        services/backend/tests/unit/test_qdrant_client.py
git commit -m "feat(backend): add lazy async Qdrant client singleton"
```

---

### Task 2: Extract Neo4j _read_query helper into a shared service module

**Files:**
- Create: `services/backend/app/services/neo4j_client.py`
- Modify: `services/backend/app/routers/graph.py` (import from new module, delete local helpers)
- Create: `services/backend/tests/unit/test_neo4j_client.py`

- [ ] **Step 1: Write failing test for read_query**

Create `services/backend/tests/unit/test_neo4j_client.py`:

```python
"""Tests for the extracted Neo4j read helper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import neo4j_client as nc


@pytest.mark.asyncio
async def test_read_query_uses_read_access_session() -> None:
    mock_session = MagicMock()
    mock_session.run = AsyncMock(return_value=_async_iter([{"name": "alpha"}]))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)

    with patch.object(nc, "get_graph_client", AsyncMock(return_value=mock_driver)):
        rows = await nc.read_query("MATCH (n) RETURN n", {})
        assert rows == [{"name": "alpha"}]
        mock_driver.session.assert_called_once()


def _async_iter(items):
    class _Result:
        def __aiter__(self):
            self._items = iter(items)
            return self

        async def __anext__(self):
            try:
                return _Record(next(self._items))
            except StopIteration:
                raise StopAsyncIteration

    return _Result()


class _Record(dict):
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_neo4j_client.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.neo4j_client'`

- [ ] **Step 3: Create the neo4j_client service module**

Create `services/backend/app/services/neo4j_client.py`:

```python
"""Shared Neo4j async driver + read-only query helper."""

from typing import Any

import neo4j
from neo4j import AsyncGraphDatabase

from app.config import settings

_driver: neo4j.AsyncDriver | None = None


async def get_graph_client() -> neo4j.AsyncDriver:
    """Lazy-init async Neo4j driver."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_url,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def read_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute a read-only Cypher query."""
    driver = await get_graph_client()
    async with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
        result = await session.run(cypher, params)
        return [dict(record) async for record in result]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_neo4j_client.py -v`
Expected: PASS

- [ ] **Step 5: Refactor graph.py to import from shared module**

In `services/backend/app/routers/graph.py`, delete the local `_driver`, `_get_graph_client`, and `_read_query` definitions (lines ~21-37). Replace with:

```python
from app.services.neo4j_client import read_query as _read_query
```

The local alias `_read_query` keeps the rest of `graph.py` unchanged (all the router functions already call `_read_query(...)`). Also delete the now-unused top-level imports in `graph.py`: `neo4j` and `AsyncGraphDatabase`, plus the module-level `_driver = None` line.

- [ ] **Step 6: Run existing graph router tests to confirm no regression**

Run: `cd services/backend && uv run pytest tests/unit/test_graph_router.py -v`
Expected: PASS (same as before — pure refactor)

- [ ] **Step 7: Commit**

```bash
git add services/backend/app/services/neo4j_client.py \
        services/backend/app/routers/graph.py \
        services/backend/tests/unit/test_neo4j_client.py
git commit -m "refactor(backend): extract Neo4j _read_query into shared service module"
```

---

## Phase B — Backend FIRMS router

### Task 3: FIRMS router — happy path

**Files:**
- Create: `services/backend/app/routers/firms.py`
- Create: `services/backend/tests/unit/test_firms_router.py`
- Modify: `services/backend/app/main.py`

- [ ] **Step 1: Write failing test for happy-path scroll + response shape**

Create `services/backend/tests/unit/test_firms_router.py`:

```python
"""Tests for the FIRMS hotspots router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_point(pid: str, lat: float, lon: float, frp: float, explosion: bool = False) -> object:
    class P:
        id = pid
        payload = {
            "source": "firms",
            "latitude": lat,
            "longitude": lon,
            "frp": frp,
            "brightness": 390.0,
            "confidence": "h",
            "acq_date": "2026-04-11",
            "acq_time": "1423",
            "satellite": "VIIRS_SNPP_NRT",
            "bbox_name": "ukraine",
            "possible_explosion": explosion,
            "ingested_epoch": 1744300000.0,
        }

    return P()


@pytest.mark.asyncio
async def test_firms_hotspots_happy_path() -> None:
    """Three Qdrant points → three JSON hotspots with all fields mapped."""
    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.return_value = (
        [
            _make_point("id-a", 48.1, 37.8, 92.0, explosion=True),
            _make_point("id-b", 48.2, 37.9, 45.0),
            _make_point("id-c", 31.4, 34.4, 12.0),
        ],
        None,
    )

    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/firms/hotspots")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert body[0]["id"] == "id-a"
    assert body[0]["possible_explosion"] is True
    assert body[0]["frp"] == 92.0
    assert body[0]["firms_map_url"].startswith("https://firms.modaps.eosdis.nasa.gov/map/#")
    assert "48.1000" in body[0]["firms_map_url"]
    assert "37.8000" in body[0]["firms_map_url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_firms_router.py::test_firms_hotspots_happy_path -v`
Expected: FAIL — router not yet mounted (404).

- [ ] **Step 3: Create firms.py router**

Create `services/backend/app/routers/firms.py`:

```python
"""FIRMS thermal anomalies — serves Qdrant-stored hotspots for globe rendering."""

from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

from app.config import settings
from app.services.qdrant_client import get_qdrant_client

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/firms", tags=["firms"])

_PAGE_SIZE = 512
_MAX_TOTAL = 5000
_CACHE_TTL_S = 60


class FIRMSHotspot(BaseModel):
    id: str
    latitude: float
    longitude: float
    frp: float
    brightness: float
    confidence: str
    acq_date: str
    acq_time: str
    satellite: str
    bbox_name: str
    possible_explosion: bool
    firms_map_url: str


def _build_map_url(acq_date: str, lat: float, lon: float) -> str:
    return (
        "https://firms.modaps.eosdis.nasa.gov/map/#d:"
        f"{acq_date};@{lon:.4f},{lat:.4f},10z"
    )


def _point_to_hotspot(point: Any) -> FIRMSHotspot | None:
    p = point.payload or {}
    try:
        lat = float(p["latitude"])
        lon = float(p["longitude"])
        acq_date = str(p.get("acq_date", ""))
        return FIRMSHotspot(
            id=str(point.id),
            latitude=lat,
            longitude=lon,
            frp=float(p.get("frp") or 0),
            brightness=float(p.get("brightness") or 0),
            confidence=str(p.get("confidence", "")),
            acq_date=acq_date,
            acq_time=str(p.get("acq_time", "")),
            satellite=str(p.get("satellite", "")),
            bbox_name=str(p.get("bbox_name", "")),
            possible_explosion=bool(p.get("possible_explosion", False)),
            firms_map_url=_build_map_url(acq_date, lat, lon),
        )
    except (KeyError, ValueError, TypeError):
        return None


@router.get("/hotspots", response_model=list[FIRMSHotspot])
async def get_firms_hotspots(
    request: Request,
    since_hours: int = Query(default=24, ge=1, le=168),
) -> list[FIRMSHotspot]:
    cache_key = f"firms:hotspots:{since_hours}h"
    cache = request.app.state.cache
    cached = await cache.get(cache_key)
    if cached is not None:
        return [FIRMSHotspot(**h) for h in cached]

    cutoff = int(time.time()) - since_hours * 3600
    flt = Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value="firms")),
            FieldCondition(key="ingested_epoch", range=Range(gte=cutoff)),
        ]
    )

    try:
        qdrant = await get_qdrant_client()
        results: list[Any] = []
        next_offset: Any = None
        while True:
            points, next_offset = await qdrant.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=flt,
                limit=_PAGE_SIZE,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            results.extend(points)
            if next_offset is None or len(results) >= _MAX_TOTAL:
                break
    except Exception as exc:
        log.error("firms_qdrant_scroll_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="qdrant unreachable") from exc

    hotspots = [h for h in (_point_to_hotspot(p) for p in results) if h is not None]
    await cache.set(cache_key, [h.model_dump() for h in hotspots], ttl=_CACHE_TTL_S)
    return hotspots
```

- [ ] **Step 4: Wire the router into main.py**

In `services/backend/app/main.py`, extend the imports and the `include_router` block:

```python
from app.routers import (
    cables,
    earthquakes,
    firms,
    flights,
    graph,
    hotspots,
    intel,
    rag,
    satellites,
    vessels,
)
```

And add below the existing `include_router` lines:

```python
app.include_router(firms.router, prefix="/api/v1")
```

- [ ] **Step 5: Run the happy-path test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_firms_router.py::test_firms_hotspots_happy_path -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/backend/app/routers/firms.py \
        services/backend/app/main.py \
        services/backend/tests/unit/test_firms_router.py
git commit -m "feat(backend): add FIRMS hotspots router — happy path"
```

---

### Task 4: FIRMS router — pagination, cache hit, boundary 422

**Files:**
- Modify: `services/backend/tests/unit/test_firms_router.py`

- [ ] **Step 1: Add pagination test**

Append to `test_firms_router.py`:

```python
@pytest.mark.asyncio
async def test_firms_hotspots_pagination_concatenates_pages() -> None:
    """Scroll with two pages returns the concatenation."""
    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.side_effect = [
        ([_make_point("id-a", 48.1, 37.8, 50.0)], "next-token"),
        ([_make_point("id-b", 48.2, 37.9, 50.0)], None),
    ]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/firms/hotspots")

    assert resp.status_code == 200
    body = resp.json()
    assert [h["id"] for h in body] == ["id-a", "id-b"]
    assert mock_qdrant.scroll.call_count == 2
```

- [ ] **Step 2: Add cache-hit test**

Append:

```python
@pytest.mark.asyncio
async def test_firms_hotspots_cache_hit_short_circuits_qdrant() -> None:
    cached_payload = [{
        "id": "cached-a", "latitude": 48.1, "longitude": 37.8,
        "frp": 10.0, "brightness": 350.0, "confidence": "n",
        "acq_date": "2026-04-11", "acq_time": "1200",
        "satellite": "VIIRS_SNPP_NRT", "bbox_name": "ukraine",
        "possible_explosion": False,
        "firms_map_url": "https://firms.modaps.eosdis.nasa.gov/map/#d:2026-04-11;@37.8000,48.1000,10z",
    }]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = cached_payload
    app.state.cache = mock_cache

    mock_qdrant = AsyncMock()
    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/firms/hotspots")

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "cached-a"
    mock_qdrant.scroll.assert_not_called()
```

- [ ] **Step 3: Add boundary tests**

Append:

```python
def test_firms_hotspots_since_hours_too_low_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/firms/hotspots?since_hours=0")
    assert resp.status_code == 422


def test_firms_hotspots_since_hours_too_high_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/firms/hotspots?since_hours=169")
    assert resp.status_code == 422
```

- [ ] **Step 4: Run all FIRMS tests**

Run: `cd services/backend && uv run pytest tests/unit/test_firms_router.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add services/backend/tests/unit/test_firms_router.py
git commit -m "test(backend): FIRMS router pagination, cache, boundary cases"
```

---

## Phase C — Backend Aircraft router

### Task 5: Aircraft router — happy path

**Files:**
- Create: `services/backend/app/routers/aircraft.py`
- Create: `services/backend/tests/unit/test_aircraft_router.py`
- Modify: `services/backend/app/main.py`

- [ ] **Step 1: Write failing happy-path test**

Create `services/backend/tests/unit/test_aircraft_router.py`:

```python
"""Tests for the Aircraft tracks router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.asyncio
async def test_aircraft_tracks_happy_path() -> None:
    """Two aircraft, one with 3 points and one with 1 point."""
    rows = [
        {
            "icao24": "AE1234",
            "callsign": "RCH842",
            "type_code": "C17",
            "military_branch": "USAF",
            "registration": "05-5140",
            "points": [
                {"lat": 51.0, "lon": 12.0, "altitude_m": 10000, "speed_ms": 240, "heading": 90, "timestamp": 1744300000},
                {"lat": 51.2, "lon": 12.3, "altitude_m": 10100, "speed_ms": 242, "heading": 92, "timestamp": 1744300900},
                {"lat": 51.4, "lon": 12.6, "altitude_m": 10200, "speed_ms": 245, "heading": 94, "timestamp": 1744301800},
            ],
        },
        {
            "icao24": "AE5678",
            "callsign": None,
            "type_code": "KC135",
            "military_branch": "USAF",
            "registration": "58-0100",
            "points": [
                {"lat": 49.0, "lon": 8.0, "altitude_m": 9000, "speed_ms": 220, "heading": 180, "timestamp": 1744302000},
            ],
        },
    ]

    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.aircraft.read_query", AsyncMock(return_value=rows)):
        client = TestClient(app)
        resp = client.get("/api/v1/aircraft/tracks")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["icao24"] == "AE1234"
    assert len(body[0]["points"]) == 3
    assert body[0]["points"][0]["altitude_m"] == 10000
    assert body[1]["callsign"] is None
    assert len(body[1]["points"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_aircraft_router.py::test_aircraft_tracks_happy_path -v`
Expected: FAIL — router not yet mounted.

- [ ] **Step 3: Create aircraft.py router**

Create `services/backend/app/routers/aircraft.py`:

```python
"""Military Aircraft tracks — serves Neo4j-backed SPOTTED_AT tracks for globe rendering."""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.neo4j_client import read_query

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/aircraft", tags=["aircraft"])

_CACHE_TTL_S = 30

_TRACK_QUERY = """
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
"""


class AircraftPoint(BaseModel):
    lat: float
    lon: float
    altitude_m: float | None
    speed_ms: float | None
    heading: float | None
    timestamp: int


class AircraftTrack(BaseModel):
    icao24: str
    callsign: str | None
    type_code: str | None
    military_branch: str | None
    registration: str | None
    points: list[AircraftPoint]


@router.get("/tracks", response_model=list[AircraftTrack])
async def get_aircraft_tracks(
    request: Request,
    since_hours: int = Query(default=24, ge=1, le=72),
) -> list[AircraftTrack]:
    cache_key = f"aircraft:tracks:{since_hours}h"
    cache = request.app.state.cache
    cached = await cache.get(cache_key)
    if cached is not None:
        return [AircraftTrack(**t) for t in cached]

    since_epoch = int(time.time()) - since_hours * 3600

    try:
        rows = await read_query(_TRACK_QUERY, {"since_epoch": since_epoch})
    except Exception as exc:
        log.error("aircraft_neo4j_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="neo4j unreachable") from exc

    tracks = [AircraftTrack(**row) for row in rows]
    await cache.set(cache_key, [t.model_dump() for t in tracks], ttl=_CACHE_TTL_S)
    return tracks
```

- [ ] **Step 4: Wire into main.py**

In `services/backend/app/main.py`, add `aircraft` to the router imports:

```python
from app.routers import (
    aircraft,
    cables,
    earthquakes,
    firms,
    ...
)
```

And register:

```python
app.include_router(aircraft.router, prefix="/api/v1")
```

- [ ] **Step 5: Run happy-path test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_aircraft_router.py::test_aircraft_tracks_happy_path -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/backend/app/routers/aircraft.py \
        services/backend/app/main.py \
        services/backend/tests/unit/test_aircraft_router.py
git commit -m "feat(backend): add Aircraft tracks router — happy path"
```

---

### Task 6: Aircraft router — cache, boundary, query-string guard

**Files:**
- Modify: `services/backend/tests/unit/test_aircraft_router.py`

- [ ] **Step 1: Add cache-hit test**

Append to `test_aircraft_router.py`:

```python
@pytest.mark.asyncio
async def test_aircraft_tracks_cache_hit_short_circuits_neo4j() -> None:
    cached = [{
        "icao24": "AE9999",
        "callsign": "TEST01",
        "type_code": "F16",
        "military_branch": "USAF",
        "registration": "87-0001",
        "points": [{
            "lat": 40.0, "lon": -70.0,
            "altitude_m": 5000, "speed_ms": 200, "heading": 270,
            "timestamp": 1744300000,
        }],
    }]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = cached
    app.state.cache = mock_cache

    read_mock = AsyncMock()
    with patch("app.routers.aircraft.read_query", read_mock):
        client = TestClient(app)
        resp = client.get("/api/v1/aircraft/tracks")

    assert resp.status_code == 200
    assert resp.json()[0]["icao24"] == "AE9999"
    read_mock.assert_not_called()
```

- [ ] **Step 2: Add empty-result test**

Append:

```python
@pytest.mark.asyncio
async def test_aircraft_tracks_empty_neo4j_returns_empty_list() -> None:
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.aircraft.read_query", AsyncMock(return_value=[])):
        client = TestClient(app)
        resp = client.get("/api/v1/aircraft/tracks")

    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 3: Add boundary tests**

Append:

```python
def test_aircraft_tracks_since_hours_too_low_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/aircraft/tracks?since_hours=0")
    assert resp.status_code == 422


def test_aircraft_tracks_since_hours_too_high_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/aircraft/tracks?since_hours=73")
    assert resp.status_code == 422
```

- [ ] **Step 4: Add Cypher NULL filter guard test**

Append:

```python
def test_aircraft_tracks_query_filters_null_coordinates() -> None:
    """Cypher text must filter null lat/lon so the router doesn't rely on Python-side filtering."""
    from app.routers.aircraft import _TRACK_QUERY
    assert "r.latitude IS NOT NULL" in _TRACK_QUERY
    assert "r.longitude IS NOT NULL" in _TRACK_QUERY
```

- [ ] **Step 5: Run all aircraft tests**

Run: `cd services/backend && uv run pytest tests/unit/test_aircraft_router.py -v`
Expected: 6 PASS

- [ ] **Step 6: Lint & type-check backend**

Run: `cd services/backend && uv run ruff check app/ tests/ && uv run mypy app/`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add services/backend/tests/unit/test_aircraft_router.py
git commit -m "test(backend): Aircraft router cache, boundary, null-filter cases"
```

---

## Phase D — Frontend types + API client

### Task 7: Add FIRMS + Aircraft types and extend LayerVisibility

**Files:**
- Modify: `services/frontend/src/types/index.ts`

- [ ] **Step 1: Append new types**

Open `services/frontend/src/types/index.ts` and append after the existing `Hotspot` interface:

```tsx
export interface FIRMSHotspot {
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
  firms_map_url: string;
}

export interface AircraftPoint {
  lat: number;
  lon: number;
  altitude_m: number | null;
  speed_ms: number | null;
  heading: number | null;
  timestamp: number;
}

export interface AircraftTrack {
  icao24: string;
  callsign: string | null;
  type_code: string | null;
  military_branch: string | null;
  registration: string | null;
  points: AircraftPoint[];
}
```

- [ ] **Step 2: Extend LayerVisibility interface**

Find the `LayerVisibility` interface in the same file and add two fields:

```tsx
export interface LayerVisibility {
  flights: boolean;
  satellites: boolean;
  earthquakes: boolean;
  vessels: boolean;
  cctv: boolean;
  events: boolean;
  cables: boolean;
  pipelines: boolean;
  firmsHotspots: boolean;   // new
  milAircraft: boolean;     // new
}
```

(If the existing interface has different keys, preserve them — only add the two new ones.)

- [ ] **Step 3: Run TypeScript check**

Run: `cd services/frontend && npm run type-check`
Expected: FAIL — existing `layers` state initialisers / consumers don't include the new keys. That's fine, we fix it in Task 12.

For now, ignore — we commit types separately and fix downstream in later tasks.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/types/index.ts
git commit -m "feat(frontend): add FIRMS + Aircraft types, extend LayerVisibility"
```

---

### Task 8: Add API client functions for FIRMS + Aircraft

**Files:**
- Modify: `services/frontend/src/services/api.ts`

- [ ] **Step 1: Add the new type imports**

In `services/frontend/src/services/api.ts`, extend the type import list:

```tsx
import type {
  Aircraft,
  AircraftTrack,         // new
  CableDataset,
  ClientConfig,
  Earthquake,
  FIRMSHotspot,          // new
  GeoEventsResponse,
  Hotspot,
  IntelAnalysis,
  IntelEvent,
  IntelQuery,
  Satellite,
  Vessel,
} from "../types";
```

- [ ] **Step 2: Add the two fetch helpers**

Append to `api.ts` after the existing `getHotspots` / similar helpers:

```tsx
export async function getFIRMSHotspots(sinceHours = 24): Promise<FIRMSHotspot[]> {
  return fetchJSON<FIRMSHotspot[]>(`/firms/hotspots?since_hours=${sinceHours}`);
}

export async function getAircraftTracks(sinceHours = 24): Promise<AircraftTrack[]> {
  return fetchJSON<AircraftTrack[]>(`/aircraft/tracks?since_hours=${sinceHours}`);
}
```

- [ ] **Step 3: Verify type-check passes for api.ts only**

Run: `cd services/frontend && npx tsc --noEmit src/services/api.ts`
Expected: no errors from api.ts itself (LayerVisibility mismatches are elsewhere).

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/services/api.ts
git commit -m "feat(frontend): add getFIRMSHotspots + getAircraftTracks API helpers"
```

---

## Phase E — Frontend hooks

### Task 9: useFIRMSHotspots hook

**Files:**
- Create: `services/frontend/src/hooks/useFIRMSHotspots.ts`
- Create: `services/frontend/src/hooks/__tests__/useFIRMSHotspots.test.ts`

- [ ] **Step 1: Write failing test**

Create `services/frontend/src/hooks/__tests__/useFIRMSHotspots.test.ts`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useFIRMSHotspots } from "../useFIRMSHotspots";

describe("useFIRMSHotspots", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fetches on mount when enabled", async () => {
    const spy = vi.spyOn(api, "getFIRMSHotspots").mockResolvedValue([
      {
        id: "h1", latitude: 48.1, longitude: 37.8, frp: 100, brightness: 390,
        confidence: "h", acq_date: "2026-04-11", acq_time: "1200",
        satellite: "VIIRS_SNPP_NRT", bbox_name: "ukraine",
        possible_explosion: true,
        firms_map_url: "https://example/",
      },
    ]);

    const { result } = renderHook(() => useFIRMSHotspots(true));
    await waitFor(() => expect(result.current.hotspots.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getFIRMSHotspots").mockResolvedValue([
      {
        id: "h1", latitude: 0, longitude: 0, frp: 0, brightness: 0,
        confidence: "", acq_date: "", acq_time: "",
        satellite: "", bbox_name: "", possible_explosion: false,
        firms_map_url: "",
      },
    ]);

    const { result, rerender } = renderHook(({ on }: { on: boolean }) => useFIRMSHotspots(on), {
      initialProps: { on: true },
    });
    await waitFor(() => expect(result.current.hotspots.length).toBe(1));

    rerender({ on: false });
    expect(result.current.hotspots.length).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useFIRMSHotspots.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the hook**

Create `services/frontend/src/hooks/useFIRMSHotspots.ts`:

```tsx
import { useState, useEffect, useCallback } from "react";
import type { FIRMSHotspot } from "../types";
import { getFIRMSHotspots } from "../services/api";

const POLL_INTERVAL = 60_000;

export function useFIRMSHotspots(enabled: boolean, sinceHours = 24) {
  const [hotspots, setHotspots] = useState<FIRMSHotspot[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getFIRMSHotspots(sinceHours);
      setHotspots(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled, sinceHours]);

  useEffect(() => {
    if (!enabled) {
      setHotspots([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { hotspots, loading, lastUpdate };
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useFIRMSHotspots.test.ts`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/hooks/useFIRMSHotspots.ts \
        services/frontend/src/hooks/__tests__/useFIRMSHotspots.test.ts
git commit -m "feat(frontend): add useFIRMSHotspots polling hook"
```

---

### Task 10: useAircraftTracks hook

**Files:**
- Create: `services/frontend/src/hooks/useAircraftTracks.ts`
- Create: `services/frontend/src/hooks/__tests__/useAircraftTracks.test.ts`

- [ ] **Step 1: Write failing test**

Create `services/frontend/src/hooks/__tests__/useAircraftTracks.test.ts`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useAircraftTracks } from "../useAircraftTracks";

describe("useAircraftTracks", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fetches on mount when enabled", async () => {
    const spy = vi.spyOn(api, "getAircraftTracks").mockResolvedValue([
      {
        icao24: "AE1234", callsign: "RCH842", type_code: "C17",
        military_branch: "USAF", registration: "05-5140",
        points: [{ lat: 51, lon: 12, altitude_m: 10000, speed_ms: 240, heading: 90, timestamp: 1744300000 }],
      },
    ]);

    const { result } = renderHook(() => useAircraftTracks(true));
    await waitFor(() => expect(result.current.tracks.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getAircraftTracks").mockResolvedValue([
      {
        icao24: "X", callsign: null, type_code: null, military_branch: null, registration: null,
        points: [],
      },
    ]);
    const { result, rerender } = renderHook(({ on }: { on: boolean }) => useAircraftTracks(on), {
      initialProps: { on: true },
    });
    await waitFor(() => expect(result.current.tracks.length).toBe(1));
    rerender({ on: false });
    expect(result.current.tracks.length).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useAircraftTracks.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the hook**

Create `services/frontend/src/hooks/useAircraftTracks.ts`:

```tsx
import { useState, useEffect, useCallback } from "react";
import type { AircraftTrack } from "../types";
import { getAircraftTracks } from "../services/api";

const POLL_INTERVAL = 30_000;

export function useAircraftTracks(enabled: boolean, sinceHours = 24) {
  const [tracks, setTracks] = useState<AircraftTrack[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getAircraftTracks(sinceHours);
      setTracks(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled, sinceHours]);

  useEffect(() => {
    if (!enabled) {
      setTracks([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { tracks, loading, lastUpdate };
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useAircraftTracks.test.ts`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/hooks/useAircraftTracks.ts \
        services/frontend/src/hooks/__tests__/useAircraftTracks.test.ts
git commit -m "feat(frontend): add useAircraftTracks polling hook"
```

---

## Phase F — Frontend FIRMS layer

### Task 11: FIRMS layer canvas helpers + component

**Files:**
- Create: `services/frontend/src/components/layers/FIRMSLayer.tsx`
- Create: `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx`

- [ ] **Step 1: Write failing test for createFIRMSDot + layer mount**

Create `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { FIRMSLayer, createFIRMSDot, frpToSize, frpToColor } from "../FIRMSLayer";
import type { FIRMSHotspot } from "../../../types";

function fakeViewer(): Cesium.Viewer {
  const bc = new Cesium.BillboardCollection({ scene: {} as Cesium.Scene });
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  return {
    scene: { primitives, requestRender: vi.fn() },
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

describe("FIRMS canvas helpers", () => {
  it("frpToSize clamps between 6 and 22", () => {
    expect(frpToSize(0)).toBe(6);
    expect(frpToSize(40)).toBeCloseTo(16);
    expect(frpToSize(500)).toBe(22);
  });

  it("frpToColor interpolates yellow → orange → red", () => {
    const cold = frpToColor(0);
    const hot = frpToColor(100);
    expect(cold.red).toBeGreaterThan(0.9);
    expect(cold.green).toBeGreaterThan(0.8);
    expect(hot.red).toBeGreaterThan(0.9);
    expect(hot.green).toBeLessThan(0.3);
  });

  it("createFIRMSDot returns a canvas of non-zero size", () => {
    const c = createFIRMSDot(10, Cesium.Color.RED);
    expect(c.width).toBeGreaterThan(0);
    expect(c.height).toBeGreaterThan(0);
  });
});

describe("FIRMSLayer component", () => {
  const baseHotspot = (over: Partial<FIRMSHotspot>): FIRMSHotspot => ({
    id: over.id ?? "h",
    latitude: 48, longitude: 37,
    frp: 20, brightness: 370, confidence: "n",
    acq_date: "2026-04-11", acq_time: "1200",
    satellite: "VIIRS_SNPP_NRT", bbox_name: "ukraine",
    possible_explosion: false,
    firms_map_url: "https://example/",
    ...over,
  });

  it("renders without throwing for three hotspots (one flagged)", () => {
    const viewer = fakeViewer();
    const onSelect = vi.fn();
    render(
      <FIRMSLayer
        viewer={viewer}
        hotspots={[
          baseHotspot({ id: "a" }),
          baseHotspot({ id: "b" }),
          baseHotspot({ id: "c", possible_explosion: true }),
        ]}
        visible={true}
        onSelect={onSelect}
      />,
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/FIRMSLayer.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create FIRMSLayer.tsx**

Create `services/frontend/src/components/layers/FIRMSLayer.tsx`:

```tsx
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";

export function frpToSize(frp: number): number {
  return Math.min(22, 6 + Math.min(frp / 4, 16));
}

export function frpToColor(frp: number): Cesium.Color {
  const clamped = Math.max(0, Math.min(100, frp));
  const t = clamped / 100;
  if (t < 0.5) {
    const k = t / 0.5;
    return new Cesium.Color(1.0, 1.0 - 0.35 * k, 0.0, 1.0);
  }
  const k = (t - 0.5) / 0.5;
  return new Cesium.Color(1.0, 0.65 * (1 - k), 0.0, 1.0);
}

export function createFIRMSDot(radius: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(radius * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const center = canvasSize / 2;
  const grad = ctx.createRadialGradient(center, center, radius * 0.2, center, center, radius);
  grad.addColorStop(0, `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 1.0)`);
  grad.addColorStop(1, `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.0)`);
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(center, center, radius, 0, Math.PI * 2);
  ctx.fill();
  return canvas;
}

export function createFIRMSRing(size: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(size * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const center = canvasSize / 2;
  ctx.beginPath();
  ctx.arc(center, center, size, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.8)`;
  ctx.lineWidth = 2;
  ctx.stroke();
  return canvas;
}

interface FIRMSLayerProps {
  viewer: Cesium.Viewer | null;
  hotspots: FIRMSHotspot[];
  visible: boolean;
  onSelect?: (h: FIRMSHotspot) => void;
}

interface FIRMSPulse {
  ring: Cesium.Billboard;
  color: Cesium.Color;
}

export function FIRMSLayer({ viewer, hotspots, visible, onSelect }: FIRMSLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, FIRMSHotspot>>(new Map());
  const pulsesRef = useRef<FIRMSPulse[]>([]);
  const animFrameRef = useRef<number | null>(null);
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
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const hotspot = idMapRef.current.get(picked.primitive as unknown as object);
        if (hotspot && onSelectRef.current) onSelectRef.current(hotspot);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed() && collectionRef.current) {
        viewer.scene.primitives.remove(collectionRef.current);
      }
      collectionRef.current = null;
      idMapRef.current.clear();
      pulsesRef.current = [];
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    if (!bc) return;
    bc.removeAll();
    idMapRef.current.clear();
    pulsesRef.current = [];
    if (!visible) return;

    for (const h of hotspots) {
      const position = Cesium.Cartesian3.fromDegrees(h.longitude, h.latitude, 0);
      const size = frpToSize(h.frp);
      const color = frpToColor(h.frp);
      const dot = bc.add({
        position,
        image: createFIRMSDot(size, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -45),
      });
      idMapRef.current.set(dot as unknown as object, h);
      if (h.possible_explosion) {
        const ring = bc.add({
          position,
          image: createFIRMSRing(size * 1.5, color),
          scale: 1.0,
          eyeOffset: new Cesium.Cartesian3(0, 0, -44),
        });
        pulsesRef.current.push({ ring, color });
      }
    }
  }, [hotspots, visible]);

  useEffect(() => {
    if (!visible || pulsesRef.current.length === 0) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      return;
    }
    const animate = () => {
      const now = Date.now();
      const phase = (now * 0.003) % (Math.PI * 2);
      const scale = 1.0 + 0.5 * Math.sin(phase);
      const alpha = 0.8 - 0.4 * Math.sin(phase);
      for (const p of pulsesRef.current) {
        p.ring.scale = scale;
        p.ring.color = p.color.withAlpha(alpha);
      }
      animFrameRef.current = requestAnimationFrame(animate);
    };
    animFrameRef.current = requestAnimationFrame(animate);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [visible, hotspots]);

  return null;
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/FIRMSLayer.test.tsx`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/layers/FIRMSLayer.tsx \
        services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx
git commit -m "feat(frontend): add FIRMSLayer with FRP gradient + explosion pulse"
```

---

## Phase G — Frontend Aircraft layer

### Task 12: MilAircraftLayer canvas helpers + component

**Files:**
- Create: `services/frontend/src/components/layers/MilAircraftLayer.tsx`
- Create: `services/frontend/src/components/layers/__tests__/MilAircraftLayer.test.tsx`

- [ ] **Step 1: Write failing test**

Create `services/frontend/src/components/layers/__tests__/MilAircraftLayer.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import {
  MilAircraftLayer,
  branchColor,
  createJetIcon,
  trackToPolylinePositions,
} from "../MilAircraftLayer";
import type { AircraftTrack } from "../../../types";

function fakeViewer(): Cesium.Viewer {
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  return {
    scene: { primitives, requestRender: vi.fn() },
    canvas: document.createElement("canvas"),
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

describe("MilAircraft helpers", () => {
  it("branchColor maps known branches", () => {
    expect(branchColor("USAF").red).toBeGreaterThan(0.3);
    expect(branchColor("RUAF").red).toBeGreaterThan(0.9);
    expect(branchColor(null)).toEqual(Cesium.Color.WHITE);
  });

  it("createJetIcon returns canvas with visible pixels", () => {
    const c = createJetIcon(Cesium.Color.CYAN, 24);
    expect(c.width).toBe(24);
    expect(c.height).toBe(24);
    const ctx = c.getContext("2d");
    expect(ctx).not.toBeNull();
  });

  it("trackToPolylinePositions returns one Cartesian3 per point", () => {
    const positions = trackToPolylinePositions([
      { lat: 51, lon: 12, altitude_m: 10000, speed_ms: 240, heading: 90, timestamp: 1 },
      { lat: 52, lon: 13, altitude_m: 10100, speed_ms: 240, heading: 90, timestamp: 2 },
    ]);
    expect(positions.length).toBe(2);
  });

  it("trackToPolylinePositions falls back to 0 for null altitude", () => {
    const positions = trackToPolylinePositions([
      { lat: 0, lon: 0, altitude_m: null, speed_ms: null, heading: null, timestamp: 1 },
    ]);
    expect(positions.length).toBe(1);
  });
});

describe("MilAircraftLayer component", () => {
  const track = (id: string, nPoints: number): AircraftTrack => ({
    icao24: id,
    callsign: "TEST",
    type_code: "C17",
    military_branch: "USAF",
    registration: "00-0000",
    points: Array.from({ length: nPoints }, (_, i) => ({
      lat: 50 + i * 0.1,
      lon: 10 + i * 0.1,
      altitude_m: 10000,
      speed_ms: 240,
      heading: 90,
      timestamp: 1744300000 + i * 60,
    })),
  });

  it("renders without throwing for mixed-length tracks", () => {
    const viewer = fakeViewer();
    render(
      <MilAircraftLayer
        viewer={viewer}
        tracks={[track("a", 5), track("b", 1)]}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/MilAircraftLayer.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create MilAircraftLayer.tsx**

Create `services/frontend/src/components/layers/MilAircraftLayer.tsx`:

```tsx
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { AircraftPoint, AircraftTrack } from "../../types";

export function branchColor(branch: string | null): Cesium.Color {
  switch ((branch || "").toUpperCase()) {
    case "USAF":
      return Cesium.Color.fromCssColorString("#66e6ff");
    case "USN":
    case "USMC":
      return Cesium.Color.fromCssColorString("#4d9fff");
    case "RUAF":
    case "VKS":
      return Cesium.Color.fromCssColorString("#ff5050");
    default:
      return branch ? Cesium.Color.fromCssColorString("#ffaa33") : Cesium.Color.WHITE;
  }
}

export function createJetIcon(color: Cesium.Color, size = 24): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const cx = size / 2;
  ctx.translate(cx, cx);
  ctx.fillStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.95)`;
  ctx.strokeStyle = "rgba(0,0,0,0.8)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, -size * 0.45);
  ctx.lineTo(size * 0.1, size * 0.1);
  ctx.lineTo(size * 0.45, size * 0.2);
  ctx.lineTo(size * 0.1, size * 0.25);
  ctx.lineTo(size * 0.08, size * 0.4);
  ctx.lineTo(-size * 0.08, size * 0.4);
  ctx.lineTo(-size * 0.1, size * 0.25);
  ctx.lineTo(-size * 0.45, size * 0.2);
  ctx.lineTo(-size * 0.1, size * 0.1);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  return canvas;
}

export function trackToPolylinePositions(points: AircraftPoint[]): Cesium.Cartesian3[] {
  const arr: number[] = [];
  for (const p of points) {
    arr.push(p.lon, p.lat, p.altitude_m ?? 0);
  }
  return Cesium.Cartesian3.fromDegreesArrayHeights(arr);
}

interface MilAircraftLayerProps {
  viewer: Cesium.Viewer | null;
  tracks: AircraftTrack[];
  visible: boolean;
  onSelect?: (t: AircraftTrack) => void;
}

export function MilAircraftLayer({ viewer, tracks, visible, onSelect }: MilAircraftLayerProps) {
  const polyCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, AircraftTrack>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!polyCollectionRef.current) {
      polyCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(polyCollectionRef.current);
    }
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const track = idMapRef.current.get(picked.primitive as unknown as object);
        if (track && onSelectRef.current) onSelectRef.current(track);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed()) {
        if (polyCollectionRef.current) viewer.scene.primitives.remove(polyCollectionRef.current);
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
      }
      polyCollectionRef.current = null;
      billboardCollectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const pc = polyCollectionRef.current;
    const bc = billboardCollectionRef.current;
    if (!pc || !bc) return;
    pc.removeAll();
    bc.removeAll();
    idMapRef.current.clear();
    if (!visible) return;

    for (const t of tracks) {
      if (t.points.length === 0) continue;
      const color = branchColor(t.military_branch);

      if (t.points.length >= 2) {
        const positions = trackToPolylinePositions(t.points);
        const poly = pc.add({
          positions,
          width: 1.5,
          material: Cesium.Material.fromType("Color", { color: color.withAlpha(0.6) }),
        });
        idMapRef.current.set(poly as unknown as object, t);
      }

      const last = t.points[t.points.length - 1];
      const position = Cesium.Cartesian3.fromDegrees(last.lon, last.lat, last.altitude_m ?? 0);
      const rotationRad = Cesium.Math.toRadians(-(last.heading ?? 0) + 90);
      const bb = bc.add({
        position,
        image: createJetIcon(color, 24),
        scale: 0.8,
        rotation: rotationRad,
        alignedAxis: Cesium.Cartesian3.UNIT_Z,
        eyeOffset: new Cesium.Cartesian3(0, 0, -40),
      });
      idMapRef.current.set(bb as unknown as object, t);
    }
  }, [tracks, visible]);

  return null;
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/MilAircraftLayer.test.tsx`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/layers/MilAircraftLayer.tsx \
        services/frontend/src/components/layers/__tests__/MilAircraftLayer.test.tsx
git commit -m "feat(frontend): add MilAircraftLayer with 3D polylines + jet billboards"
```

---

## Phase H — UI wiring

### Task 13: OperationsPanel — split layer config, add Ingestion section

**Files:**
- Modify: `services/frontend/src/components/ui/OperationsPanel.tsx`

- [ ] **Step 1: Read current structure**

Open `services/frontend/src/components/ui/OperationsPanel.tsx` to review the current `LAYER_CONFIG` + `LayerIcon` + render block.

- [ ] **Step 2: Split the constant**

Rename the existing `LAYER_CONFIG` to `CORE_LAYERS` (keep its entries unchanged). Add below it:

```tsx
const INGESTION_LAYERS: { key: keyof LayerVisibility; label: string; color: string }[] = [
  { key: "firmsHotspots", label: "FIRMS HOTSPOTS", color: "#ff7a33" },
  { key: "milAircraft",   label: "MIL AIRCRAFT",   color: "#66e6ff" },
];
```

- [ ] **Step 3: Add two LayerIcon cases**

Inside the `LayerIcon` switch, add:

```tsx
case "firmsHotspots":
  return (
    <svg {...s}>
      <path
        d="M16 6 C13 12 10 13 10 18 A6 6 0 0 0 22 18 C22 13 19 12 16 6 Z"
        fill={color}
        opacity={0.8}
      />
    </svg>
  );
case "milAircraft":
  return (
    <svg {...s}>
      <path
        d="M16 4 L18 16 L28 18 L18 20 L17 28 L15 28 L14 20 L4 18 L14 16 Z"
        fill={color}
        opacity={0.85}
      />
    </svg>
  );
```

- [ ] **Step 4: Extend props**

Update `OperationsPanelProps`:

```tsx
interface OperationsPanelProps {
  layers: LayerVisibility;
  onToggleLayer: (layer: keyof LayerVisibility) => void;
  activeShader: ShaderType;
  onShaderChange: (shader: ShaderType) => void;
  firmsCount?: number;
  milAircraftCount?: number;
}
```

And in the function signature destructuring:

```tsx
export function OperationsPanel({
  layers,
  onToggleLayer,
  activeShader,
  onShaderChange,
  firmsCount = 0,
  milAircraftCount = 0,
}: OperationsPanelProps) {
```

- [ ] **Step 5: Render two sections**

Inside the layer-render block, replace the single `LAYER_CONFIG.map(...)` with two passes. Extract a helper for clarity:

```tsx
const countFor = (key: keyof LayerVisibility): number | null => {
  if (key === "firmsHotspots") return firmsCount;
  if (key === "milAircraft") return milAircraftCount;
  return null;
};

const renderLayerRow = ({ key, label, color }: { key: keyof LayerVisibility; label: string; color: string }) => {
  const count = countFor(key);
  const badge = count && count > 0 ? ` (${count})` : "";
  return (
    <button
      key={key}
      onClick={() => onToggleLayer(key)}
      className="w-full flex items-center gap-2 px-2 py-1.5 rounded mb-1 transition-colors border"
      style={layers[key] ? {
        backgroundColor: `${color}1a`,
        borderColor: `${color}4d`,
        color: color,
      } : {
        color: "rgba(0, 255, 65, 0.4)",
        borderColor: "transparent",
      }}
    >
      <LayerIcon layerKey={key} color={color} />
      <span>{label}{badge}</span>
    </button>
  );
};
```

Then in the JSX where the loop used to be:

```tsx
<div className="text-green-500/60 mb-2 text-[10px] tracking-widest">DATA LAYERS</div>
{CORE_LAYERS.map(renderLayerRow)}

<div className="mt-3 pt-3 border-t border-green-500/20 text-green-500/60 mb-2 text-[10px] tracking-widest">
  INGESTION
</div>
{INGESTION_LAYERS.map(renderLayerRow)}
```

(Adapt to whatever existing markup already wraps the button — keep the outer `div`s untouched.)

- [ ] **Step 6: Run type-check to see what still needs App.tsx**

Run: `cd services/frontend && npm run type-check`
Expected: remaining errors all point to `App.tsx` passing a LayerVisibility missing the two new keys. That's fixed in Task 15.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/components/ui/OperationsPanel.tsx
git commit -m "feat(frontend): split OperationsPanel into CORE_LAYERS + INGESTION_LAYERS"
```

---

### Task 14: SelectionPanel (bottom-left info card)

**Files:**
- Create: `services/frontend/src/components/ui/SelectionPanel.tsx`
- Create: `services/frontend/src/components/ui/__tests__/SelectionPanel.test.tsx`

- [ ] **Step 1: Write failing test**

Create `services/frontend/src/components/ui/__tests__/SelectionPanel.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SelectionPanel } from "../SelectionPanel";
import type { FIRMSHotspot, AircraftTrack } from "../../../types";

const hotspot: FIRMSHotspot = {
  id: "h1",
  latitude: 48.1234,
  longitude: 37.5678,
  frp: 87.3,
  brightness: 382.1,
  confidence: "h",
  acq_date: "2026-04-11",
  acq_time: "1423",
  satellite: "VIIRS_SNPP_NRT",
  bbox_name: "ukraine",
  possible_explosion: true,
  firms_map_url: "https://example/map",
};

const track: AircraftTrack = {
  icao24: "AE1234",
  callsign: "RCH842",
  type_code: "C17",
  military_branch: "USAF",
  registration: "05-5140",
  points: [
    { lat: 51, lon: 12, altitude_m: 10000, speed_ms: 240, heading: 90, timestamp: 1 },
    { lat: 52, lon: 13, altitude_m: 10100, speed_ms: 245, heading: 92, timestamp: 2 },
  ],
};

describe("SelectionPanel", () => {
  it("returns null when selected is null", () => {
    const { container } = render(
      <SelectionPanel selected={null} onClose={vi.fn()} viewer={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders FIRMS details with explosion badge and link", () => {
    render(
      <SelectionPanel
        selected={{ type: "firms", data: hotspot }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText(/THERMAL ANOMALY/i)).toBeInTheDocument();
    expect(screen.getByText(/POSSIBLE EXPLOSION/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /FIRMS Map/i })).toHaveAttribute(
      "href",
      "https://example/map",
    );
  });

  it("renders aircraft details with callsign and points count", () => {
    render(
      <SelectionPanel
        selected={{ type: "aircraft", data: track }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.getByText(/RCH842/)).toBeInTheDocument();
    expect(screen.getByText(/C17/)).toBeInTheDocument();
    expect(screen.getByText(/2 points/i)).toBeInTheDocument();
  });

  it("calls onClose when × is clicked", () => {
    const onClose = vi.fn();
    render(
      <SelectionPanel
        selected={{ type: "firms", data: hotspot }}
        onClose={onClose}
        viewer={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/ui/__tests__/SelectionPanel.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create SelectionPanel.tsx**

Create `services/frontend/src/components/ui/SelectionPanel.tsx`:

```tsx
import * as Cesium from "cesium";
import type { AircraftTrack, FIRMSHotspot } from "../../types";

export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: AircraftTrack };

interface SelectionPanelProps {
  selected: Selected | null;
  onClose: () => void;
  viewer: Cesium.Viewer | null;
}

export function SelectionPanel({ selected, onClose, viewer }: SelectionPanelProps) {
  if (!selected) return null;

  return (
    <div className="absolute left-3 bottom-16 w-80 max-h-[40vh] overflow-y-auto bg-black/85 border border-green-500/20 rounded font-mono text-xs z-40 backdrop-blur-sm">
      <div className="flex items-center justify-between px-3 py-2 border-b border-green-500/20 text-green-400 font-bold tracking-wider">
        <span>{selected.type === "firms" ? "THERMAL ANOMALY" : "AIRCRAFT TRACK"}</span>
        <button
          aria-label="close"
          onClick={onClose}
          className="text-green-400/60 hover:text-green-400"
        >
          ×
        </button>
      </div>
      <div className="p-3 text-green-300/80 leading-relaxed">
        {selected.type === "firms" ? (
          <FIRMSContent h={selected.data} />
        ) : (
          <AircraftContent t={selected.data} viewer={viewer} />
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="text-green-500/50">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}

function FIRMSContent({ h }: { h: FIRMSHotspot }) {
  return (
    <>
      {h.possible_explosion && (
        <div className="mb-2 px-2 py-1 bg-red-900/40 border border-red-500/40 text-red-300 rounded text-center tracking-widest">
          POSSIBLE EXPLOSION
        </div>
      )}
      <Row label="FRP" value={`${h.frp.toFixed(1)} MW`} />
      <Row label="BRIGHTNESS" value={`${h.brightness.toFixed(1)} K`} />
      <Row label="CONFIDENCE" value={h.confidence || "-"} />
      <Row label="SATELLITE" value={h.satellite} />
      <Row label="ACQ" value={`${h.acq_date} ${h.acq_time}`} />
      <Row label="REGION" value={h.bbox_name} />
      <Row label="POSITION" value={`${h.latitude.toFixed(4)}, ${h.longitude.toFixed(4)}`} />
      <a
        href={h.firms_map_url}
        target="_blank"
        rel="noreferrer"
        className="block mt-2 text-center text-cyan-300 hover:text-cyan-200 underline"
      >
        View on FIRMS Map
      </a>
    </>
  );
}

function AircraftContent({ t, viewer }: { t: AircraftTrack; viewer: Cesium.Viewer | null }) {
  const last = t.points[t.points.length - 1];

  const onCenter = () => {
    if (!viewer || viewer.isDestroyed() || t.points.length === 0) return;
    const cartesians = t.points.map((p) =>
      Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.altitude_m ?? 0),
    );
    const sphere = Cesium.BoundingSphere.fromPoints(cartesians);
    viewer.camera.flyToBoundingSphere(sphere, { duration: 1.2 });
  };

  return (
    <>
      <div className="mb-1 text-green-300 font-bold">
        {t.callsign || t.icao24}
      </div>
      <div className="mb-2 text-green-500/60">
        {[t.type_code, t.military_branch, t.registration].filter(Boolean).join(" • ") || "—"}
      </div>
      <Row label="ICAO24" value={t.icao24} />
      <Row label="POINTS" value={`${t.points.length} points`} />
      {last && (
        <>
          <Row label="POSITION" value={`${last.lat.toFixed(4)}, ${last.lon.toFixed(4)}`} />
          <Row label="ALTITUDE" value={last.altitude_m != null ? `${last.altitude_m.toFixed(0)} m` : "—"} />
          <Row label="SPEED" value={last.speed_ms != null ? `${last.speed_ms.toFixed(0)} m/s` : "—"} />
          <Row label="HEADING" value={last.heading != null ? `${last.heading.toFixed(0)}°` : "—"} />
        </>
      )}
      <button
        onClick={onCenter}
        className="block w-full mt-2 px-2 py-1 bg-cyan-900/30 border border-cyan-500/40 text-cyan-300 rounded hover:bg-cyan-900/50"
      >
        Center on track
      </button>
    </>
  );
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd services/frontend && npx vitest run src/components/ui/__tests__/SelectionPanel.test.tsx`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/ui/SelectionPanel.tsx \
        services/frontend/src/components/ui/__tests__/SelectionPanel.test.tsx
git commit -m "feat(frontend): add SelectionPanel for FIRMS + Aircraft click details"
```

---

### Task 15: Wire layers + hooks + selection into App.tsx

**Files:**
- Modify: `services/frontend/src/App.tsx`
- Modify: `services/backend/app/main.py` (`default_layers` dict)

- [ ] **Step 1: Extend App.tsx imports**

Add near the existing layer imports in `App.tsx`:

```tsx
import { FIRMSLayer } from "./components/layers/FIRMSLayer";
import { MilAircraftLayer } from "./components/layers/MilAircraftLayer";
import { SelectionPanel, type Selected } from "./components/ui/SelectionPanel";
import { useFIRMSHotspots } from "./hooks/useFIRMSHotspots";
import { useAircraftTracks } from "./hooks/useAircraftTracks";
```

- [ ] **Step 2: Extend the layers state initializer**

Find the `useState` call for `layers` (a `LayerVisibility` object) and add two keys:

```tsx
const [layers, setLayers] = useState<LayerVisibility>({
  flights: true,
  satellites: true,
  earthquakes: true,
  vessels: false,
  cctv: false,
  events: false,
  cables: false,
  pipelines: false,
  firmsHotspots: true,   // new
  milAircraft: true,     // new
});
```

(Preserve existing keys and defaults. Only add the two new entries.)

- [ ] **Step 3: Add hooks and selection state**

Near the other `use*` hook calls:

```tsx
const { hotspots: firmsHotspots } = useFIRMSHotspots(layers.firmsHotspots);
const { tracks: milTracks } = useAircraftTracks(layers.milAircraft);
const [selected, setSelected] = useState<Selected | null>(null);
```

- [ ] **Step 4: Mount the layers and SelectionPanel in the JSX**

Near the existing layer mounts (e.g. `<EarthquakeLayer ... />`), add:

```tsx
<FIRMSLayer
  viewer={viewer}
  hotspots={firmsHotspots}
  visible={layers.firmsHotspots}
  onSelect={(h) => setSelected({ type: "firms", data: h })}
/>
<MilAircraftLayer
  viewer={viewer}
  tracks={milTracks}
  visible={layers.milAircraft}
  onSelect={(t) => setSelected({ type: "aircraft", data: t })}
/>
```

Near the existing `<OperationsPanel ... />` mount, add the count props:

```tsx
<OperationsPanel
  layers={layers}
  onToggleLayer={(k) => setLayers((s) => ({ ...s, [k]: !s[k] }))}
  activeShader={activeShader}
  onShaderChange={setActiveShader}
  firmsCount={firmsHotspots.length}
  milAircraftCount={milTracks.length}
/>
```

And somewhere inside the root container (outside the Cesium div is fine):

```tsx
<SelectionPanel
  selected={selected}
  onClose={() => setSelected(null)}
  viewer={viewer}
/>
```

- [ ] **Step 5: Extend backend default_layers**

In `services/backend/app/main.py`, find the `client_config` function and extend its `default_layers` dict:

```python
default_layers={
    "flights": True,
    "satellites": True,
    "earthquakes": True,
    "vessels": False,
    "cctv": False,
    "events": False,
    "cables": False,
    "pipelines": False,
    "firmsHotspots": True,
    "milAircraft": True,
},
```

- [ ] **Step 6: Type-check + lint frontend**

Run:
```
cd services/frontend && npm run type-check && npm run lint
```
Expected: clean (no errors).

- [ ] **Step 7: Run full frontend test suite**

Run: `cd services/frontend && npx vitest run`
Expected: all tests PASS.

- [ ] **Step 8: Run full backend test suite + lint + mypy**

Run:
```
cd services/backend && uv run pytest && uv run ruff check app/ tests/ && uv run mypy app/
```
Expected: clean, all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add services/frontend/src/App.tsx services/backend/app/main.py
git commit -m "feat: wire FIRMS + MilAircraft layers, selection panel, default layers"
```

---

## Phase I — Smoke test & wrap-up

### Task 16: Manual smoke test

**Files:** none modified

- [ ] **Step 1: Boot ingestion stack**

Run: `./odin.sh up ingestion`
Wait ~5 minutes for FIRMS + Military Aircraft collectors to populate Qdrant and Neo4j.

- [ ] **Step 2: Verify backend endpoints**

```bash
curl -s localhost:8080/api/v1/firms/hotspots?since_hours=24 | jq length
curl -s localhost:8080/api/v1/aircraft/tracks?since_hours=24 | jq length
curl -s -o /dev/null -w "%{http_code}\n" localhost:8080/api/v1/firms/hotspots?since_hours=0
curl -s -o /dev/null -w "%{http_code}\n" localhost:8080/api/v1/aircraft/tracks?since_hours=73
```
Expected: integers > 0 for the first two, `422` for both boundary requests.

- [ ] **Step 3: Swap to interactive mode**

Run: `./odin.sh swap interactive`

- [ ] **Step 4: Open the frontend**

Open `http://localhost:5173` in a browser.

- [ ] **Step 5: Verify layers and interactions**

- Operations panel shows INGESTION section with `FIRMS HOTSPOTS (N)` and `MIL AIRCRAFT (N)` with live counts.
- Toggling each checkbox hides / shows the relevant primitives.
- Clicking a FIRMS dot opens the SelectionPanel with FRP/brightness/confidence and the "View on FIRMS Map" link.
- Clicking an aircraft icon opens the SelectionPanel with callsign/type/branch, and "Center on track" flies the camera.
- If any `possible_explosion` hotspot is present, the ring pulses smoothly.

- [ ] **Step 6: Document any deviations**

If any step fails, note the failure and open a follow-up task rather than forcing a green commit. If everything works, proceed.

- [ ] **Step 7: Final commit (only if README / docs updates were needed)**

If any notes or docs were updated during the smoke test, commit them. Otherwise skip this step.

---

## Done criteria

- All backend tests pass (`pytest tests/unit/test_firms_router.py tests/unit/test_aircraft_router.py`)
- `uv run ruff check` and `uv run mypy app/` clean
- All frontend tests pass (`npx vitest run`)
- `npm run type-check` and `npm run lint` clean
- Smoke test in Task 16 passes end-to-end on the real stack
