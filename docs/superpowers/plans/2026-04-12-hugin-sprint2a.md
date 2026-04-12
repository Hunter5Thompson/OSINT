# Hugin Sprint 2a: Conflict + Disaster Collectors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five new data collectors (EONET, GDACS, HAPI, NOAA NHC, PortWatch) with two Globe-Layer visualizations (EONET, GDACS). Last feature sprint before app restructure.

**Architecture:** Collectors inherit BaseCollector, ingest to Qdrant/Neo4j via Pipeline. EONET/GDACS use mutable-event upsert (first-seen → Pipeline, updates → Qdrant-only). Two backend routers with Redis cache serve EONET/GDACS to frontend. Frontend uses polling hooks + BillboardCollection layers in INGESTION_LAYERS.

**Tech Stack:** Python 3.12, FastAPI, httpx, Qdrant, APScheduler, React 19, TypeScript, CesiumJS, Vitest

**Spec:** `docs/superpowers/specs/2026-04-12-hugin-sprint2a-design.md`

---

## File Structure

All paths relative to repo root.

### New files:
| File | Responsibility |
|------|---------------|
| `services/data-ingestion/feeds/eonet_collector.py` | NASA EONET natural events collector (mutable upsert) |
| `services/data-ingestion/feeds/gdacs_collector.py` | GDACS disaster alerts collector (mutable upsert) |
| `services/data-ingestion/feeds/hapi_collector.py` | HAPI humanitarian conflict data collector |
| `services/data-ingestion/feeds/noaa_nhc_collector.py` | NOAA NHC tropical weather collector |
| `services/data-ingestion/feeds/portwatch_collector.py` | IMF PortWatch chokepoint flows collector |
| `services/data-ingestion/tests/test_eonet_collector.py` | EONET collector tests |
| `services/data-ingestion/tests/test_gdacs_collector.py` | GDACS collector tests |
| `services/data-ingestion/tests/test_hapi_collector.py` | HAPI collector tests |
| `services/data-ingestion/tests/test_noaa_nhc_collector.py` | NOAA NHC collector tests |
| `services/data-ingestion/tests/test_portwatch_collector.py` | PortWatch collector tests |
| `services/backend/app/routers/eonet.py` | EONET backend API router |
| `services/backend/app/routers/gdacs.py` | GDACS backend API router |
| `services/frontend/src/hooks/useEONETEvents.ts` | EONET polling hook |
| `services/frontend/src/hooks/useGDACSEvents.ts` | GDACS polling hook |
| `services/frontend/src/components/layers/EONETLayer.tsx` | CesiumJS EONET globe layer |
| `services/frontend/src/components/layers/GDACSLayer.tsx` | CesiumJS GDACS globe layer |

### Modified files:
| File | Change |
|------|--------|
| `services/data-ingestion/config.py` | Add 5 new settings fields |
| `services/data-ingestion/scheduler.py` | Add 5 new collector jobs + startup |
| `services/backend/app/main.py` | Register eonet + gdacs routers |
| `services/frontend/src/types/index.ts` | EONETEvent + GDACSEvent types, LayerVisibility |
| `services/frontend/src/services/api.ts` | `getEONETEvents()` + `getGDACSEvents()` |
| `services/frontend/src/components/ui/OperationsPanel.tsx` | Add to INGESTION_LAYERS |
| `services/frontend/src/components/ui/SelectionPanel.tsx` | Add EONET + GDACS content |
| `services/frontend/src/App.tsx` | Wire hooks, render layers |

---

### Task 1: Config + Settings

**Files:**
- Modify: `services/data-ingestion/config.py`

- [ ] **Step 1: Add new settings fields**

Add after the `correlation_interval_hours` field (line 86) in `config.py`:

```python
    # --- Hugin P1 Collectors (Sprint 2a) ---

    # EONET (NASA Earth Observatory Natural Events)
    eonet_interval_hours: int = 2

    # GDACS (Global Disaster Alerts)
    gdacs_interval_hours: int = 2

    # HAPI (Humanitarian Data Exchange)
    hapi_app_identifier: str = ""  # Base64 encoded email
    hapi_interval_hours: int = 24

    # NOAA NHC (Tropical Weather)
    noaa_nhc_interval_hours: int = 3

    # PortWatch (IMF Chokepoint Flows)
    portwatch_interval_hours: int = 6
```

- [ ] **Step 2: Verify settings load**

Run: `cd services/data-ingestion && python -c "from config import settings; print(settings.eonet_interval_hours, settings.gdacs_interval_hours)"`
Expected: `2 2`

- [ ] **Step 3: Commit**

```bash
git add services/data-ingestion/config.py
git commit -m "feat(ingestion): add Sprint 2a collector settings"
```

---

### Task 2: Frontend Types + API Client

**Files:**
- Modify: `services/frontend/src/types/index.ts`
- Modify: `services/frontend/src/services/api.ts`
- Modify: `services/frontend/src/App.tsx` (LayerVisibility defaults)

- [ ] **Step 1: Add EONET + GDACS types**

Add to `services/frontend/src/types/index.ts` before the `// ── UI State Types ──` section:

```typescript
export interface EONETEvent {
  id: string;
  title: string;
  category: string;
  status: string;
  latitude: number;
  longitude: number;
  event_date: string;
}

export interface GDACSEvent {
  id: string;
  event_type: string;
  event_name: string;
  alert_level: string;
  severity: number;
  country: string;
  latitude: number;
  longitude: number;
  from_date: string;
  to_date: string;
}
```

- [ ] **Step 2: Extend LayerVisibility**

Add after `refineries: boolean;` in the `LayerVisibility` interface:

```typescript
  eonet: boolean;
  gdacs: boolean;
```

- [ ] **Step 3: Fix LayerVisibility literals in App.tsx**

In `src/App.tsx`, add to the `useState<LayerVisibility>` initial value (after `refineries: false,`):

```typescript
    eonet: false,
    gdacs: false,
```

And in the `getConfig().catch()` fallback `default_layers`:

```typescript
        eonet: false, gdacs: false,
```

- [ ] **Step 4: Add API functions**

Add to the end of `services/frontend/src/services/api.ts`:

```typescript
export async function getEONETEvents(sinceHours = 168): Promise<EONETEvent[]> {
  return fetchJSON<EONETEvent[]>(`/eonet/events?since_hours=${sinceHours}`);
}

export async function getGDACSEvents(sinceHours = 168): Promise<GDACSEvent[]> {
  return fetchJSON<GDACSEvent[]>(`/gdacs/events?since_hours=${sinceHours}`);
}
```

Add `EONETEvent` and `GDACSEvent` to the import block at the top of `api.ts`.

- [ ] **Step 5: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: Clean (0 errors).

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/types/index.ts services/frontend/src/services/api.ts services/frontend/src/App.tsx
git commit -m "feat(frontend): add EONET + GDACS types, API functions, LayerVisibility"
```

---

### Task 3: EONET Collector + Tests

**Files:**
- Create: `services/data-ingestion/feeds/eonet_collector.py`
- Create: `services/data-ingestion/tests/test_eonet_collector.py`

- [ ] **Step 1: Write failing tests**

Create `services/data-ingestion/tests/test_eonet_collector.py`:

```python
"""Tests for EONET natural events collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.eonet_collector import EONETCollector

SAMPLE_RESPONSE = {
    "events": [
        {
            "id": "EONET_1234",
            "title": "Wildfire - California",
            "categories": [{"id": "wildfires", "title": "Wildfires"}],
            "geometry": [
                {
                    "date": "2026-04-10T12:00:00Z",
                    "type": "Point",
                    "coordinates": [-118.5, 34.0],
                }
            ],
            "closed": None,
        },
        {
            "id": "EONET_5678",
            "title": "Volcano - Etna",
            "categories": [{"id": "volcanoes", "title": "Volcanoes"}],
            "geometry": [
                {
                    "date": "2026-04-09T08:00:00Z",
                    "type": "Point",
                    "coordinates": [15.0, 37.75],
                }
            ],
            "closed": "2026-04-11T00:00:00Z",
        },
    ]
}


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = EONETCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestEONETParser:
    def test_parse_events_extracts_all_fields(self, collector):
        events = collector._parse_events(SAMPLE_RESPONSE)
        assert len(events) == 2

        e1 = events[0]
        assert e1["eonet_id"] == "EONET_1234"
        assert e1["title"] == "Wildfire - California"
        assert e1["category"] == "wildfires"
        assert e1["status"] == "open"
        assert e1["latitude"] == 34.0
        assert e1["longitude"] == -118.5
        assert e1["event_date"] == "2026-04-10T12:00:00Z"

    def test_parse_events_closed_status(self, collector):
        events = collector._parse_events(SAMPLE_RESPONSE)
        e2 = events[1]
        assert e2["status"] == "closed"
        assert e2["category"] == "volcanoes"

    def test_parse_events_empty_input(self, collector):
        events = collector._parse_events({"events": []})
        assert events == []

    def test_parse_events_uses_latest_geometry(self, collector):
        response = {
            "events": [
                {
                    "id": "E1",
                    "title": "Storm",
                    "categories": [{"id": "severeStorms"}],
                    "geometry": [
                        {"date": "2026-04-08T00:00:00Z", "type": "Point", "coordinates": [10.0, 20.0]},
                        {"date": "2026-04-10T00:00:00Z", "type": "Point", "coordinates": [11.0, 21.0]},
                    ],
                    "closed": None,
                }
            ]
        }
        events = collector._parse_events(response)
        assert events[0]["latitude"] == 21.0
        assert events[0]["longitude"] == 11.0
        assert events[0]["event_date"] == "2026-04-10T00:00:00Z"


class TestEONETContentHash:
    def test_stable_hash_for_same_id(self, collector):
        h1 = collector._eonet_content_hash("EONET_1234")
        h2 = collector._eonet_content_hash("EONET_1234")
        assert h1 == h2

    def test_different_hash_for_different_id(self, collector):
        h1 = collector._eonet_content_hash("EONET_1234")
        h2 = collector._eonet_content_hash("EONET_5678")
        assert h1 != h2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && uv run pytest tests/test_eonet_collector.py -v`
Expected: FAIL — module `feeds.eonet_collector` not found.

- [ ] **Step 3: Implement EONET collector**

Create `services/data-ingestion/feeds/eonet_collector.py`:

```python
"""EONET — NASA Earth Observatory Natural Event Tracker.

Collects natural events (wildfires, volcanoes, storms, floods, etc.)
and upserts to Qdrant. Mutable events: first-seen goes through Pipeline,
updates are Qdrant-only to avoid Neo4j duplicates.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import structlog

from config import settings
from feeds.base import BaseCollector

log = structlog.get_logger("eonet_collector")

_EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"


class EONETCollector(BaseCollector):
    """Collect natural events from NASA EONET API."""

    def _eonet_content_hash(self, event_id: str) -> int:
        """Stable point ID from EONET event ID."""
        digest = hashlib.sha256(event_id.encode()).hexdigest()
        return int(digest[:16], 16)

    def _parse_events(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse EONET response into normalized event dicts."""
        events: list[dict[str, Any]] = []
        for event in data.get("events", []):
            geometries = event.get("geometry", [])
            if not geometries:
                continue

            # Use latest geometry (most recent position)
            latest = max(geometries, key=lambda g: g.get("date", ""))
            coords = latest.get("coordinates", [])
            if len(coords) < 2:
                continue

            categories = event.get("categories", [])
            category = categories[0].get("id", "unknown") if categories else "unknown"

            events.append({
                "eonet_id": event["id"],
                "title": event.get("title", ""),
                "category": category,
                "status": "closed" if event.get("closed") else "open",
                "latitude": coords[1],  # GeoJSON: [lon, lat]
                "longitude": coords[0],
                "event_date": latest.get("date", ""),
            })
        return events

    async def collect(self) -> None:
        """Fetch EONET events, upsert to Qdrant (mutable-event pattern)."""
        await self._ensure_collection()

        params = {"status": "open", "days": 30}
        try:
            resp = await self.http.get(_EONET_URL, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            log.exception("eonet_fetch_failed")
            return

        events = self._parse_events(data)
        log.info("eonet_parsed", count=len(events))

        if not events:
            return

        new_count = 0
        update_count = 0
        points = []

        for event in events:
            point_id = self._eonet_content_hash(event["eonet_id"])
            description = f"{event['title']} - {event['category']} event"

            # Check if already exists in Qdrant
            existing = await asyncio.to_thread(
                self.qdrant.retrieve,
                collection_name=settings.qdrant_collection,
                ids=[point_id],
            )
            is_new = len(existing) == 0

            if is_new:
                # First-seen: run through Pipeline for Neo4j
                try:
                    from pipeline import process_item
                    await process_item(
                        title=event["title"],
                        text=description,
                        url=f"https://eonet.gsfc.nasa.gov/api/v3/events/{event['eonet_id']}",
                        source="eonet",
                        settings=settings,
                        redis_client=self.redis_client,
                    )
                except Exception:
                    log.warning("eonet_pipeline_failed", event_id=event["eonet_id"])
                new_count += 1
            else:
                update_count += 1

            # Always upsert to Qdrant (new or update)
            vector = await self._embed(description)
            if vector is None:
                continue

            payload = {
                "source": "eonet",
                **event,
                "ingested_epoch": time.time(),
                "description": description,
            }
            point = self._build_point(
                point_id=point_id,
                vector=vector,
                payload=payload,
            )
            points.append(point)

        if points:
            await self._batch_upsert(points)

        log.info(
            "eonet_complete",
            total=len(events),
            new=new_count,
            updated=update_count,
            upserted=len(points),
        )
```

- [ ] **Step 4: Run tests**

Run: `cd services/data-ingestion && uv run pytest tests/test_eonet_collector.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/eonet_collector.py services/data-ingestion/tests/test_eonet_collector.py
git commit -m "feat(ingestion): add EONET natural events collector"
```

---

### Task 4: GDACS Collector + Tests

**Files:**
- Create: `services/data-ingestion/feeds/gdacs_collector.py`
- Create: `services/data-ingestion/tests/test_gdacs_collector.py`

- [ ] **Step 1: Write failing tests**

Create `services/data-ingestion/tests/test_gdacs_collector.py`:

```python
"""Tests for GDACS disaster alert collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.gdacs_collector import GDACSCollector

SAMPLE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [95.0, 3.5]},
            "properties": {
                "eventtype": "EQ",
                "eventid": "1001",
                "eventname": "Earthquake Indonesia",
                "alertlevel": "Red",
                "severity": {"value": 6.8},
                "country": "Indonesia",
                "fromdate": "2026-04-10",
                "todate": "2026-04-10",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-80.0, 25.0]},
            "properties": {
                "eventtype": "TC",
                "eventid": "2002",
                "eventname": "Tropical Cyclone Alpha",
                "alertlevel": "Orange",
                "severity": {"value": 4.2},
                "country": "United States",
                "fromdate": "2026-04-08",
                "todate": "2026-04-12",
            },
        },
    ],
}


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = GDACSCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestGDACSParser:
    def test_parse_features_extracts_all_fields(self, collector):
        events = collector._parse_features(SAMPLE_GEOJSON)
        assert len(events) == 2

        e1 = events[0]
        assert e1["gdacs_id"] == "EQ_1001"
        assert e1["event_type"] == "EQ"
        assert e1["event_name"] == "Earthquake Indonesia"
        assert e1["alert_level"] == "Red"
        assert e1["severity"] == 6.8
        assert e1["country"] == "Indonesia"
        assert e1["latitude"] == 3.5
        assert e1["longitude"] == 95.0

    def test_parse_features_tropical_cyclone(self, collector):
        events = collector._parse_features(SAMPLE_GEOJSON)
        e2 = events[1]
        assert e2["event_type"] == "TC"
        assert e2["alert_level"] == "Orange"

    def test_parse_features_empty_input(self, collector):
        events = collector._parse_features({"type": "FeatureCollection", "features": []})
        assert events == []


class TestGDACSContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._gdacs_content_hash("EQ", "1001")
        h2 = collector._gdacs_content_hash("EQ", "1001")
        assert h1 == h2

    def test_different_type_different_hash(self, collector):
        h1 = collector._gdacs_content_hash("EQ", "1001")
        h2 = collector._gdacs_content_hash("TC", "1001")
        assert h1 != h2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdacs_collector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement GDACS collector**

Create `services/data-ingestion/feeds/gdacs_collector.py`:

```python
"""GDACS — Global Disaster Alert and Coordination System.

Collects disaster events (earthquakes, cyclones, floods, volcanoes, droughts, wildfires).
Mutable events: first-seen through Pipeline, updates Qdrant-only.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import structlog

from config import settings
from feeds.base import BaseCollector

log = structlog.get_logger("gdacs_collector")

_GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"


class GDACSCollector(BaseCollector):
    """Collect disaster alerts from GDACS API."""

    def _gdacs_content_hash(self, event_type: str, event_id: str) -> int:
        digest = hashlib.sha256(f"{event_type}{event_id}".encode()).hexdigest()
        return int(digest[:16], 16)

    def _parse_features(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            if len(coords) < 2:
                continue

            event_type = str(props.get("eventtype", ""))
            event_id = str(props.get("eventid", ""))
            severity_obj = props.get("severity", {})
            severity = float(severity_obj.get("value", 0)) if isinstance(severity_obj, dict) else 0.0

            events.append({
                "gdacs_id": f"{event_type}_{event_id}",
                "event_type": event_type,
                "event_name": str(props.get("eventname", "")),
                "alert_level": str(props.get("alertlevel", "")),
                "severity": severity,
                "country": str(props.get("country", "")),
                "latitude": coords[1],
                "longitude": coords[0],
                "from_date": str(props.get("fromdate", "")),
                "to_date": str(props.get("todate", "")),
            })
        return events

    async def collect(self) -> None:
        await self._ensure_collection()

        try:
            resp = await self.http.get(_GDACS_URL, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            log.exception("gdacs_fetch_failed")
            return

        events = self._parse_features(data)
        log.info("gdacs_parsed", count=len(events))

        if not events:
            return

        new_count = 0
        update_count = 0
        points = []

        for event in events:
            point_id = self._gdacs_content_hash(event["event_type"], event["gdacs_id"].split("_")[-1])
            description = f"{event['event_name']} - {event['event_type']} alert ({event['alert_level']})"

            existing = await asyncio.to_thread(
                self.qdrant.retrieve,
                collection_name=settings.qdrant_collection,
                ids=[point_id],
            )
            is_new = len(existing) == 0

            if is_new:
                try:
                    from pipeline import process_item
                    await process_item(
                        title=event["event_name"],
                        text=description,
                        url=f"https://www.gdacs.org/report.aspx?eventtype={event['event_type']}&eventid={event['gdacs_id'].split('_')[-1]}",
                        source="gdacs",
                        settings=settings,
                        redis_client=self.redis_client,
                    )
                except Exception:
                    log.warning("gdacs_pipeline_failed", event_id=event["gdacs_id"])
                new_count += 1
            else:
                update_count += 1

            vector = await self._embed(description)
            if vector is None:
                continue

            payload = {
                "source": "gdacs",
                **event,
                "ingested_epoch": time.time(),
                "description": description,
            }
            point = self._build_point(point_id=point_id, vector=vector, payload=payload)
            points.append(point)

        if points:
            await self._batch_upsert(points)

        log.info("gdacs_complete", total=len(events), new=new_count, updated=update_count, upserted=len(points))
```

- [ ] **Step 4: Run tests**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdacs_collector.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/gdacs_collector.py services/data-ingestion/tests/test_gdacs_collector.py
git commit -m "feat(ingestion): add GDACS disaster alert collector"
```

---

### Task 5: HAPI Collector + Tests

**Files:**
- Create: `services/data-ingestion/feeds/hapi_collector.py`
- Create: `services/data-ingestion/tests/test_hapi_collector.py`

- [ ] **Step 1: Write failing tests**

Create `services/data-ingestion/tests/test_hapi_collector.py`:

```python
"""Tests for HAPI humanitarian conflict collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.hapi_collector import HAPICollector, FOCUS_COUNTRIES

SAMPLE_RESPONSE = {
    "data": [
        {
            "location_code": "UKR",
            "reference_period_start": "2026-03-01",
            "event_type": "political_violence",
            "events": 245,
            "fatalities": 89,
        },
        {
            "location_code": "UKR",
            "reference_period_start": "2026-03-01",
            "event_type": "civilian_targeting",
            "events": 52,
            "fatalities": 31,
        },
    ]
}


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.hapi_app_identifier = "dGVzdEBlbWFpbC5jb20="  # base64("test@email.com")
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = HAPICollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestHAPIParser:
    def test_parse_records(self, collector):
        records = collector._parse_records(SAMPLE_RESPONSE, "UKR")
        assert len(records) == 2

        r1 = records[0]
        assert r1["location_code"] == "UKR"
        assert r1["reference_period"] == "2026-03"
        assert r1["event_type"] == "political_violence"
        assert r1["events_count"] == 245
        assert r1["fatalities"] == 89

    def test_parse_records_empty(self, collector):
        records = collector._parse_records({"data": []}, "UKR")
        assert records == []


class TestHAPIFocusCountries:
    def test_all_iso3(self):
        for code in FOCUS_COUNTRIES:
            assert len(code) == 3
            assert code.isalpha()
            assert code.isupper()

    def test_count(self):
        assert len(FOCUS_COUNTRIES) == 20


class TestHAPIContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._hapi_content_hash("UKR", "2026-03", "political_violence")
        h2 = collector._hapi_content_hash("UKR", "2026-03", "political_violence")
        assert h1 == h2

    def test_different_country_different_hash(self, collector):
        h1 = collector._hapi_content_hash("UKR", "2026-03", "political_violence")
        h2 = collector._hapi_content_hash("SYR", "2026-03", "political_violence")
        assert h1 != h2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && uv run pytest tests/test_hapi_collector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement HAPI collector**

Create `services/data-ingestion/feeds/hapi_collector.py`:

```python
"""HAPI — Humanitarian Data Exchange API.

Collects monthly conflict aggregates per country (events, fatalities, event_type).
Standard insert-only dedup (not mutable events).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import structlog

from config import settings
from feeds.base import BaseCollector

log = structlog.get_logger("hapi_collector")

_HAPI_URL = "https://hapi.humdata.org/api/v2/coordination-context/conflict-events"

FOCUS_COUNTRIES = [
    "AFG", "SYR", "UKR", "SDN", "SSD",
    "SOM", "COD", "MMR", "YEM", "ETH",
    "IRQ", "PSE", "LBY", "MLI", "BFA",
    "NER", "NGA", "CMR", "MOZ", "HTI",
]


class HAPICollector(BaseCollector):
    """Collect humanitarian conflict data from HAPI."""

    def _hapi_content_hash(self, location_code: str, period: str, event_type: str) -> int:
        digest = hashlib.sha256(f"{location_code}{period}{event_type}".encode()).hexdigest()
        return int(digest[:16], 16)

    def _parse_records(self, data: dict[str, Any], country: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in data.get("data", []):
            period_start = str(item.get("reference_period_start", ""))
            period = period_start[:7] if len(period_start) >= 7 else period_start

            records.append({
                "location_code": country,
                "reference_period": period,
                "event_type": str(item.get("event_type", "")),
                "events_count": int(item.get("events", 0)),
                "fatalities": int(item.get("fatalities", 0)),
            })
        return records

    async def collect(self) -> None:
        await self._ensure_collection()

        headers = {}
        if settings.hapi_app_identifier:
            headers["app_identifier"] = settings.hapi_app_identifier

        total_ingested = 0

        for country in FOCUS_COUNTRIES:
            params = {
                "output_format": "json",
                "limit": 1000,
                "location_code": country,
            }
            try:
                resp = await self.http.get(_HAPI_URL, params=params, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                log.warning("hapi_fetch_failed", country=country)
                continue

            records = self._parse_records(data, country)
            points = []

            for record in records:
                point_id = self._hapi_content_hash(
                    record["location_code"],
                    record["reference_period"],
                    record["event_type"],
                )

                # Standard dedup — skip if exists
                is_dup = await self._dedup_check(point_id)
                if is_dup:
                    continue

                description = (
                    f"{record['event_type']}: {record['events_count']} events, "
                    f"{record['fatalities']} fatalities in {country} ({record['reference_period']})"
                )

                try:
                    from pipeline import process_item
                    await process_item(
                        title=f"HAPI {country} {record['reference_period']}",
                        text=description,
                        url=_HAPI_URL,
                        source="hapi",
                        settings=settings,
                        redis_client=self.redis_client,
                    )
                except Exception:
                    log.warning("hapi_pipeline_failed", country=country)

                vector = await self._embed(description)
                if vector is None:
                    continue

                payload = {
                    "source": "hapi",
                    **record,
                    "ingested_epoch": time.time(),
                    "description": description,
                }
                point = self._build_point(point_id=point_id, vector=vector, payload=payload)
                points.append(point)

            if points:
                await self._batch_upsert(points)
                total_ingested += len(points)

            # Rate limiting between country queries
            await asyncio.sleep(1)

        log.info("hapi_complete", total_ingested=total_ingested, countries=len(FOCUS_COUNTRIES))
```

- [ ] **Step 4: Run tests**

Run: `cd services/data-ingestion && uv run pytest tests/test_hapi_collector.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/hapi_collector.py services/data-ingestion/tests/test_hapi_collector.py
git commit -m "feat(ingestion): add HAPI humanitarian conflict collector"
```

---

### Task 6: NOAA NHC Collector + Tests

**Files:**
- Create: `services/data-ingestion/feeds/noaa_nhc_collector.py`
- Create: `services/data-ingestion/tests/test_noaa_nhc_collector.py`

- [ ] **Step 1: Write failing tests**

Create `services/data-ingestion/tests/test_noaa_nhc_collector.py`:

```python
"""Tests for NOAA NHC tropical weather collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.noaa_nhc_collector import NOAANHCCollector

SAMPLE_RESPONSE = {
    "activeStorms": [
        {
            "id": "al042026",
            "name": "Delta",
            "classification": "HU",
            "intensity": 85,
            "pressure": 972,
            "lat": 25.4,
            "lon": -88.2,
            "movement": {"text": "NW at 12 kt"},
            "lastUpdate": "2026-04-12T15:00:00Z",
            "advisoryNumber": "14",
        },
    ]
}


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = NOAANHCCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestNOAAParser:
    def test_parse_storms(self, collector):
        storms = collector._parse_storms(SAMPLE_RESPONSE)
        assert len(storms) == 1

        s = storms[0]
        assert s["storm_id"] == "al042026"
        assert s["storm_name"] == "Delta"
        assert s["classification"] == "Hurricane"
        assert s["wind_speed_kt"] == 85
        assert s["pressure_mb"] == 972
        assert s["latitude"] == 25.4
        assert s["longitude"] == -88.2
        assert s["advisory_number"] == "14"

    def test_parse_storms_empty(self, collector):
        storms = collector._parse_storms({"activeStorms": []})
        assert storms == []

    def test_classification_mapping(self, collector):
        for code, label in [("TD", "Tropical Depression"), ("TS", "Tropical Storm"), ("HU", "Hurricane")]:
            data = {"activeStorms": [{"id": "t1", "name": "T", "classification": code, "intensity": 50, "pressure": 1000, "lat": 20, "lon": -80, "movement": {"text": "N"}, "lastUpdate": "", "advisoryNumber": "1"}]}
            storms = collector._parse_storms(data)
            assert storms[0]["classification"] == label


class TestNOAAContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._nhc_content_hash("al042026", "14")
        h2 = collector._nhc_content_hash("al042026", "14")
        assert h1 == h2

    def test_different_advisory_different_hash(self, collector):
        h1 = collector._nhc_content_hash("al042026", "14")
        h2 = collector._nhc_content_hash("al042026", "15")
        assert h1 != h2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && uv run pytest tests/test_noaa_nhc_collector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement NOAA NHC collector**

Create `services/data-ingestion/feeds/noaa_nhc_collector.py`:

```python
"""NOAA NHC — National Hurricane Center Tropical Weather.

Collects active tropical cyclone advisories. Standard insert-only dedup.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import structlog

from config import settings
from feeds.base import BaseCollector

log = structlog.get_logger("noaa_nhc_collector")

_NHC_URL = "https://www.nhc.noaa.gov/CurrentSummaries.json"

_CLASSIFICATION_MAP = {
    "TD": "Tropical Depression",
    "TS": "Tropical Storm",
    "HU": "Hurricane",
    "STD": "Subtropical Depression",
    "STS": "Subtropical Storm",
    "PTC": "Post-Tropical Cyclone",
    "TW": "Tropical Weather Outlook",
}


class NOAANHCCollector(BaseCollector):
    """Collect tropical weather advisories from NOAA NHC."""

    def _nhc_content_hash(self, storm_id: str, advisory_number: str) -> int:
        digest = hashlib.sha256(f"{storm_id}{advisory_number}".encode()).hexdigest()
        return int(digest[:16], 16)

    def _parse_storms(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        storms: list[dict[str, Any]] = []
        for storm in data.get("activeStorms", []):
            classification_code = str(storm.get("classification", ""))
            classification = _CLASSIFICATION_MAP.get(classification_code, classification_code)

            movement = storm.get("movement", {})
            movement_text = movement.get("text", "") if isinstance(movement, dict) else str(movement)

            storms.append({
                "storm_id": str(storm.get("id", "")),
                "storm_name": str(storm.get("name", "")),
                "classification": classification,
                "wind_speed_kt": int(storm.get("intensity", 0)),
                "pressure_mb": int(storm.get("pressure", 0)),
                "latitude": float(storm.get("lat", 0)),
                "longitude": float(storm.get("lon", 0)),
                "movement": movement_text,
                "advisory_number": str(storm.get("advisoryNumber", "")),
            })
        return storms

    async def collect(self) -> None:
        await self._ensure_collection()

        try:
            resp = await self.http.get(_NHC_URL, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            log.exception("noaa_nhc_fetch_failed")
            return

        storms = self._parse_storms(data)
        log.info("noaa_nhc_parsed", count=len(storms))

        if not storms:
            log.info("noaa_nhc_no_active_storms")
            return

        points = []
        for storm in storms:
            point_id = self._nhc_content_hash(storm["storm_id"], storm["advisory_number"])

            is_dup = await self._dedup_check(point_id)
            if is_dup:
                continue

            description = (
                f"{storm['classification']} {storm['storm_name']} — "
                f"winds {storm['wind_speed_kt']}kt, pressure {storm['pressure_mb']}mb, "
                f"moving {storm['movement']}"
            )

            try:
                from pipeline import process_item
                await process_item(
                    title=f"NHC Advisory: {storm['storm_name']}",
                    text=description,
                    url=f"https://www.nhc.noaa.gov/text/refresh/{storm['storm_id']}+shtml",
                    source="noaa_nhc",
                    settings=settings,
                    redis_client=self.redis_client,
                )
            except Exception:
                log.warning("noaa_nhc_pipeline_failed", storm_id=storm["storm_id"])

            vector = await self._embed(description)
            if vector is None:
                continue

            payload = {
                "source": "noaa_nhc",
                **storm,
                "ingested_epoch": time.time(),
                "description": description,
            }
            point = self._build_point(point_id=point_id, vector=vector, payload=payload)
            points.append(point)

        if points:
            await self._batch_upsert(points)

        log.info("noaa_nhc_complete", storms=len(storms), ingested=len(points))
```

- [ ] **Step 4: Run tests**

Run: `cd services/data-ingestion && uv run pytest tests/test_noaa_nhc_collector.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/noaa_nhc_collector.py services/data-ingestion/tests/test_noaa_nhc_collector.py
git commit -m "feat(ingestion): add NOAA NHC tropical weather collector"
```

---

### Task 7: PortWatch Collector + Tests

**Files:**
- Create: `services/data-ingestion/feeds/portwatch_collector.py`
- Create: `services/data-ingestion/tests/test_portwatch_collector.py`

- [ ] **Step 1: Write failing tests**

Create `services/data-ingestion/tests/test_portwatch_collector.py`:

```python
"""Tests for IMF PortWatch chokepoint collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.portwatch_collector import PortWatchCollector, CHOKEPOINT_COORDS

SAMPLE_CHOKEPOINT_RESPONSE = {
    "features": [
        {
            "attributes": {
                "chokepoint_name": "Strait of Hormuz",
                "date": "2026-04-10",
                "trade_value_usd": 250_000_000,
                "vessel_count": 42,
            },
        },
        {
            "attributes": {
                "chokepoint_name": "Suez Canal",
                "date": "2026-04-10",
                "trade_value_usd": 180_000_000,
                "vessel_count": 35,
            },
        },
    ],
    "exceededTransferLimit": False,
}

SAMPLE_DISRUPTION_RESPONSE = {
    "features": [
        {
            "attributes": {
                "objectid": "D001",
                "chokepoint_name": "Bab el-Mandeb",
                "disruption_description": "Houthi drone attack on tanker",
                "start_date": "2026-04-08",
                "end_date": None,
            },
        },
    ],
    "exceededTransferLimit": False,
}


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = PortWatchCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestPortWatchParser:
    def test_parse_chokepoint_data(self, collector):
        records = collector._parse_chokepoint_data(SAMPLE_CHOKEPOINT_RESPONSE)
        assert len(records) == 2

        r1 = records[0]
        assert r1["chokepoint"] == "Strait of Hormuz"
        assert r1["date"] == "2026-04-10"
        assert r1["trade_value_usd"] == 250_000_000
        assert r1["vessel_count"] == 42
        assert r1["record_type"] == "daily_flow"

    def test_parse_disruption_data(self, collector):
        records = collector._parse_disruption_data(SAMPLE_DISRUPTION_RESPONSE)
        assert len(records) == 1

        r = records[0]
        assert r["chokepoint"] == "Bab el-Mandeb"
        assert r["record_type"] == "disruption"
        assert r["end_date"] is None

    def test_parse_empty(self, collector):
        assert collector._parse_chokepoint_data({"features": []}) == []
        assert collector._parse_disruption_data({"features": []}) == []


class TestChokepoints:
    def test_all_chokepoints_have_coords(self):
        for name, coords in CHOKEPOINT_COORDS.items():
            assert isinstance(coords, tuple)
            assert len(coords) == 2
            lat, lon = coords
            assert -90 <= lat <= 90
            assert -180 <= lon <= 180
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && uv run pytest tests/test_portwatch_collector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement PortWatch collector**

Create `services/data-ingestion/feeds/portwatch_collector.py`:

```python
"""IMF PortWatch — Chokepoint Trade Flows and Disruption Events.

ArcGIS FeatureServer with paginated queries. Standard insert-only dedup.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import structlog

from config import settings
from feeds.base import BaseCollector

log = structlog.get_logger("portwatch_collector")

_BASE_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
_CHOKEPOINTS_URL = f"{_BASE_URL}/Daily_Chokepoints_Data/FeatureServer/0/query"
_DISRUPTIONS_URL = f"{_BASE_URL}/portwatch_disruptions_database/FeatureServer/0/query"

_PAGE_SIZE = 1000

# Center coordinates for known chokepoints (lat, lon)
CHOKEPOINT_COORDS: dict[str, tuple[float, float]] = {
    "Strait of Hormuz": (26.57, 56.25),
    "Bab el-Mandeb": (12.58, 43.33),
    "Suez Canal": (30.46, 32.34),
    "Strait of Malacca": (2.50, 101.20),
    "Panama Canal": (9.08, -79.68),
    "Cape of Good Hope": (-34.35, 18.50),
    "Strait of Gibraltar": (35.96, -5.50),
    "Turkish Straits": (41.12, 29.08),
}


class PortWatchCollector(BaseCollector):
    """Collect chokepoint trade flows and disruptions from IMF PortWatch."""

    def _chokepoint_content_hash(self, chokepoint: str, date: str) -> int:
        digest = hashlib.sha256(f"{chokepoint}{date}daily_flow".encode()).hexdigest()
        return int(digest[:16], 16)

    def _disruption_content_hash(self, disruption_id: str) -> int:
        digest = hashlib.sha256(f"disruption_{disruption_id}".encode()).hexdigest()
        return int(digest[:16], 16)

    def _parse_chokepoint_data(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            chokepoint = str(attrs.get("chokepoint_name", ""))
            records.append({
                "record_type": "daily_flow",
                "chokepoint": chokepoint,
                "date": str(attrs.get("date", "")),
                "trade_value_usd": float(attrs.get("trade_value_usd", 0)),
                "vessel_count": int(attrs.get("vessel_count", 0)),
            })
        return records

    def _parse_disruption_data(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            records.append({
                "record_type": "disruption",
                "disruption_id": str(attrs.get("objectid", "")),
                "chokepoint": str(attrs.get("chokepoint_name", "")),
                "description": str(attrs.get("disruption_description", "")),
                "start_date": str(attrs.get("start_date", "")),
                "end_date": attrs.get("end_date"),
            })
        return records

    async def _fetch_paginated(self, url: str) -> list[dict[str, Any]]:
        """Fetch all pages from ArcGIS FeatureServer."""
        all_features: list[dict[str, Any]] = []
        offset = 0

        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "f": "json",
                "resultRecordCount": _PAGE_SIZE,
                "resultOffset": offset,
            }
            try:
                resp = await self.http.get(url, params=params, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                log.warning("portwatch_page_failed", url=url, offset=offset)
                break

            features = data.get("features", [])
            all_features.extend(features)

            if not features or not data.get("exceededTransferLimit", False):
                break

            offset += len(features)
            await asyncio.sleep(1)

        return {"features": all_features}

    async def collect(self) -> None:
        await self._ensure_collection()

        # 1. Chokepoint daily flows
        log.info("portwatch_fetching_chokepoints")
        chokepoint_data = await self._fetch_paginated(_CHOKEPOINTS_URL)
        flow_records = self._parse_chokepoint_data(chokepoint_data)
        log.info("portwatch_flows_parsed", count=len(flow_records))

        flow_points = []
        for record in flow_records:
            point_id = self._chokepoint_content_hash(record["chokepoint"], record["date"])
            is_dup = await self._dedup_check(point_id)
            if is_dup:
                continue

            coords = CHOKEPOINT_COORDS.get(record["chokepoint"], (0.0, 0.0))
            description = (
                f"PortWatch: {record['chokepoint']} on {record['date']} — "
                f"${record['trade_value_usd']:,.0f} trade, {record['vessel_count']} vessels"
            )

            try:
                from pipeline import process_item
                await process_item(
                    title=f"PortWatch {record['chokepoint']}",
                    text=description,
                    url=_CHOKEPOINTS_URL,
                    source="portwatch",
                    settings=settings,
                    redis_client=self.redis_client,
                )
            except Exception:
                log.warning("portwatch_pipeline_failed", chokepoint=record["chokepoint"])

            vector = await self._embed(description)
            if vector is None:
                continue

            payload = {
                "source": "portwatch",
                **record,
                "latitude": coords[0],
                "longitude": coords[1],
                "ingested_epoch": time.time(),
                "description": description,
            }
            point = self._build_point(point_id=point_id, vector=vector, payload=payload)
            flow_points.append(point)

        if flow_points:
            await self._batch_upsert(flow_points)

        # 2. Disruption events
        log.info("portwatch_fetching_disruptions")
        disruption_data = await self._fetch_paginated(_DISRUPTIONS_URL)
        disruption_records = self._parse_disruption_data(disruption_data)
        log.info("portwatch_disruptions_parsed", count=len(disruption_records))

        disruption_points = []
        for record in disruption_records:
            point_id = self._disruption_content_hash(record["disruption_id"])
            is_dup = await self._dedup_check(point_id)
            if is_dup:
                continue

            coords = CHOKEPOINT_COORDS.get(record["chokepoint"], (0.0, 0.0))
            description = f"PortWatch Disruption: {record['chokepoint']} — {record['description']}"

            try:
                from pipeline import process_item
                await process_item(
                    title=f"PortWatch Disruption: {record['chokepoint']}",
                    text=description,
                    url=_DISRUPTIONS_URL,
                    source="portwatch",
                    settings=settings,
                    redis_client=self.redis_client,
                )
            except Exception:
                log.warning("portwatch_disruption_pipeline_failed")

            vector = await self._embed(description)
            if vector is None:
                continue

            payload = {
                "source": "portwatch",
                **record,
                "latitude": coords[0],
                "longitude": coords[1],
                "ingested_epoch": time.time(),
            }
            point = self._build_point(point_id=point_id, vector=vector, payload=payload)
            disruption_points.append(point)

        if disruption_points:
            await self._batch_upsert(disruption_points)

        log.info(
            "portwatch_complete",
            flows=len(flow_points),
            disruptions=len(disruption_points),
        )
```

- [ ] **Step 4: Run tests**

Run: `cd services/data-ingestion && uv run pytest tests/test_portwatch_collector.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/portwatch_collector.py services/data-ingestion/tests/test_portwatch_collector.py
git commit -m "feat(ingestion): add IMF PortWatch chokepoint collector"
```

---

### Task 8: Scheduler Wiring

**Files:**
- Modify: `services/data-ingestion/scheduler.py`

- [ ] **Step 1: Add imports**

Add after the existing imports (after line 27 `from feeds.correlation_job import CorrelationJob`):

```python
from feeds.eonet_collector import EONETCollector
from feeds.gdacs_collector import GDACSCollector
from feeds.hapi_collector import HAPICollector
from feeds.noaa_nhc_collector import NOAANHCCollector
from feeds.portwatch_collector import PortWatchCollector
```

- [ ] **Step 2: Add job wrapper functions**

Add after `run_correlation_job()` (after line 181):

```python
async def run_eonet_collector() -> None:
    """Collect NASA EONET natural events."""
    collector = EONETCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("eonet_job_failed")
    finally:
        await collector.close()


async def run_gdacs_collector() -> None:
    """Collect GDACS disaster alerts."""
    collector = GDACSCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("gdacs_job_failed")
    finally:
        await collector.close()


async def run_hapi_collector() -> None:
    """Collect HAPI humanitarian conflict data."""
    collector = HAPICollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("hapi_job_failed")
    finally:
        await collector.close()


async def run_noaa_nhc_collector() -> None:
    """Collect NOAA NHC tropical weather advisories."""
    collector = NOAANHCCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("noaa_nhc_job_failed")
    finally:
        await collector.close()


async def run_portwatch_collector() -> None:
    """Collect IMF PortWatch chokepoint flows."""
    collector = PortWatchCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("portwatch_job_failed")
    finally:
        await collector.close()
```

- [ ] **Step 3: Add scheduler jobs**

Add after the correlation job registration (after line 295) in `create_scheduler()`:

```python
    # --- Hugin P1 Collectors (Sprint 2a) ---

    scheduler.add_job(
        run_eonet_collector,
        trigger=IntervalTrigger(hours=settings.eonet_interval_hours),
        id="eonet_collector",
        name="EONET Natural Events Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_gdacs_collector,
        trigger=IntervalTrigger(hours=settings.gdacs_interval_hours),
        id="gdacs_collector",
        name="GDACS Disaster Alert Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_hapi_collector,
        trigger=CronTrigger(hour=4, minute=0, timezone="UTC"),
        id="hapi_collector",
        name="HAPI Humanitarian Conflict Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_noaa_nhc_collector,
        trigger=IntervalTrigger(hours=settings.noaa_nhc_interval_hours),
        id="noaa_nhc_collector",
        name="NOAA NHC Tropical Weather Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_portwatch_collector,
        trigger=IntervalTrigger(hours=settings.portwatch_interval_hours),
        id="portwatch_collector",
        name="IMF PortWatch Chokepoint Collector",
        replace_existing=True,
    )
```

- [ ] **Step 4: Add to initial startup tasks**

Add the new collectors to the `initial_tasks` list (before `# OFAC runs daily`):

```python
        run_eonet_collector(),
        run_gdacs_collector(),
        # HAPI runs daily via cron, not on initial startup
        run_noaa_nhc_collector(),
        run_portwatch_collector(),
```

- [ ] **Step 5: Run ingestion tests**

Run: `cd services/data-ingestion && uv run pytest -v`
Expected: All tests pass (existing + 5 new collector tests).

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/scheduler.py
git commit -m "feat(ingestion): wire 5 new collectors into scheduler"
```

---

### Task 9: EONET Backend Router

**Files:**
- Create: `services/backend/app/routers/eonet.py`
- Modify: `services/backend/app/main.py`

- [ ] **Step 1: Create EONET router**

Create `services/backend/app/routers/eonet.py`:

```python
"""EONET natural events — serves Qdrant-stored events for globe rendering."""

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

router = APIRouter(prefix="/eonet", tags=["eonet"])

_PAGE_SIZE = 512
_MAX_TOTAL = 2000
_CACHE_TTL_S = 120


class EONETEvent(BaseModel):
    id: str
    title: str
    category: str
    status: str
    latitude: float
    longitude: float
    event_date: str


def _point_to_event(point: Any) -> EONETEvent | None:
    p = point.payload or {}
    try:
        return EONETEvent(
            id=str(point.id),
            title=str(p.get("title", "")),
            category=str(p.get("category", "")),
            status=str(p.get("status", "")),
            latitude=float(p["latitude"]),
            longitude=float(p["longitude"]),
            event_date=str(p.get("event_date", "")),
        )
    except (KeyError, ValueError, TypeError):
        return None


@router.get("/events", response_model=list[EONETEvent])
async def get_eonet_events(
    request: Request,
    since_hours: int = Query(default=168, ge=1, le=720),
) -> list[EONETEvent]:
    cache_key = f"eonet:events:{since_hours}h"
    cache = request.app.state.cache
    cached = await cache.get(cache_key)
    if cached is not None:
        return [EONETEvent(**e) for e in cached]

    cutoff = int(time.time()) - since_hours * 3600
    flt = Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value="eonet")),
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
        log.error("eonet_qdrant_scroll_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="qdrant unreachable") from exc

    events = [e for e in (_point_to_event(p) for p in results) if e is not None]
    await cache.set(cache_key, [e.model_dump() for e in events], ttl_seconds=_CACHE_TTL_S)
    return events
```

- [ ] **Step 2: Register router in main.py**

Add import and registration in `services/backend/app/main.py`:

```python
from app.routers import eonet
```

And in the router registration section:

```python
app.include_router(eonet.router, prefix="/api/v1")
```

- [ ] **Step 3: Run backend tests**

Run: `cd services/backend && uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/backend/app/routers/eonet.py services/backend/app/main.py
git commit -m "feat(backend): add EONET events router with Redis cache"
```

---

### Task 10: GDACS Backend Router

**Files:**
- Create: `services/backend/app/routers/gdacs.py`
- Modify: `services/backend/app/main.py`

- [ ] **Step 1: Create GDACS router**

Create `services/backend/app/routers/gdacs.py`:

```python
"""GDACS disaster alerts — serves Qdrant-stored events for globe rendering."""

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

router = APIRouter(prefix="/gdacs", tags=["gdacs"])

_PAGE_SIZE = 512
_MAX_TOTAL = 2000
_CACHE_TTL_S = 120


class GDACSEvent(BaseModel):
    id: str
    event_type: str
    event_name: str
    alert_level: str
    severity: float
    country: str
    latitude: float
    longitude: float
    from_date: str
    to_date: str


def _point_to_event(point: Any) -> GDACSEvent | None:
    p = point.payload or {}
    try:
        return GDACSEvent(
            id=str(point.id),
            event_type=str(p.get("event_type", "")),
            event_name=str(p.get("event_name", "")),
            alert_level=str(p.get("alert_level", "")),
            severity=float(p.get("severity", 0)),
            country=str(p.get("country", "")),
            latitude=float(p["latitude"]),
            longitude=float(p["longitude"]),
            from_date=str(p.get("from_date", "")),
            to_date=str(p.get("to_date", "")),
        )
    except (KeyError, ValueError, TypeError):
        return None


@router.get("/events", response_model=list[GDACSEvent])
async def get_gdacs_events(
    request: Request,
    since_hours: int = Query(default=168, ge=1, le=720),
) -> list[GDACSEvent]:
    cache_key = f"gdacs:events:{since_hours}h"
    cache = request.app.state.cache
    cached = await cache.get(cache_key)
    if cached is not None:
        return [GDACSEvent(**e) for e in cached]

    cutoff = int(time.time()) - since_hours * 3600
    flt = Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value="gdacs")),
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
        log.error("gdacs_qdrant_scroll_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="qdrant unreachable") from exc

    events = [e for e in (_point_to_event(p) for p in results) if e is not None]
    await cache.set(cache_key, [e.model_dump() for e in events], ttl_seconds=_CACHE_TTL_S)
    return events
```

- [ ] **Step 2: Register router in main.py**

Add import:

```python
from app.routers import gdacs
```

And registration:

```python
app.include_router(gdacs.router, prefix="/api/v1")
```

- [ ] **Step 3: Run backend tests**

Run: `cd services/backend && uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/backend/app/routers/gdacs.py services/backend/app/main.py
git commit -m "feat(backend): add GDACS events router with Redis cache"
```

---

### Task 11: Frontend Hooks (EONET + GDACS)

**Files:**
- Create: `services/frontend/src/hooks/useEONETEvents.ts`
- Create: `services/frontend/src/hooks/useGDACSEvents.ts`

- [ ] **Step 1: Create useEONETEvents hook**

Create `services/frontend/src/hooks/useEONETEvents.ts`:

```typescript
import { useState, useEffect, useCallback } from "react";
import { getEONETEvents } from "../services/api";
import type { EONETEvent } from "../types";

const POLL_INTERVAL = 120_000; // 120 seconds

export function useEONETEvents(enabled: boolean, sinceHours = 168) {
  const [events, setEvents] = useState<EONETEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getEONETEvents(sinceHours);
      setEvents(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data on error
    } finally {
      setLoading(false);
    }
  }, [enabled, sinceHours]);

  useEffect(() => {
    if (!enabled) {
      setEvents([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { events, loading, lastUpdate };
}
```

- [ ] **Step 2: Create useGDACSEvents hook**

Create `services/frontend/src/hooks/useGDACSEvents.ts`:

```typescript
import { useState, useEffect, useCallback } from "react";
import { getGDACSEvents } from "../services/api";
import type { GDACSEvent } from "../types";

const POLL_INTERVAL = 120_000; // 120 seconds

export function useGDACSEvents(enabled: boolean, sinceHours = 168) {
  const [events, setEvents] = useState<GDACSEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getGDACSEvents(sinceHours);
      setEvents(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data on error
    } finally {
      setLoading(false);
    }
  }, [enabled, sinceHours]);

  useEffect(() => {
    if (!enabled) {
      setEvents([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { events, loading, lastUpdate };
}
```

- [ ] **Step 3: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: Clean.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/hooks/useEONETEvents.ts services/frontend/src/hooks/useGDACSEvents.ts
git commit -m "feat(frontend): add EONET + GDACS polling hooks"
```

---

### Task 12: Frontend Globe Layers (EONET + GDACS)

**Files:**
- Create: `services/frontend/src/components/layers/EONETLayer.tsx`
- Create: `services/frontend/src/components/layers/GDACSLayer.tsx`

- [ ] **Step 1: Create EONETLayer**

Create `services/frontend/src/components/layers/EONETLayer.tsx`:

```typescript
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { EONETEvent } from "../../types";

const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

const CATEGORY_COLORS: Record<string, string> = {
  volcanoes: "#ef4444",
  wildfires: "#f97316",
  severeStorms: "#a855f7",
  floods: "#3b82f6",
  seaLakeIce: "#3b82f6",
  earthquakes: "#ef4444",
  landslides: "#92400e",
  dustHaze: "#d4a574",
};

const DEFAULT_COLOR = "#9ca3af";

function categoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? DEFAULT_COLOR;
}

export function createEONETIcon(category: string, size = 24): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const color = categoryColor(category);
  const cx = size / 2;

  ctx.fillStyle = color;
  ctx.globalAlpha = 0.8;

  if (category === "volcanoes") {
    // Triangle
    ctx.beginPath();
    ctx.moveTo(cx, 2);
    ctx.lineTo(size - 2, size - 2);
    ctx.lineTo(2, size - 2);
    ctx.closePath();
    ctx.fill();
  } else if (category === "wildfires") {
    // Flame shape
    ctx.beginPath();
    ctx.moveTo(cx, 2);
    ctx.quadraticCurveTo(cx - 6, size * 0.5, cx - 5, size - 3);
    ctx.quadraticCurveTo(cx, size * 0.7, cx + 5, size - 3);
    ctx.quadraticCurveTo(cx + 6, size * 0.5, cx, 2);
    ctx.closePath();
    ctx.fill();
  } else if (category === "severeStorms") {
    // Spiral/cyclone approximation
    ctx.beginPath();
    ctx.arc(cx, cx, size * 0.35, 0, Math.PI * 1.8);
    ctx.lineWidth = 3;
    ctx.strokeStyle = color;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cx, 3, 0, Math.PI * 2);
    ctx.fill();
  } else {
    // Default: filled circle
    ctx.beginPath();
    ctx.arc(cx, cx, size * 0.35, 0, Math.PI * 2);
    ctx.fill();
  }

  return canvas;
}

interface EONETLayerProps {
  viewer: Cesium.Viewer | null;
  events: EONETEvent[];
  visible: boolean;
  onSelect?: (event: EONETEvent) => void;
}

export function EONETLayer({ viewer, events, visible, onSelect }: EONETLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, EONETEvent>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const evt = idMapRef.current.get(picked.primitive as unknown as object);
        if (evt && onSelectRef.current) onSelectRef.current(evt);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed()) {
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      billboardCollectionRef.current = null;
      labelCollectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const bc = billboardCollectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;
    bc.removeAll();
    lc.removeAll();
    idMapRef.current.clear();
    if (!visible) return;

    for (const event of events) {
      const position = Cesium.Cartesian3.fromDegrees(event.longitude, event.latitude);
      const color = categoryColor(event.category);

      const bb = bc.add({
        position,
        image: createEONETIcon(event.category, 24),
        scale: 0.8,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
      });
      idMapRef.current.set(bb as unknown as object, event);

      lc.add({
        position,
        text: event.title,
        font: "11px monospace",
        fillColor: Cesium.Color.fromCssColorString(color).withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -18),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        scale: 0.9,
      });
    }
  }, [events, visible, viewer]);

  return null;
}
```

- [ ] **Step 2: Create GDACSLayer**

Create `services/frontend/src/components/layers/GDACSLayer.tsx`:

```typescript
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { GDACSEvent } from "../../types";

const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

const ALERT_CONFIG: Record<string, { color: string; size: number }> = {
  Red: { color: "#ef4444", size: 16 },
  Orange: { color: "#f97316", size: 12 },
  Green: { color: "#22c55e", size: 8 },
};

const DEFAULT_ALERT = { color: "#9ca3af", size: 10 };

export function createGDACSIcon(alertLevel: string, size?: number): HTMLCanvasElement {
  const config = ALERT_CONFIG[alertLevel] ?? DEFAULT_ALERT;
  const canvasSize = size ?? config.size * 2;
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const cx = canvasSize / 2;
  const radius = config.size * 0.7;

  // Filled circle with glow
  const grad = ctx.createRadialGradient(cx, cx, radius * 0.3, cx, cx, radius);
  grad.addColorStop(0, config.color);
  grad.addColorStop(1, `${config.color}00`);
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(cx, cx, radius, 0, Math.PI * 2);
  ctx.fill();

  // Solid core
  ctx.fillStyle = config.color;
  ctx.globalAlpha = 0.9;
  ctx.beginPath();
  ctx.arc(cx, cx, radius * 0.5, 0, Math.PI * 2);
  ctx.fill();

  return canvas;
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  EQ: "Earthquake",
  TC: "Tropical Cyclone",
  FL: "Flood",
  VO: "Volcano",
  DR: "Drought",
  WF: "Wildfire",
};

interface GDACSLayerProps {
  viewer: Cesium.Viewer | null;
  events: GDACSEvent[];
  visible: boolean;
  onSelect?: (event: GDACSEvent) => void;
}

export function GDACSLayer({ viewer, events, visible, onSelect }: GDACSLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, GDACSEvent>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const evt = idMapRef.current.get(picked.primitive as unknown as object);
        if (evt && onSelectRef.current) onSelectRef.current(evt);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed()) {
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      billboardCollectionRef.current = null;
      labelCollectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const bc = billboardCollectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;
    bc.removeAll();
    lc.removeAll();
    idMapRef.current.clear();
    if (!visible) return;

    for (const event of events) {
      const position = Cesium.Cartesian3.fromDegrees(event.longitude, event.latitude);
      const config = ALERT_CONFIG[event.alert_level] ?? DEFAULT_ALERT;

      const bb = bc.add({
        position,
        image: createGDACSIcon(event.alert_level),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
      });
      idMapRef.current.set(bb as unknown as object, event);

      lc.add({
        position,
        text: event.event_name,
        font: "11px monospace",
        fillColor: Cesium.Color.fromCssColorString(config.color).withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -18),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        scale: 0.9,
      });
    }
  }, [events, visible, viewer]);

  return null;
}

export { EVENT_TYPE_LABELS };
```

- [ ] **Step 3: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: Clean.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/components/layers/EONETLayer.tsx services/frontend/src/components/layers/GDACSLayer.tsx
git commit -m "feat(frontend): add EONET + GDACS globe layers"
```

---

### Task 13: Frontend Integration (OperationsPanel, SelectionPanel, App.tsx)

**Files:**
- Modify: `services/frontend/src/components/ui/OperationsPanel.tsx`
- Modify: `services/frontend/src/components/ui/SelectionPanel.tsx`
- Modify: `services/frontend/src/App.tsx`

- [ ] **Step 1: Add to INGESTION_LAYERS in OperationsPanel**

Add to the `INGESTION_LAYERS` array (after `milAircraft`):

```typescript
  { key: "eonet",   label: "EONET EVENTS",  color: "#f97316" },
  { key: "gdacs",   label: "GDACS ALERTS",  color: "#ef4444" },
```

Add LayerIcon SVG cases before the `default`:

```typescript
    case "eonet":
      return (
        <svg {...s}>
          <path d="M16 4 L26 26 L6 26 Z" fill={color} opacity={0.7} stroke={color} strokeWidth={1} />
        </svg>
      );
    case "gdacs":
      return (
        <svg {...s}>
          <circle cx={16} cy={16} r={10} fill={color} opacity={0.3} stroke={color} strokeWidth={2} />
          <circle cx={16} cy={16} r={4} fill={color} opacity={0.9} />
        </svg>
      );
```

- [ ] **Step 2: Extend SelectionPanel**

Add imports:

```typescript
import type { AircraftTrack, FIRMSHotspot, DatacenterProperties, RefineryProperties, EONETEvent, GDACSEvent } from "../../types";
```

Extend `Selected` type:

```typescript
export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: AircraftTrack }
  | { type: "datacenter"; data: DatacenterProperties }
  | { type: "refinery"; data: RefineryProperties }
  | { type: "eonet"; data: EONETEvent }
  | { type: "gdacs"; data: GDACSEvent };
```

Update the header `<span>` and content routing to handle `eonet` and `gdacs` types. Add content components:

```typescript
function EONETContent({ e }: { e: EONETEvent }) {
  return (
    <>
      <div className="mb-1 text-orange-300 font-bold">{e.title}</div>
      <Row label="CATEGORY" value={e.category.toUpperCase()} />
      <Row label="STATUS" value={e.status.toUpperCase()} />
      <Row label="DATE" value={e.event_date.slice(0, 10)} />
      <Row label="POSITION" value={`${e.latitude.toFixed(4)}, ${e.longitude.toFixed(4)}`} />
    </>
  );
}

function GDACSContent({ e }: { e: GDACSEvent }) {
  const typeLabel: Record<string, string> = {
    EQ: "Earthquake", TC: "Tropical Cyclone", FL: "Flood",
    VO: "Volcano", DR: "Drought", WF: "Wildfire",
  };
  return (
    <>
      <div className="mb-1 text-red-300 font-bold">{e.event_name}</div>
      <Row label="TYPE" value={typeLabel[e.event_type] ?? e.event_type} />
      <Row label="ALERT" value={e.alert_level} />
      <Row label="SEVERITY" value={e.severity.toFixed(1)} />
      <Row label="COUNTRY" value={e.country} />
      <Row label="PERIOD" value={`${e.from_date.slice(0, 10)} → ${e.to_date.slice(0, 10)}`} />
      <Row label="POSITION" value={`${e.latitude.toFixed(4)}, ${e.longitude.toFixed(4)}`} />
    </>
  );
}
```

- [ ] **Step 3: Wire in App.tsx**

Add imports:

```typescript
import { EONETLayer } from "./components/layers/EONETLayer";
import { GDACSLayer } from "./components/layers/GDACSLayer";
import { useEONETEvents } from "./hooks/useEONETEvents";
import { useGDACSEvents } from "./hooks/useGDACSEvents";
```

Add hooks:

```typescript
  const { events: eonetEvents } = useEONETEvents(layers.eonet);
  const { events: gdacsEvents } = useGDACSEvents(layers.gdacs);
```

Add layer components (after RefineryLayer, before EntityClickHandler):

```typescript
      <EONETLayer
        viewer={viewer}
        events={eonetEvents}
        visible={layers.eonet}
        onSelect={(e) => setSelected({ type: "eonet", data: e })}
      />
      <GDACSLayer
        viewer={viewer}
        events={gdacsEvents}
        visible={layers.gdacs}
        onSelect={(e) => setSelected({ type: "gdacs", data: e })}
      />
```

Add `eonetCount` and `gdacsCount` to OperationsPanel props:

```typescript
        eonetCount={eonetEvents.length}
        gdacsCount={gdacsEvents.length}
```

Update OperationsPanel component to accept and display these counts (add to props interface + `countFor` function).

- [ ] **Step 4: Run type-check + tests**

Run: `cd services/frontend && npx tsc --noEmit && npx vitest run`
Expected: Clean type-check, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/ui/OperationsPanel.tsx services/frontend/src/components/ui/SelectionPanel.tsx services/frontend/src/App.tsx
git commit -m "feat(frontend): wire EONET + GDACS layers into App"
```

---

### Task 14: Frontend Tests

**Files:**
- Create: `services/frontend/src/hooks/__tests__/useEONETEvents.test.ts`
- Create: `services/frontend/src/hooks/__tests__/useGDACSEvents.test.ts`

- [ ] **Step 1: Write EONET hook tests**

Create `services/frontend/src/hooks/__tests__/useEONETEvents.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useEONETEvents } from "../useEONETEvents";

describe("useEONETEvents", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(api, "getEONETEvents");
    renderHook(() => useEONETEvents(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches when enabled", async () => {
    const spy = vi.spyOn(api, "getEONETEvents").mockResolvedValue([
      { id: "e1", title: "Fire", category: "wildfires", status: "open", latitude: 34.0, longitude: -118.5, event_date: "2026-04-10" },
    ]);

    const { result } = renderHook(() => useEONETEvents(true));
    await waitFor(() => expect(result.current.events.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getEONETEvents").mockResolvedValue([
      { id: "e1", title: "Fire", category: "wildfires", status: "open", latitude: 34.0, longitude: -118.5, event_date: "2026-04-10" },
    ]);

    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useEONETEvents(on),
      { initialProps: { on: true } },
    );
    await waitFor(() => expect(result.current.events.length).toBe(1));

    rerender({ on: false });
    expect(result.current.events.length).toBe(0);
  });
});
```

- [ ] **Step 2: Write GDACS hook tests**

Create `services/frontend/src/hooks/__tests__/useGDACSEvents.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useGDACSEvents } from "../useGDACSEvents";

describe("useGDACSEvents", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(api, "getGDACSEvents");
    renderHook(() => useGDACSEvents(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches when enabled", async () => {
    const spy = vi.spyOn(api, "getGDACSEvents").mockResolvedValue([
      { id: "g1", event_type: "EQ", event_name: "Earthquake", alert_level: "Red", severity: 6.5, country: "Indonesia", latitude: 3.5, longitude: 95.0, from_date: "2026-04-10", to_date: "2026-04-10" },
    ]);

    const { result } = renderHook(() => useGDACSEvents(true));
    await waitFor(() => expect(result.current.events.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getGDACSEvents").mockResolvedValue([
      { id: "g1", event_type: "EQ", event_name: "Earthquake", alert_level: "Red", severity: 6.5, country: "Indonesia", latitude: 3.5, longitude: 95.0, from_date: "2026-04-10", to_date: "2026-04-10" },
    ]);

    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useGDACSEvents(on),
      { initialProps: { on: true } },
    );
    await waitFor(() => expect(result.current.events.length).toBe(1));

    rerender({ on: false });
    expect(result.current.events.length).toBe(0);
  });
});
```

- [ ] **Step 3: Run all frontend tests**

Run: `cd services/frontend && npx vitest run`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/hooks/__tests__/useEONETEvents.test.ts services/frontend/src/hooks/__tests__/useGDACSEvents.test.ts
git commit -m "test(frontend): add EONET + GDACS hook tests"
```

---

### Task 15: Full Verification

**Files:** None (verification only)

- [ ] **Step 1: Run ingestion tests**

Run: `cd services/data-ingestion && uv run pytest -v`
Expected: All tests pass. Note count.

- [ ] **Step 2: Run backend tests**

Run: `cd services/backend && uv run pytest -v`
Expected: All tests pass. Note count.

- [ ] **Step 3: Run frontend tests**

Run: `cd services/frontend && npx vitest run`
Expected: All tests pass. Note count.

- [ ] **Step 4: Run frontend type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 5: Run frontend lint**

Run: `cd services/frontend && npx eslint src/ --ext .ts,.tsx`
Expected: 0 new errors.

- [ ] **Step 6: Run frontend build**

Run: `cd services/frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 7: Run backend lint**

Run: `cd services/backend && uv run ruff check app/`
Expected: 0 new errors.

- [ ] **Step 8: Run ingestion lint**

Run: `cd services/data-ingestion && uv run ruff check feeds/ tests/`
Expected: 0 new errors.

- [ ] **Step 9: Report results**

Report all test counts, type-check status, lint status, and build status across all 3 services.
