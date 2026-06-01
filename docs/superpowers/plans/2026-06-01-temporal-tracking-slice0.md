# Temporal Tracking — Slice 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared time foundation (global clock + two-tier scrubber + windowed-data contract) and prove it end-to-end with a real military-aircraft track replay, using data that already exists — no new storage.

**Architecture:** A global `TimeContext` (React facade over `Cesium.Clock`) exposes a ref-based `getTimeMs()` hot path plus throttled UI state. A storage-agnostic `GET /api/timeline/window` serves events (from Neo4j, filtered on a new canonical `timeline_at`) and mil-aircraft tracks (from existing `SPOTTED_AT` relationships). The ingestion pipeline stamps honest `timeline_at`/`time_basis`. The frontend normalizes live and replay track shapes through one adapter and drives `MilAircraftLayer` off the clock.

**Tech Stack:** FastAPI + Pydantic v2 + Neo4j (httpx + `read_query`); Python data-ingestion; React 19 + TypeScript + CesiumJS + Vitest.

**Spec:** `docs/superpowers/specs/2026-06-01-temporal-tracking-design.md`

**Base-branch assumption:** This plan executes on a branch based on the **merged reliability-first refactor** — routers mounted only under `/api`, `api.ts` `BASE = "/api"` (no `/api/v1` fallback), `usePeriodicJson` available. If executing before that merge lands, rebase onto it first. (`useTimeWindow` here is self-contained — it uses `AbortController` directly per the reliability pattern — so it does not hard-depend on `usePeriodicJson`.)

---

## File Structure

**Backend (`services/backend`)**
- Create `app/models/timeline.py` — `WindowSample` (discriminated union) + `WindowResponse`.
- Create `app/routers/timeline.py` — `GET /api/timeline/window` (events + mil-aircraft movements branches).
- Modify `app/main.py` — register the router under `/api`.
- Create `tests/unit/test_timeline_router.py`.

**Data-ingestion (`services/data-ingestion`)**
- Modify `pipeline.py` — optional time kwargs, `occurred_at` validator, `timeline_at`/`time_basis` on the Event write.
- Modify `feeds/{rss,usgs,firms}_collector.py` — pass native time into `process_item`.
- Modify `gdelt_raw/writers/neo4j_writer.py` — `timeline_at` on `ON CREATE`/`ON MATCH`.
- Create `gdelt_raw/migrations/phase3_timeline_at.cypher` + add `apply_phase3()` to `gdelt_raw/migrations/apply.py` + `gdelt_raw/migrations/run_phase3.py` (one-shot).
- Create `tests/test_pipeline_timeline_at.py`, `tests/test_collector_time_passthrough.py`, `tests/test_migration_phase3.py`.

**Frontend (`services/frontend`)**
- Create `src/state/TimeContext.tsx` (+ `__tests__/TimeContext.test.tsx`).
- Create `src/components/layers/milTrackAdapter.ts` (+ `__tests__/milTrackAdapter.test.ts`).
- Create `src/hooks/useTimeWindow.ts` (+ `__tests__/useTimeWindow.test.ts`); modify `src/services/api.ts`; add types to `src/types/index.ts`.
- Modify `src/components/layers/MilAircraftLayer.tsx` (time-aware).
- Create `src/components/time/TwoTierScrubber.tsx` (+ `__tests__`).
- Modify `src/pages/WorldviewPage.tsx` (provider + scrubber + live/replay switch).

---

## Backend

### Task 1: Window response models

**Files:**
- Create: `services/backend/app/models/timeline.py`
- Test: `services/backend/tests/unit/test_timeline_models.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/unit/test_timeline_models.py
from app.models.timeline import EventSample, TrackSample, TrackPoint, WindowResponse


def test_event_sample_defaults_nullable():
    s = EventSample(id="ev-1", time="2026-05-01T00:00:00Z", time_basis="indexed")
    assert s.kind == "event"
    assert s.title is None and s.severity is None and s.lat is None


def test_track_sample_roundtrip():
    s = TrackSample(
        id="abc123",
        icao24="abc123",
        points=[TrackPoint(ts_ms=1_700_000_000_000, lat=1.0, lon=2.0)],
    )
    assert s.kind == "track"
    assert s.points[0].ts_ms == 1_700_000_000_000


def test_window_response_shape():
    r = WindowResponse(
        domain="events", tier="coarse",
        t_start="2026-05-01T00:00:00Z", t_end="2026-05-02T00:00:00Z",
        bbox=None, samples=[], total_count=0, truncated=False,
    )
    assert r.truncated is False and r.samples == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_models.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.timeline`.

- [ ] **Step 3: Write the models**

```python
# services/backend/app/models/timeline.py
"""Windowed-data contract models for /api/timeline/window."""

from typing import Literal

from pydantic import BaseModel, Field


class EventSample(BaseModel):
    kind: Literal["event"] = "event"
    id: str
    time: str  # ISO-8601 UTC (the timeline anchor)
    time_basis: str
    title: str | None = None
    codebook_type: str | None = None
    severity: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    country: str | None = None


class TrackPoint(BaseModel):
    ts_ms: int  # epoch milliseconds
    lat: float
    lon: float
    altitude_m: float | None = None
    speed_ms: float | None = None
    heading: float | None = None


class TrackSample(BaseModel):
    kind: Literal["track"] = "track"
    id: str
    icao24: str | None = None
    callsign: str | None = None
    type_code: str | None = None
    military_branch: str | None = None
    registration: str | None = None
    points: list[TrackPoint] = Field(default_factory=list)


class BBox(BaseModel):
    west: float
    south: float
    east: float
    north: float


class WindowResponse(BaseModel):
    domain: Literal["events", "movements"]
    tier: Literal["coarse", "fine"]
    t_start: str
    t_end: str
    bbox: BBox | None = None
    samples: list[EventSample | TrackSample] = Field(default_factory=list)
    total_count: int = 0
    truncated: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_models.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/models/timeline.py services/backend/tests/unit/test_timeline_models.py
git commit -m "feat(backend): add timeline window contract models"
```

---

### Task 2: Param validation + bbox parsing helper

**Files:**
- Create: `services/backend/app/routers/timeline.py` (validation helpers only in this task)
- Test: `services/backend/tests/unit/test_timeline_params.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/unit/test_timeline_params.py
import pytest
from fastapi import HTTPException

from app.routers.timeline import parse_bbox, validate_window


def test_validate_window_rejects_reversed():
    with pytest.raises(HTTPException) as e:
        validate_window("2026-05-02T00:00:00Z", "2026-05-01T00:00:00Z")
    assert e.value.status_code == 422


def test_validate_window_rejects_bad_iso():
    with pytest.raises(HTTPException) as e:
        validate_window("not-a-date", "2026-05-01T00:00:00Z")
    assert e.value.status_code == 422


def test_parse_bbox_none_returns_none():
    assert parse_bbox(None) is None


def test_parse_bbox_valid():
    b = parse_bbox("-10,-20,30,40")
    assert (b.west, b.south, b.east, b.north) == (-10.0, -20.0, 30.0, 40.0)


def test_parse_bbox_bad_count_422():
    with pytest.raises(HTTPException) as e:
        parse_bbox("1,2,3")
    assert e.value.status_code == 422


def test_parse_bbox_out_of_range_422():
    with pytest.raises(HTTPException) as e:
        parse_bbox("-200,0,10,10")
    assert e.value.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_params.py -v`
Expected: FAIL — cannot import `parse_bbox`/`validate_window`.

- [ ] **Step 3: Write the helpers**

```python
# services/backend/app/routers/timeline.py
"""GET /api/timeline/window — storage-agnostic windowed-data contract (READ-ONLY)."""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, Query

from app.models.timeline import BBox, EventSample, TrackPoint, TrackSample, WindowResponse
from app.services.neo4j_client import read_query

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/timeline", tags=["timeline"])

_MAX_LIMIT = 500
_SUPPORTED_MOVEMENT_KINDS = {"mil_aircraft", "civil_aircraft", "ship", "satellite"}
_IMPLEMENTED_MOVEMENT_KINDS = {"mil_aircraft"}


def validate_window(t_start: str, t_end: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.fromisoformat(t_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(t_end.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="t_start/t_end must be ISO-8601") from exc
    if end < start:
        raise HTTPException(status_code=422, detail="t_end must be >= t_start")
    return start, end


def parse_bbox(raw: str | None) -> BBox | None:
    if raw is None:
        return None
    parts = raw.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox must be west,south,east,north")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox values must be numeric") from exc
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise HTTPException(status_code=422, detail="bbox out of range")
    if south > north:
        raise HTTPException(status_code=422, detail="bbox south must be <= north")
    return BBox(west=west, south=south, east=east, north=north)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_params.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/timeline.py services/backend/tests/unit/test_timeline_params.py
git commit -m "feat(backend): timeline window param + bbox validation"
```

---

### Task 3: Events branch of `/timeline/window`

**Files:**
- Modify: `services/backend/app/routers/timeline.py`
- Test: `services/backend/tests/unit/test_timeline_router.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/unit/test_timeline_router.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

W = "?t_start=2026-05-01T00:00:00Z&t_end=2026-05-02T00:00:00Z"


@pytest.fixture
def client():
    return TestClient(app)


def test_events_window_returns_samples(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [
            [{
                "id": "gdelt:event:1", "title": None, "codebook_type": "military.airstrike",
                "severity": None, "time": "2026-05-01T06:00:00Z", "time_basis": "indexed",
                "location_name": None, "country": None, "lat": None, "lon": None,
            }],
            [{"total": 1}],
        ]
        resp = client.get(f"/api/timeline/window{W}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "events" and data["tier"] == "coarse"
    assert data["samples"][0]["kind"] == "event"
    assert data["samples"][0]["title"] is None  # GDELT nullable
    assert data["samples"][0]["time_basis"] == "indexed"
    assert data["total_count"] == 1 and data["truncated"] is False


def test_reversed_window_422(client):
    resp = client.get("/api/timeline/window?t_start=2026-05-02T00:00:00Z&t_end=2026-05-01T00:00:00Z")
    assert resp.status_code == 422


def test_limit_over_cap_422(client):
    resp = client.get(f"/api/timeline/window{W}&limit=999")
    assert resp.status_code == 422


def test_events_with_movement_kind_422(client):
    resp = client.get(f"/api/timeline/window{W}&movement_kind=mil_aircraft")
    assert resp.status_code == 422


def test_events_fine_422(client):
    resp = client.get(f"/api/timeline/window{W}&tier=fine")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_router.py -v`
Expected: FAIL — route returns 404 (handler not yet added).

- [ ] **Step 3: Add the events query + handler skeleton**

Append to `services/backend/app/routers/timeline.py`:

```python
_EVENTS_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
WITH ev, l
WHERE $bbox_off
   OR (l.lat IS NOT NULL AND l.lon IS NOT NULL
       AND l.lat >= $south AND l.lat <= $north
       AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
          OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) ))
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at ASC
LIMIT $limit
"""

_EVENTS_COUNT_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
WITH ev, l
WHERE $bbox_off
   OR (l.lat IS NOT NULL AND l.lon IS NOT NULL
       AND l.lat >= $south AND l.lat <= $north
       AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
          OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) ))
RETURN count(DISTINCT ev) AS total
"""


def _bbox_params(bbox: BBox | None) -> dict:
    if bbox is None:
        return {"bbox_off": True, "west": -180.0, "east": 180.0, "south": -90.0, "north": 90.0}
    return {"bbox_off": False, "west": bbox.west, "east": bbox.east, "south": bbox.south, "north": bbox.north}


@router.get("/window", response_model=WindowResponse)
async def get_window(
    t_start: str,
    t_end: str,
    domain: str = "events",
    tier: str = "coarse",
    movement_kind: str | None = None,
    bbox: str | None = None,
    limit: int = Query(default=200),
) -> WindowResponse:
    if domain not in ("events", "movements"):
        raise HTTPException(status_code=422, detail="domain must be events|movements")
    if tier not in ("coarse", "fine"):
        raise HTTPException(status_code=422, detail="tier must be coarse|fine")
    if not (1 <= limit <= _MAX_LIMIT):
        raise HTTPException(status_code=422, detail=f"limit must be in [1,{_MAX_LIMIT}]")
    validate_window(t_start, t_end)
    box = parse_bbox(bbox)

    if domain == "events":
        if movement_kind is not None:
            raise HTTPException(status_code=422, detail="movement_kind only valid for domain=movements")
        if tier != "coarse":
            raise HTTPException(status_code=422, detail="events only support tier=coarse")
        return await _events_window(t_start, t_end, box, limit)

    return await _movements_window(t_start, t_end, tier, movement_kind, box, limit)


async def _events_window(t_start: str, t_end: str, box: BBox | None, limit: int) -> WindowResponse:
    params = {"t_start": t_start, "t_end": t_end, "limit": limit, **_bbox_params(box)}
    rows = await read_query(_EVENTS_QUERY, params)
    count_rows = await read_query(_EVENTS_COUNT_QUERY, params)
    total = int(count_rows[0]["total"]) if count_rows else len(rows)
    samples = [
        EventSample(
            id=str(r.get("id") or ""),
            time=str(r.get("time") or ""),
            time_basis=str(r.get("time_basis") or "indexed"),
            title=r.get("title"),
            codebook_type=r.get("codebook_type"),
            severity=r.get("severity"),
            lat=float(r["lat"]) if r.get("lat") is not None else None,
            lon=float(r["lon"]) if r.get("lon") is not None else None,
            location_name=r.get("location_name"),
            country=r.get("country"),
        )
        for r in rows
    ]
    return WindowResponse(
        domain="events", tier="coarse", t_start=t_start, t_end=t_end, bbox=box,
        samples=samples, total_count=total, truncated=total > len(samples),
    )
```

(The `_movements_window` function is added in Task 4 — add a temporary stub so the module imports: `async def _movements_window(*a, **k): raise HTTPException(status_code=501, detail="movements not implemented")`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_router.py -v`
Expected: PASS for the 5 tests above (event + 422 cases).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/timeline.py services/backend/tests/unit/test_timeline_router.py
git commit -m "feat(backend): timeline window events branch + status codes"
```

---

### Task 4: Movements branch (mil-aircraft) + 501s

**Files:**
- Modify: `services/backend/app/routers/timeline.py`
- Test: `services/backend/tests/unit/test_timeline_router.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_movements_mil_aircraft_window(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.return_value = [{
            "icao24": "abc123", "callsign": "FORTE10", "type_code": "RQ4",
            "military_branch": "USAF", "registration": None,
            "points": [
                {"ts_ms": 1714521600000, "lat": 50.0, "lon": 30.0,
                 "altitude_m": 18000.0, "speed_ms": 200.0, "heading": 90.0},
            ],
        }]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "movements"
    s = data["samples"][0]
    assert s["kind"] == "track" and s["icao24"] == "abc123"
    assert s["points"][0]["ts_ms"] == 1714521600000
    assert data["total_count"] == 1  # counts TRACKS not points


def test_movements_missing_kind_422(client):
    resp = client.get(f"/api/timeline/window{W}&domain=movements&tier=fine")
    assert resp.status_code == 422


def test_movements_coarse_422(client):
    resp = client.get(f"/api/timeline/window{W}&domain=movements&movement_kind=mil_aircraft")
    assert resp.status_code == 422  # tier defaults to coarse


def test_movements_civil_501(client):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=civil_aircraft"
    )
    assert resp.status_code == 501


def test_movements_unknown_kind_422(client):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=bicycle"
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_router.py -v`
Expected: FAIL — stub raises 501 for the valid mil case; 422 cases not yet distinguished.

- [ ] **Step 3: Replace the stub with the real movements branch**

Replace the temporary `_movements_window` stub with:

```python
_MIL_TRACKS_QUERY = """
MATCH (a:MilitaryAircraft)-[r:SPOTTED_AT]->()
WHERE r.timestamp >= $start_s AND r.timestamp <= $end_s
  AND r.latitude IS NOT NULL AND r.longitude IS NOT NULL
WITH a, r ORDER BY r.timestamp ASC
WITH a, collect(r) AS rs
WITH a, rs,
  [x IN rs WHERE $bbox_off
     OR (x.latitude >= $south AND x.latitude <= $north
         AND ( ($west <= $east AND x.longitude >= $west AND x.longitude <= $east)
            OR ($west >  $east AND (x.longitude >= $west OR x.longitude <= $east)) ))] AS inbox
WHERE size(inbox) >= 1
WITH a, [x IN rs | {
    ts_ms: x.timestamp * 1000, lat: x.latitude, lon: x.longitude,
    altitude_m: x.altitude_m, speed_ms: x.speed_ms, heading: x.heading
  }] AS points
RETURN a.icao24 AS icao24, a.callsign AS callsign, a.type_code AS type_code,
       a.military_branch AS military_branch, a.registration AS registration, points
ORDER BY points[-1].ts_ms DESC
LIMIT $limit
"""


async def _movements_window(
    t_start: str, t_end: str, tier: str, movement_kind: str | None, box: BBox | None, limit: int
) -> WindowResponse:
    if movement_kind is None:
        raise HTTPException(status_code=422, detail="movement_kind required for domain=movements")
    if movement_kind not in _SUPPORTED_MOVEMENT_KINDS:
        raise HTTPException(status_code=422, detail="unknown movement_kind")
    if tier != "fine":
        raise HTTPException(status_code=422, detail="movements only support tier=fine")
    if movement_kind not in _IMPLEMENTED_MOVEMENT_KINDS:
        raise HTTPException(status_code=501, detail=f"{movement_kind} not implemented")

    start, end = validate_window(t_start, t_end)
    params = {
        "start_s": int(start.timestamp()), "end_s": int(end.timestamp()),
        "limit": limit, **_bbox_params(box),
    }
    rows = await read_query(_MIL_TRACKS_QUERY, params)
    samples = [
        TrackSample(
            id=str(r.get("icao24") or ""),
            icao24=r.get("icao24"),
            callsign=r.get("callsign"),
            type_code=r.get("type_code"),
            military_branch=r.get("military_branch"),
            registration=r.get("registration"),
            points=[TrackPoint(**p) for p in (r.get("points") or [])],
        )
        for r in rows
    ]
    return WindowResponse(
        domain="movements", tier="fine", t_start=t_start, t_end=t_end, bbox=box,
        samples=samples, total_count=len(samples), truncated=len(samples) >= limit,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_router.py -v`
Expected: PASS (all events + movements cases).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/timeline.py services/backend/tests/unit/test_timeline_router.py
git commit -m "feat(backend): timeline window mil-aircraft movements branch"
```

---

### Task 5: Register the router under `/api`

**Files:**
- Modify: `services/backend/app/main.py:17-36` (imports) and `:182-192` (registration)
- Test: `services/backend/tests/unit/test_timeline_router.py` (the existing tests already hit `/api/timeline/window`)

- [ ] **Step 1: Add `timeline` to the router imports**

In the `from app.routers import (...)` block, add `timeline` (alphabetical, after `signals`):

```python
    signals,
    timeline,
    vessels,
)
```

- [ ] **Step 2: Register it under `/api`**

Add `timeline.router` to the `for r in (...)` tuple that mounts under `/api` (post-reliability: single prefix):

```python
    firms.router, aircraft.router, eonet.router, gdacs.router, reports.router,
    timeline.router,
):
    app.include_router(r, prefix="/api")
```

- [ ] **Step 3: Run the full router test**

Run: `cd services/backend && uv run pytest tests/unit/test_timeline_router.py -v && uv run ruff check app/`
Expected: PASS, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add services/backend/app/main.py
git commit -m "feat(backend): mount /api/timeline router"
```

---

## Data-ingestion

### Task 6: Honest `timeline_at` / `time_basis` on the Event write

**Files:**
- Modify: `services/data-ingestion/pipeline.py` (`process_item` signature `:179`, `_RESPONSE_SCHEMA` `:141`, Event write `:376-397`)
- Test: `services/data-ingestion/tests/test_pipeline_timeline_at.py`

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_pipeline_timeline_at.py
from pipeline import _resolve_timeline


def test_precedence_occurred_wins():
    at, basis = _resolve_timeline(
        occurred_at="2026-05-01T00:00:00+00:00",
        observed_at="2026-05-02T00:00:00+00:00",
        published_at="2026-05-03T00:00:00+00:00",
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-01T00:00:00+00:00" and basis == "occurred"


def test_falls_back_to_ingested():
    at, basis = _resolve_timeline(
        occurred_at=None, observed_at=None, published_at=None,
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-04T00:00:00+00:00" and basis == "ingested"


def test_malformed_occurred_is_dropped_not_fabricated():
    # malformed LLM hint -> not used; falls through to ingested, never now()
    at, basis = _resolve_timeline(
        occurred_at="last tuesday", observed_at=None, published_at=None,
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-04T00:00:00+00:00" and basis == "ingested"


def test_tz_naive_iso_is_normalized_to_utc():
    at, basis = _resolve_timeline(
        occurred_at="2026-05-01T00:00:00", observed_at=None, published_at=None,
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-01T00:00:00+00:00" and basis == "occurred"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_timeline_at.py -v`
Expected: FAIL — `cannot import name '_resolve_timeline'`.

- [ ] **Step 3: Add `_resolve_timeline` + a validator to `pipeline.py`**

Add near the top of `pipeline.py` (after imports; ensure `from datetime import UTC, datetime`):

```python
def _normalize_iso(value: str | None) -> str | None:
    """Validate + normalize an ISO-8601 string to tz-aware UTC; None if invalid."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _resolve_timeline(
    *, occurred_at: str | None, observed_at: str | None,
    published_at: str | None, ingested_at: str,
) -> tuple[str, str]:
    """Canonical timeline_at + time_basis by precedence. Never fabricates a time."""
    for value, basis in (
        (occurred_at, "occurred"),
        (observed_at, "observed"),
        (published_at, "published"),
    ):
        norm = _normalize_iso(value)
        if norm is not None:
            return norm, basis
    return ingested_at, "ingested"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_timeline_at.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Wire it into `process_item` (signature + write)**

Change the signature (`:179`) to accept optional time kwargs:

```python
async def process_item(
    title: str,
    text: str,
    url: str,
    source: str,
    *,
    settings: Settings,
    redis_client: Any | None = None,
    occurred_at: str | None = None,
    observed_at: str | None = None,
    published_at: str | None = None,
) -> dict | None:
```

Inside, before building Event statements, compute the canonical anchor (LLM hint is a *fallback* occurred_at — structured kwarg wins):

```python
    ingested_at = datetime.now(UTC).isoformat()
```

Then change the Events loop (`:376-397`) so each event resolves its own timeline:

```python
    # Create Events
    for event in events:
        ev_occurred = occurred_at or event.get("timestamp")  # structured kwarg beats LLM hint
        timeline_at, time_basis = _resolve_timeline(
            occurred_at=ev_occurred, observed_at=observed_at,
            published_at=published_at, ingested_at=ingested_at,
        )
        statements.append({
            "statement": (
                "CREATE (ev:Event {"
                "  title: $title, summary: $summary,"
                "  codebook_type: $codebook_type,"
                "  severity: $severity, confidence: $confidence,"
                "  timeline_at: datetime($timeline_at), time_basis: $time_basis"
                "}) "
                "WITH ev "
                "MATCH (d:Document {url: $url}) "
                "MERGE (d)-[:DESCRIBES]->(ev)"
            ),
            "parameters": {
                "title": event.get("title", ""),
                "summary": event.get("summary", ""),
                "codebook_type": event.get("codebook_type", "other.unclassified"),
                "severity": event.get("severity", "low"),
                "confidence": event.get("confidence", 0.5),
                "timeline_at": timeline_at,
                "time_basis": time_basis,
                "url": doc_url,
            },
        })
```

- [ ] **Step 6: Add a test asserting the built statement carries the fields**

```python
# append to tests/test_pipeline_timeline_at.py
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipeline import process_item
from tests.test_pipeline import _make_settings, _mock_vllm_response, _mock_neo4j_response


@pytest.mark.asyncio
async def test_event_write_includes_timeline_at():
    vllm = _mock_vllm_response(events=[{
        "title": "x", "summary": "y", "codebook_type": "military.airstrike",
        "severity": "high", "confidence": 0.9,
    }])
    neo = _mock_neo4j_response()
    captured = {}

    def _capture(*a, **k):
        captured["json"] = k.get("json")
        return neo

    with patch("pipeline.httpx.AsyncClient") as cls:
        mc = AsyncMock()
        mc.post.side_effect = [vllm, neo]
        cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await process_item(
            title="t", text="x", url="http://e/1", source="usgs",
            settings=_make_settings(), occurred_at="2026-05-01T00:00:00Z",
        )
        neo_call = mc.post.call_args_list[1]
    stmt = neo_call.kwargs["json"]["statements"]
    ev_stmt = next(s for s in stmt if "ev:Event" in s["statement"])
    assert "timeline_at: datetime($timeline_at)" in ev_stmt["statement"]
    assert ev_stmt["parameters"]["timeline_at"] == "2026-05-01T00:00:00+00:00"
    assert ev_stmt["parameters"]["time_basis"] == "occurred"
```

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_timeline_at.py -v`
Expected: PASS.

- [ ] **Step 7: Keep the LLM hint optional (schema unchanged) + run existing suite**

The schema's event `timestamp` stays optional (NOT added to `required`) — it is only a hint. Confirm no regression:

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline.py -v`
Expected: PASS (existing tests still green — signature change is backward-compatible).

- [ ] **Step 8: Commit**

```bash
git add services/data-ingestion/pipeline.py services/data-ingestion/tests/test_pipeline_timeline_at.py
git commit -m "feat(ingestion): stamp canonical timeline_at/time_basis on events (no fabricated time)"
```

---

### Task 7: Pass native source time from RSS / USGS / FIRMS

**Files:**
- Modify: `services/data-ingestion/feeds/rss_collector.py:282`, `feeds/usgs_collector.py:276`, `feeds/firms_collector.py:191`
- Test: `services/data-ingestion/tests/test_collector_time_passthrough.py`

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_collector_time_passthrough.py
import inspect

from feeds import rss_collector, usgs_collector, firms_collector


def test_rss_passes_published_at():
    src = inspect.getsource(rss_collector)
    assert "published_at=published_dt" in src


def test_usgs_passes_occurred_at():
    src = inspect.getsource(usgs_collector)
    assert "occurred_at=" in src


def test_firms_passes_observed_at():
    src = inspect.getsource(firms_collector)
    assert "observed_at=" in src
```

(Source-level assertions keep this task fast and free of live feeds; behavioral coverage of the resolution lives in Task 6.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_collector_time_passthrough.py -v`
Expected: FAIL — strings not present.

- [ ] **Step 3: RSS — pass `published_at` (`rss_collector.py:282`)**

```python
                enrichment = await process_item(
                    title=title,
                    text=embed_text,
                    url=link,
                    source="rss",
                    settings=settings,
                    redis_client=self._redis,
                    published_at=published_dt,
                )
```

- [ ] **Step 4: USGS — pass `occurred_at` (`usgs_collector.py:276`)**

The quake origin time is already computed as `event_time` (`usgs_collector.py:134`, stored at `event["event_time"]`):

```python
                await process_item(
                    title=title,
                    text=embed_text,
                    url=event["url"],
                    source="usgs",
                    settings=self.settings,
                    redis_client=self.redis,
                    occurred_at=event.get("event_time"),
                )
```

- [ ] **Step 5: FIRMS — pass `observed_at` (`firms_collector.py:191`)**

Build an ISO acquisition timestamp from `acq_date`+`acq_time` at the call site (FIRMS `acq_time` is `HHMM`):

```python
                        acq = row.get("acq_date", "")
                        hhmm = str(row.get("acq_time", "")).zfill(4)
                        observed = f"{acq}T{hhmm[:2]}:{hhmm[2:]}:00+00:00" if acq else None
                        await process_item(
                            title=title,
                            text=embed_text,
                            url=url,
                            source="firms",
                            settings=self.settings,
                            redis_client=self.redis,
                            observed_at=observed,
                        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_collector_time_passthrough.py -v && uv run ruff check feeds/`
Expected: PASS, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add services/data-ingestion/feeds/rss_collector.py services/data-ingestion/feeds/usgs_collector.py services/data-ingestion/feeds/firms_collector.py services/data-ingestion/tests/test_collector_time_passthrough.py
git commit -m "feat(ingestion): pass native source time (rss/usgs/firms) into process_item"
```

---

### Task 8: GDELT writer sets `timeline_at` on CREATE and MATCH

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py:21-46` (`MERGE_EVENT`)
- Test: `services/data-ingestion/tests/test_gdelt_timeline_at.py`

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_gdelt_timeline_at.py
from gdelt_raw.writers.neo4j_writer import MERGE_EVENT


def test_merge_event_sets_timeline_at_on_create_and_match():
    assert "timeline_at = datetime($date_added)" in MERGE_EVENT
    assert "time_basis = 'indexed'" in MERGE_EVENT
    # present in both ON CREATE and ON MATCH blocks
    create_block, _, match_block = MERGE_EVENT.partition("ON MATCH SET")
    assert "timeline_at" in create_block and "timeline_at" in match_block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_timeline_at.py -v`
Expected: FAIL — `timeline_at` absent.

- [ ] **Step 3: Edit `MERGE_EVENT`**

Add to the `ON CREATE SET` block (after `e.date_added = datetime($date_added),`):

```cypher
    e.timeline_at = datetime($date_added),
    e.time_basis = 'indexed',
```

And extend the `ON MATCH SET` block:

```cypher
  ON MATCH SET
    e.num_mentions = $num_mentions,
    e.num_sources = $num_sources,
    e.num_articles = $num_articles,
    e.timeline_at = datetime($date_added),
    e.time_basis = 'indexed'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_timeline_at.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/writers/neo4j_writer.py services/data-ingestion/tests/test_gdelt_timeline_at.py
git commit -m "feat(ingestion): GDELT writer stamps timeline_at on create+match"
```

---

### Task 9: Phase-3 backfill migration (idempotent, batched, one-shot)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/migrations/phase3_timeline_at.cypher`
- Modify: `services/data-ingestion/gdelt_raw/migrations/apply.py` (add `apply_phase3`)
- Create: `services/data-ingestion/gdelt_raw/migrations/run_phase3.py` (documented one-shot)
- Test: `services/data-ingestion/tests/test_migration_phase3.py`

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_migration_phase3.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from gdelt_raw.migrations import apply as mig


def test_phase3_cypher_is_idempotent_and_batched():
    text = mig.read_cypher_file("phase3_timeline_at.cypher")
    assert "IF NOT EXISTS" in text
    assert "IN TRANSACTIONS" in text
    assert "e.timeline_at IS NULL" in text


@pytest.mark.asyncio
async def test_apply_phase3_runs_statements_autocommit():
    # each statement runs in its own implicit/auto-commit session.run (no explicit tx)
    session = AsyncMock()
    session.run = AsyncMock()
    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    await mig.apply_phase3(driver)
    assert session.run.await_count >= 2  # index + backfill
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_migration_phase3.py -v`
Expected: FAIL — file + `apply_phase3` missing.

- [ ] **Step 3: Write the migration cypher**

```cypher
// services/data-ingestion/gdelt_raw/migrations/phase3_timeline_at.cypher
CREATE INDEX event_timeline_at IF NOT EXISTS
  FOR (e:Event) ON (e.timeline_at);
MATCH (e:GDELTEvent)
WHERE e.timeline_at IS NULL AND e.date_added IS NOT NULL
CALL { WITH e
  SET e.timeline_at = e.date_added, e.time_basis = 'indexed'
} IN TRANSACTIONS OF 10000 ROWS;
```

- [ ] **Step 4: Add `apply_phase3` to `apply.py`**

```python
async def apply_phase3(driver) -> None:
    """Backfill timeline_at on existing GDELT events. Idempotent + batched.

    Each statement runs in auto-commit mode (CALL {} IN TRANSACTIONS cannot run
    inside an explicit transaction). Re-running is safe (timeline_at IS NULL guard).
    """
    statements = [
        s.strip() for s in read_cypher_file("phase3_timeline_at.cypher").split(";")
        if s.strip()
    ]
    async with driver.session() as session:
        for stmt in statements:
            await session.run(stmt)
            log.info("phase3_applied", stmt=stmt[:60])
```

- [ ] **Step 5: Write the one-shot runner**

```python
# services/data-ingestion/gdelt_raw/migrations/run_phase3.py
"""One-shot: backfill timeline_at on existing GDELT events.

Run manually (NOT wired into the scheduler):
    cd services/data-ingestion && uv run python -m gdelt_raw.migrations.run_phase3
"""

import asyncio

from neo4j import AsyncGraphDatabase

from config import Settings
from gdelt_raw.migrations.apply import apply_phase3


async def main() -> None:
    settings = Settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_url, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        await apply_phase3(driver)
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
```

(If `config.Settings`/driver URL differs in data-ingestion, mirror how `pipeline.py` constructs Neo4j access — it uses `settings.neo4j_url`. Confirm the bolt vs http URL: `AsyncGraphDatabase.driver` needs the **bolt** URL; use `settings.neo4j_url` if that is bolt, else add a bolt setting.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_migration_phase3.py -v && uv run ruff check gdelt_raw/`
Expected: PASS, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add services/data-ingestion/gdelt_raw/migrations/phase3_timeline_at.cypher services/data-ingestion/gdelt_raw/migrations/apply.py services/data-ingestion/gdelt_raw/migrations/run_phase3.py services/data-ingestion/tests/test_migration_phase3.py
git commit -m "feat(ingestion): phase-3 timeline_at backfill migration (idempotent one-shot)"
```

---

## Frontend

### Task 10: Window contract types + `getTimeWindow` + `useTimeWindow`

**Files:**
- Modify: `services/frontend/src/types/index.ts` (add window types)
- Modify: `services/frontend/src/services/api.ts` (add `getTimeWindow`)
- Create: `services/frontend/src/hooks/useTimeWindow.ts`
- Test: `services/frontend/src/hooks/__tests__/useTimeWindow.test.ts`

- [ ] **Step 1: Add types to `src/types/index.ts`**

```ts
export interface WindowTrackPoint {
  ts_ms: number;
  lat: number;
  lon: number;
  altitude_m?: number | null;
  speed_ms?: number | null;
  heading?: number | null;
}

export interface WindowTrackSample {
  kind: "track";
  id: string;
  icao24?: string | null;
  callsign?: string | null;
  type_code?: string | null;
  military_branch?: string | null;
  registration?: string | null;
  points: WindowTrackPoint[];
}

export interface WindowEventSample {
  kind: "event";
  id: string;
  time: string;
  time_basis: string;
  title?: string | null;
  codebook_type?: string | null;
  severity?: string | null;
  lat?: number | null;
  lon?: number | null;
  location_name?: string | null;
  country?: string | null;
}

export type WindowSample = WindowEventSample | WindowTrackSample;

export interface WindowResponse {
  domain: "events" | "movements";
  tier: "coarse" | "fine";
  t_start: string;
  t_end: string;
  bbox: { west: number; south: number; east: number; north: number } | null;
  samples: WindowSample[];
  total_count: number;
  truncated: boolean;
}

export interface TimeWindowQuery {
  tStart: string;
  tEnd: string;
  domain?: "events" | "movements";
  tier?: "coarse" | "fine";
  movementKind?: "mil_aircraft" | "civil_aircraft" | "ship" | "satellite";
  bbox?: [number, number, number, number];
  limit?: number;
}
```

- [ ] **Step 2: Write the failing hook test**

```ts
// services/frontend/src/hooks/__tests__/useTimeWindow.test.ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useTimeWindow } from "../useTimeWindow";

afterEach(() => vi.restoreAllMocks());

const RESP = {
  domain: "movements", tier: "fine", t_start: "a", t_end: "b", bbox: null,
  samples: [{ kind: "track", id: "abc", icao24: "abc", points: [] }],
  total_count: 1, truncated: false,
} as const;

describe("useTimeWindow", () => {
  it("fetches when enabled with params", async () => {
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(RESP as never);
    const { result } = renderHook(() =>
      useTimeWindow(true, {
        tStart: "2026-05-01T00:00:00Z", tEnd: "2026-05-02T00:00:00Z",
        domain: "movements", tier: "fine", movementKind: "mil_aircraft",
      }),
    );
    await waitFor(() => expect(result.current.data?.samples.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("does not fetch when disabled", async () => {
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(RESP as never);
    renderHook(() =>
      useTimeWindow(false, { tStart: "a", tEnd: "b" }),
    );
    expect(spy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useTimeWindow.test.ts`
Expected: FAIL — `getTimeWindow`/`useTimeWindow` undefined.

- [ ] **Step 4: Add `getTimeWindow` to `api.ts`**

```ts
import type { WindowResponse, TimeWindowQuery } from "../types";

export async function getTimeWindow(
  q: TimeWindowQuery,
  signal?: AbortSignal,
): Promise<WindowResponse> {
  const p = new URLSearchParams({ t_start: q.tStart, t_end: q.tEnd });
  if (q.domain) p.set("domain", q.domain);
  if (q.tier) p.set("tier", q.tier);
  if (q.movementKind) p.set("movement_kind", q.movementKind);
  if (q.bbox) p.set("bbox", q.bbox.join(","));
  if (q.limit) p.set("limit", String(q.limit));
  return fetchJSON<WindowResponse>(`/timeline/window?${p.toString()}`, { signal });
}
```

- [ ] **Step 5: Write `useTimeWindow` (param-driven, AbortController + sequence guard)**

```ts
// services/frontend/src/hooks/useTimeWindow.ts
import { useEffect, useRef, useState } from "react";
import type { TimeWindowQuery, WindowResponse } from "../types";
import { getTimeWindow } from "../services/api";

// Param-driven (refetch on query change), following the reliability pattern:
// AbortController + sequence guard + skip-when-hidden. Optional refreshMs for live.
export function useTimeWindow(
  enabled: boolean,
  query: TimeWindowQuery,
  refreshMs = 0,
) {
  const [data, setData] = useState<WindowResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const seqRef = useRef(0);
  const key = JSON.stringify(query);

  useEffect(() => {
    if (!enabled) {
      setData(null);
      setLoading(false);
      return;
    }
    const seq = ++seqRef.current;
    const ctrl = new AbortController();
    const run = async () => {
      if (typeof document !== "undefined" && document.hidden) return;
      setLoading(true);
      try {
        const res = await getTimeWindow(query, ctrl.signal);
        if (seq === seqRef.current) setData(res);
      } catch {
        // keep stale data; aborts are expected on param change/unmount
      } finally {
        if (seq === seqRef.current) setLoading(false);
      }
    };
    void run();
    const timer = refreshMs > 0 ? setInterval(() => void run(), refreshMs) : null;
    return () => {
      ctrl.abort();
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key, refreshMs]);

  return { data, loading };
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useTimeWindow.test.ts && npm run type-check`
Expected: PASS, types clean.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/types/index.ts services/frontend/src/services/api.ts services/frontend/src/hooks/useTimeWindow.ts services/frontend/src/hooks/__tests__/useTimeWindow.test.ts
git commit -m "feat(frontend): windowed-data contract client (getTimeWindow + useTimeWindow)"
```

---

### Task 11: Canonical mil-track adapter + interpolation

**Files:**
- Create: `services/frontend/src/components/layers/milTrackAdapter.ts`
- Test: `services/frontend/src/components/layers/__tests__/milTrackAdapter.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// services/frontend/src/components/layers/__tests__/milTrackAdapter.test.ts
import { describe, it, expect } from "vitest";
import { fromLiveTrack, fromWindowTrack, positionAtTime } from "../milTrackAdapter";
import type { AircraftTrack, WindowTrackSample } from "../../../types";

const live: AircraftTrack = {
  icao24: "abc", callsign: "F1", type_code: "RQ4", military_branch: "USAF",
  registration: null,
  points: [
    { lat: 0, lon: 0, altitude_m: 100, speed_ms: 10, heading: 90, timestamp: 1000 },
    { lat: 10, lon: 0, altitude_m: 200, speed_ms: 10, heading: 90, timestamp: 2000 },
  ],
};

const win: WindowTrackSample = {
  kind: "track", id: "xyz", icao24: "xyz", callsign: null, type_code: null,
  military_branch: "RUAF", registration: null,
  points: [{ ts_ms: 5_000_000, lat: 1, lon: 1 }],
};

describe("milTrackAdapter", () => {
  it("live timestamp seconds -> ts_ms milliseconds", () => {
    const r = fromLiveTrack(live);
    expect(r.icao24).toBe("abc");
    expect(r.points[0].ts_ms).toBe(1_000_000);
  });

  it("window track maps id->icao24 and keeps ts_ms", () => {
    const r = fromWindowTrack(win);
    expect(r.icao24).toBe("xyz");
    expect(r.points[0].ts_ms).toBe(5_000_000);
  });

  it("before first point -> null (no marker)", () => {
    const r = fromLiveTrack(live);
    expect(positionAtTime(r.points, 500_000)).toBeNull();
  });

  it("between points -> linear interpolation", () => {
    const r = fromLiveTrack(live);
    const pos = positionAtTime(r.points, 1_500_000)!;
    expect(pos.lat).toBeCloseTo(5);
    expect(pos.alt).toBeCloseTo(150);
  });

  it("after last point -> clamp to last, no dead reckoning", () => {
    const r = fromLiveTrack(live);
    const pos = positionAtTime(r.points, 9_000_000)!;
    expect(pos.lat).toBe(10);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/milTrackAdapter.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the adapter**

```ts
// services/frontend/src/components/layers/milTrackAdapter.ts
import type { AircraftTrack, WindowTrackSample } from "../../types";

export interface MilTrackPoint {
  lat: number;
  lon: number;
  altitude_m: number | null;
  speed_ms: number | null;
  heading: number | null;
  ts_ms: number;
}

export interface MilTrackRender {
  icao24: string;
  callsign: string | null;
  type_code: string | null;
  military_branch: string | null;
  registration: string | null;
  points: MilTrackPoint[];
}

export function fromLiveTrack(t: AircraftTrack): MilTrackRender {
  return {
    icao24: t.icao24,
    callsign: t.callsign,
    type_code: t.type_code,
    military_branch: t.military_branch,
    registration: t.registration,
    points: t.points.map((p) => ({
      lat: p.lat, lon: p.lon, altitude_m: p.altitude_m,
      speed_ms: p.speed_ms, heading: p.heading,
      ts_ms: p.timestamp * 1000, // collector stores epoch seconds
    })),
  };
}

export function fromWindowTrack(s: WindowTrackSample): MilTrackRender {
  return {
    icao24: s.icao24 ?? s.id,
    callsign: s.callsign ?? null,
    type_code: s.type_code ?? null,
    military_branch: s.military_branch ?? null,
    registration: s.registration ?? null,
    points: s.points.map((p) => ({
      lat: p.lat, lon: p.lon,
      altitude_m: p.altitude_m ?? null, speed_ms: p.speed_ms ?? null,
      heading: p.heading ?? null, ts_ms: p.ts_ms,
    })),
  };
}

export interface InterpPos { lat: number; lon: number; alt: number; }

// Replay edge behavior (spec §7.3): before first -> null; between -> linear;
// after last -> clamp to last (no dead reckoning).
export function positionAtTime(points: MilTrackPoint[], tMs: number): InterpPos | null {
  if (points.length === 0 || tMs < points[0].ts_ms) return null;
  const last = points[points.length - 1];
  if (tMs >= last.ts_ms) return { lat: last.lat, lon: last.lon, alt: last.altitude_m ?? 0 };
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (tMs >= a.ts_ms && tMs <= b.ts_ms) {
      const span = b.ts_ms - a.ts_ms || 1;
      const f = (tMs - a.ts_ms) / span;
      return {
        lat: a.lat + (b.lat - a.lat) * f,
        lon: a.lon + (b.lon - a.lon) * f,
        alt: (a.altitude_m ?? 0) + ((b.altitude_m ?? 0) - (a.altitude_m ?? 0)) * f,
      };
    }
  }
  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/milTrackAdapter.test.ts`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/layers/milTrackAdapter.ts services/frontend/src/components/layers/__tests__/milTrackAdapter.test.ts
git commit -m "feat(frontend): canonical mil-track adapter + replay interpolation"
```

---

### Task 12: Global `TimeContext`

**Files:**
- Create: `services/frontend/src/state/TimeContext.tsx`
- Test: `services/frontend/src/state/__tests__/TimeContext.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// services/frontend/src/state/__tests__/TimeContext.test.tsx
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { TimeProvider, useTime } from "../TimeContext";

// viewer=null path: clock is internal/simulated, no Cesium needed.
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <TimeProvider viewer={null}>{children}</TimeProvider>
);

describe("TimeContext", () => {
  it("starts in live mode with getTimeMs ~ now", () => {
    const { result } = renderHook(() => useTime(), { wrapper });
    expect(result.current.mode).toBe("live");
    expect(Math.abs(result.current.getTimeMs() - Date.now())).toBeLessThan(2000);
  });

  it("seek sets cursor and bumps discontinuityEpoch (even forward)", () => {
    const { result } = renderHook(() => useTime(), { wrapper });
    const before = result.current.discontinuityEpoch;
    act(() => result.current.seek(1_700_000_000_000));
    expect(result.current.getTimeMs()).toBe(1_700_000_000_000);
    expect(result.current.discontinuityEpoch).toBe(before + 1);
  });

  it("setMode replay bumps discontinuityEpoch", () => {
    const { result } = renderHook(() => useTime(), { wrapper });
    const before = result.current.discontinuityEpoch;
    act(() => result.current.setMode("replay"));
    expect(result.current.mode).toBe("replay");
    expect(result.current.discontinuityEpoch).toBe(before + 1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/state/__tests__/TimeContext.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `TimeContext`**

```tsx
// services/frontend/src/state/TimeContext.tsx
import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ReactNode,
} from "react";
import * as Cesium from "cesium";

export type TimeMode = "live" | "replay";

interface TimeContextValue {
  mode: TimeMode;
  playing: boolean;
  speed: number;
  cursorMs: number; // throttled (~4 Hz) display value — do NOT use in hot loops
  discontinuityEpoch: number;
  getTimeMs: () => number; // hot path: ref-based, safe in per-frame loops
  seek: (ms: number) => void;
  setMode: (m: TimeMode) => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: number) => void;
}

const Ctx = createContext<TimeContextValue | null>(null);

const UI_THROTTLE_MS = 250; // ~4 Hz

export function TimeProvider({
  viewer,
  children,
}: {
  viewer: Cesium.Viewer | null;
  children: ReactNode;
}) {
  const timeRef = useRef<number>(Date.now());
  const lastUiRef = useRef<number>(0);
  const [cursorMs, setCursorMs] = useState<number>(timeRef.current);
  const [mode, setModeState] = useState<TimeMode>("live");
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeedState] = useState(1);
  const [discontinuityEpoch, setEpoch] = useState(0);

  const getTimeMs = useCallback(() => timeRef.current, []);

  // Drive timeRef from the Cesium clock when a viewer exists; otherwise simulate.
  useEffect(() => {
    if (viewer && !viewer.isDestroyed()) {
      const clock = viewer.clock;
      const remove = clock.onTick.addEventListener((c) => {
        const ms = Cesium.JulianDate.toDate(c.currentTime).getTime();
        timeRef.current = ms;
        const t = performance.now();
        if (t - lastUiRef.current >= UI_THROTTLE_MS) {
          lastUiRef.current = t;
          setCursorMs(ms);
        }
      });
      return () => remove();
    }
    // Fallback (tests / no viewer): tick from wall clock when live+playing.
    const id = setInterval(() => {
      if (mode === "live" && playing) {
        timeRef.current = Date.now();
        setCursorMs(timeRef.current);
      }
    }, UI_THROTTLE_MS);
    return () => clearInterval(id);
  }, [viewer, mode, playing]);

  const bumpEpoch = useCallback(() => setEpoch((e) => e + 1), []);

  const seek = useCallback(
    (ms: number) => {
      timeRef.current = ms;
      setCursorMs(ms);
      if (viewer && !viewer.isDestroyed()) {
        viewer.clock.currentTime = Cesium.JulianDate.fromDate(new Date(ms));
      }
      bumpEpoch(); // every explicit seek, including forward
    },
    [viewer, bumpEpoch],
  );

  const setMode = useCallback(
    (m: TimeMode) => {
      setModeState(m);
      if (viewer && !viewer.isDestroyed()) {
        const clock = viewer.clock;
        if (m === "live") {
          clock.clockRange = Cesium.ClockRange.UNBOUNDED;
          clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK;
          clock.shouldAnimate = true;
          timeRef.current = Date.now();
          clock.currentTime = Cesium.JulianDate.now();
        } else {
          clock.clockRange = Cesium.ClockRange.CLAMPED;
          clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER;
        }
      }
      bumpEpoch();
    },
    [viewer, bumpEpoch],
  );

  const play = useCallback(() => {
    setPlaying(true);
    if (viewer && !viewer.isDestroyed()) viewer.clock.shouldAnimate = true;
  }, [viewer]);

  const pause = useCallback(() => {
    setPlaying(false);
    if (viewer && !viewer.isDestroyed()) viewer.clock.shouldAnimate = false;
  }, [viewer]);

  const setSpeed = useCallback(
    (s: number) => {
      setSpeedState(s);
      if (viewer && !viewer.isDestroyed()) viewer.clock.multiplier = s;
    },
    [viewer],
  );

  const value: TimeContextValue = {
    mode, playing, speed, cursorMs, discontinuityEpoch,
    getTimeMs, seek, setMode, play, pause, setSpeed,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTime(): TimeContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTime must be used within TimeProvider");
  return v;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/state/__tests__/TimeContext.test.tsx && npm run type-check`
Expected: PASS, types clean.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/state/TimeContext.tsx services/frontend/src/state/__tests__/TimeContext.test.tsx
git commit -m "feat(frontend): global TimeContext (ref hot-path + throttled UI + discontinuityEpoch)"
```

---

### Task 13: Make `MilAircraftLayer` time-aware

**Files:**
- Modify: `services/frontend/src/components/layers/MilAircraftLayer.tsx`
- Test: `services/frontend/src/components/layers/__tests__/MilAircraftLayer.render.test.ts` (pure-logic guard; full Cesium render is verified manually)

> The layer's Cesium rendering is hard to unit-test without a WebGL context; the interpolation logic it relies on is already covered in Task 11. This task adds a small guard test that the component accepts the render model + a `getTimeMs` prop, then does the imperative wiring.

- [ ] **Step 1: Write the failing test (prop/type contract)**

```ts
// services/frontend/src/components/layers/__tests__/MilAircraftLayer.render.test.ts
import { describe, it, expect } from "vitest";
import { MilAircraftLayer } from "../MilAircraftLayer";
import type { MilTrackRender } from "../milTrackAdapter";

describe("MilAircraftLayer contract", () => {
  it("is a function component accepting render-model tracks", () => {
    expect(typeof MilAircraftLayer).toBe("function");
    const t: MilTrackRender = {
      icao24: "abc", callsign: null, type_code: null,
      military_branch: "USAF", registration: null, points: [],
    };
    // type-level assertion: tracks is MilTrackRender[]
    const props = { viewer: null, tracks: [t], visible: true, getTimeMs: () => 0, discontinuityEpoch: 0 };
    expect(props.tracks[0].icao24).toBe("abc");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/MilAircraftLayer.render.test.ts`
Expected: FAIL — `MilAircraftLayer` props don't yet include `getTimeMs`/`discontinuityEpoch`, type error.

- [ ] **Step 3: Retype props + add the tick loop**

Update the props interface and imports:

```tsx
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import { glyphColor } from "./glyphTokens";
import { positionAtTime, type MilTrackRender } from "./milTrackAdapter";

// ... keep branchColor() and createJetIcon() unchanged ...

interface MilAircraftLayerProps {
  viewer: Cesium.Viewer | null;
  tracks: MilTrackRender[];
  visible: boolean;
  getTimeMs: () => number;
  discontinuityEpoch: number;
  onSelect?: (t: MilTrackRender) => void;
}
```

Replace the second `useEffect` (the one keyed on `[tracks, visible, viewer]`) with a build step that draws the full polyline (history) once per track-change, plus a `clock.onTick` subscription that moves each billboard to `positionAtTime(track.points, getTimeMs())`:

```tsx
export function MilAircraftLayer({
  viewer, tracks, visible, getTimeMs, discontinuityEpoch, onSelect,
}: MilAircraftLayerProps) {
  const polyCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, MilTrackRender>>(new Map());
  const billboardMapRef = useRef<Map<string, { bb: Cesium.Billboard; track: MilTrackRender }>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const tickRemoveRef = useRef<Cesium.Event.RemoveCallback | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // (init effect: collections + pick handler — same as before, but idMap stores MilTrackRender)
  // ... keep the existing init useEffect, changing the generic type to MilTrackRender ...

  // Build polylines + billboards when tracks/visibility/discontinuity change.
  useEffect(() => {
    const pc = polyCollectionRef.current;
    const bc = billboardCollectionRef.current;
    if (!pc || !bc) return;
    pc.removeAll();
    bc.removeAll();
    idMapRef.current.clear();
    billboardMapRef.current.clear(); // reset render cache on tracks/discontinuity
    if (!visible) return;

    for (const t of tracks) {
      if (t.points.length === 0) continue;
      const color = branchColor(t.military_branch);
      if (t.points.length >= 2) {
        const arr: number[] = [];
        for (const p of t.points) arr.push(p.lon, p.lat, p.altitude_m ?? 0);
        const poly = pc.add({
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(arr),
          width: 1.5,
          material: Cesium.Material.fromType("Color", { color: color.withAlpha(0.6) }),
        });
        idMapRef.current.set(poly as unknown as object, t);
      }
      const bb = bc.add({
        position: Cesium.Cartesian3.fromDegrees(t.points[0].lon, t.points[0].lat, 0),
        image: createJetIcon(color, 24),
        scale: 0.8,
        alignedAxis: Cesium.Cartesian3.UNIT_Z,
        eyeOffset: new Cesium.Cartesian3(0, 0, -40),
        show: false, // shown once positioned by the tick loop
      });
      idMapRef.current.set(bb as unknown as object, t);
      billboardMapRef.current.set(t.icao24, { bb, track: t });
    }
  }, [tracks, visible, discontinuityEpoch]);

  // Move billboards to the interpolated position at the clock cursor every frame.
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (tickRemoveRef.current) { tickRemoveRef.current(); tickRemoveRef.current = null; }
    const remove = viewer.clock.onTick.addEventListener(() => {
      const t = getTimeMs();
      for (const { bb, track } of billboardMapRef.current.values()) {
        const pos = positionAtTime(track.points, t);
        if (!pos) { bb.show = false; continue; }
        bb.show = true;
        bb.position = Cesium.Cartesian3.fromDegrees(pos.lon, pos.lat, pos.alt);
      }
    });
    tickRemoveRef.current = remove;
    return () => { if (tickRemoveRef.current) { tickRemoveRef.current(); tickRemoveRef.current = null; } };
  }, [viewer, getTimeMs]);

  return null;
}
```

(Keep `branchColor`, `createJetIcon` exports. The pick handler's `idMapRef.get(...)` now yields a `MilTrackRender`; update `onSelect`'s type accordingly. Remove the now-unused `trackToPolylinePositions`/`AircraftPoint` import, or repoint it to `MilTrackPoint`.)

- [ ] **Step 4: Run test + type-check + full frontend suite**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/MilAircraftLayer.render.test.ts && npm run type-check`
Expected: PASS, types clean.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/layers/MilAircraftLayer.tsx services/frontend/src/components/layers/__tests__/MilAircraftLayer.render.test.ts
git commit -m "feat(frontend): time-aware MilAircraftLayer (clock-driven interpolation)"
```

---

### Task 14: Two-tier scrubber shell

**Files:**
- Create: `services/frontend/src/components/time/TwoTierScrubber.tsx`
- Test: `services/frontend/src/components/time/__tests__/TwoTierScrubber.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// services/frontend/src/components/time/__tests__/TwoTierScrubber.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TwoTierScrubber } from "../TwoTierScrubber";
import type { WindowEventSample } from "../../../types";

const ev: WindowEventSample = {
  kind: "event", id: "ev1", time: "2026-05-01T06:00:00Z", time_basis: "indexed",
  title: "Airstrike", codebook_type: "military.airstrike", severity: "high",
};

describe("TwoTierScrubber", () => {
  it("renders an event tick and selecting it calls onSelectEvent", () => {
    const onSelectEvent = vi.fn();
    render(
      <TwoTierScrubber
        events={[ev]} mode="live" cursorMs={Date.parse(ev.time)}
        onSelectEvent={onSelectEvent} onSeek={vi.fn()} onToggleMode={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Airstrike/i }));
    expect(onSelectEvent).toHaveBeenCalledWith(ev);
  });

  it("shows replay empty state when no events", () => {
    render(
      <TwoTierScrubber
        events={[]} mode="replay" cursorMs={0}
        onSelectEvent={vi.fn()} onSeek={vi.fn()} onToggleMode={vi.fn()}
      />,
    );
    expect(screen.getByText(/no events in window/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/time/__tests__/TwoTierScrubber.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the scrubber shell**

```tsx
// services/frontend/src/components/time/TwoTierScrubber.tsx
import type { WindowEventSample } from "../../types";

interface TwoTierScrubberProps {
  events: WindowEventSample[];
  mode: "live" | "replay";
  cursorMs: number;
  onSelectEvent: (e: WindowEventSample) => void;
  onSeek: (ms: number) => void;
  onToggleMode: () => void;
}

// Functional shell only — visual design goes through the Hlíðskjalf system later.
export function TwoTierScrubber({
  events, mode, cursorMs, onSelectEvent, onSeek, onToggleMode,
}: TwoTierScrubberProps) {
  return (
    <section
      aria-label="time scrubber"
      style={{
        position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)",
        display: "flex", flexDirection: "column", gap: 6, padding: "8px 12px",
        background: "var(--hl-panel-bg, rgba(10,10,12,0.7))",
        backdropFilter: "blur(var(--hl-panel-blur, 12px))",
        border: "1px solid var(--granite, #333)", borderRadius: 6,
        fontFamily: "var(--hl-font-mono, monospace)", fontSize: 11, color: "#ddd",
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button type="button" onClick={onToggleMode} aria-label="toggle mode">
          {mode === "live" ? "● LIVE" : "▶ REPLAY"}
        </button>
        <span>{new Date(cursorMs).toISOString().replace("T", " ").slice(0, 19)}Z</span>
      </div>

      {/* Coarse tier: event ticks */}
      <div role="group" aria-label="event timeline" style={{ display: "flex", gap: 4, flexWrap: "wrap", maxWidth: 520 }}>
        {events.length === 0 ? (
          <span style={{ opacity: 0.6 }}>no events in window</span>
        ) : (
          events.map((e) => (
            <button
              key={e.id}
              type="button"
              title={`${e.time} · ${e.time_basis}`}
              onClick={() => { onSelectEvent(e); onSeek(Date.parse(e.time)); }}
              style={{ padding: "1px 4px", fontSize: 10 }}
            >
              {e.title ?? e.codebook_type ?? e.id}
            </button>
          ))
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/time/__tests__/TwoTierScrubber.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/time/TwoTierScrubber.tsx services/frontend/src/components/time/__tests__/TwoTierScrubber.test.tsx
git commit -m "feat(frontend): two-tier scrubber shell (coarse event tier + mode toggle)"
```

---

### Task 15: Wire WorldviewPage (provider + scrubber + live/replay switch)

**Files:**
- Modify: `services/frontend/src/pages/WorldviewPage.tsx` (the mil-tracks hook at `:364`, plus provider + scrubber mount)
- Test: manual (browser) — see Verification.

> This task is integration glue; its behavior is verified end-to-end in the browser. Keep the edits minimal and typed.

- [ ] **Step 1: Wrap the page subtree in `TimeProvider`**

At the top of the rendered tree (where the Cesium `viewer` is available), wrap with `<TimeProvider viewer={viewer}>`. Inside, read the clock via `useTime()` in a child component (provider must be an ancestor of consumers).

- [ ] **Step 2: Select the mil-track source by mode**

Replace the single live hook (`:364`) with a mode-aware source. Live keeps `useAircraftTracks`; replay uses `useTimeWindow(...)`. Normalize both through the adapter:

```tsx
import { fromLiveTrack, fromWindowTrack, type MilTrackRender } from "../components/layers/milTrackAdapter";
import { useTimeWindow } from "../hooks/useTimeWindow";
import { useTime } from "../state/TimeContext";

// inside the component that is a child of <TimeProvider>:
const { mode, cursorMs, getTimeMs, discontinuityEpoch, seek, setMode } = useTime();

const { tracks: liveTracks } = useAircraftTracks(layers.milAircraft && mode === "live");

const replayWindow = useMemo(() => ({
  tStart: new Date(cursorMs - 6 * 3600_000).toISOString(),
  tEnd: new Date(cursorMs).toISOString(),
  domain: "movements" as const, tier: "fine" as const, movementKind: "mil_aircraft" as const,
}), [/* recompute when the selected coarse window changes, not every cursor tick */ selectedWindowKey]);

const { data: replayData } = useTimeWindow(layers.milAircraft && mode === "replay", replayWindow);

const milRender: MilTrackRender[] = mode === "live"
  ? liveTracks.map(fromLiveTrack)
  : (replayData?.samples ?? [])
      .filter((s): s is WindowTrackSample => s.kind === "track")
      .map(fromWindowTrack);
```

(Use a stable `selectedWindowKey` — the clicked event's window — so replay does not refetch on every cursor frame. In the absence of a selection, default to the last 6h around `cursorMs`.)

- [ ] **Step 3: Pass the render model + clock to `MilAircraftLayer`**

```tsx
<MilAircraftLayer
  viewer={viewer}
  tracks={milRender}
  visible={layers.milAircraft}
  getTimeMs={getTimeMs}
  discontinuityEpoch={discontinuityEpoch}
  onSelect={(t) => { /* existing inspector open, now typed MilTrackRender */ }}
/>
```

- [ ] **Step 4: Mount the scrubber**

```tsx
<TwoTierScrubber
  events={coarseEvents}            // from useTimeWindow('events','coarse'), live-refreshed
  mode={mode}
  cursorMs={cursorMs}
  onSelectEvent={(e) => { setSelectedWindow(e); setMode("replay"); }}
  onSeek={seek}
  onToggleMode={() => setMode(mode === "live" ? "replay" : "live")}
/>
```

Coarse events come from `useTimeWindow(true, { tStart, tEnd, domain: "events", tier: "coarse" }, 30_000)` over a rolling recent window.

- [ ] **Step 5: Type-check + build + full suite**

Run: `cd services/frontend && npm run type-check && npm run test && npm run build`
Expected: type-check clean, all Vitest green, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/pages/WorldviewPage.tsx
git commit -m "feat(frontend): wire TimeProvider + two-tier scrubber + live/replay mil-tracks"
```

---

## Final verification (end-to-end)

- [ ] **Backend:** `cd services/backend && uv run pytest tests/unit/test_timeline_router.py tests/unit/test_timeline_models.py tests/unit/test_timeline_params.py -v && uv run ruff check app/`
- [ ] **Data-ingestion:** `cd services/data-ingestion && uv run pytest tests/test_pipeline_timeline_at.py tests/test_collector_time_passthrough.py tests/test_gdelt_timeline_at.py tests/test_migration_phase3.py tests/test_pipeline.py -v && uv run ruff check .`
- [ ] **Run the backfill once** (operational one-shot, against a DB copy first): `cd services/data-ingestion && uv run python -m gdelt_raw.migrations.run_phase3` — re-run to confirm idempotency (no further writes).
- [ ] **Frontend:** `cd services/frontend && npm run test && npm run type-check && npm run build`
- [ ] **Browser:** `npm run dev` →
  - Live mode shows identical mil-aircraft behavior (Profiler: no per-frame React re-renders).
  - Coarse scrubber shows real graph events (GDELT + new RSS/USGS/FIRMS); `time_basis` visible on hover.
  - Clicking an event enters replay and scopes the fine window; a **mil-track visibly scrubs a historical flight path**; the marker hides before the first point and clamps at the last (no dead reckoning past the end).
  - Toggling back to LIVE returns losslessly.

---

## Self-Review

**Spec coverage:** clock hot/UI split (Task 12) · windowed contract + status matrix (Tasks 1–5) · events branch w/ GDELT-nullable + fallback id (Task 3) · mil-aircraft movements w/ absolute window + bbox track-selection + ts_ms (Task 4) · `timeline_at`/`time_basis` honest semantics + LLM validator (Task 6) · native source time passthrough (Task 7) · GDELT writer create+match (Task 8) · idempotent batched one-shot migration (Task 9) · contract client (Task 10) · canonical adapter + replay edge behavior (Task 11) · time-aware layer w/ clock.onTick (Task 13) · scrubber shell (Task 14) · live/replay wiring (Task 15). All spec sections map to a task.

**Type consistency:** `MilTrackRender`/`MilTrackPoint` (Task 11) are consumed unchanged by `MilAircraftLayer` (Task 13) and produced by the adapter from `AircraftTrack` (live) and `WindowTrackSample` (Task 10). `WindowResponse`/`EventSample`/`TrackSample` field names match between backend models (Task 1) and frontend types (Task 10). `getTimeMs`/`discontinuityEpoch` signatures match between `TimeContext` (Task 12) and `MilAircraftLayer` props (Task 13).

**Known follow-ups (Slice 1+, not blockers):** event geo coverage for full bbox; legacy (non-GDELT) `timeline_at` backfill; the remaining 8 collectors' native times; `events_in_window` agent tool. Documented in the spec.
