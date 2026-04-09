# Hugin P0 Collectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 new OSINT collectors (ACLED, UCDP, FIRMS, USGS, Military Aircraft, OFAC) to the data-ingestion service with a shared BaseCollector abstraction.

**Architecture:** Each collector inherits from `BaseCollector` which handles Qdrant setup, embedding, dedup, and batch upsert. Four collectors (ACLED, UCDP, FIRMS, USGS) use `process_item()` for vLLM extraction → Neo4j → Redis. Two (Military Aircraft, OFAC) write directly to Neo4j with deterministic Cypher templates.

**Tech Stack:** Python 3.12, httpx, qdrant-client, structlog, pydantic-settings, APScheduler, lxml (OFAC XML), respx (test mocking)

**Spec:** `docs/superpowers/specs/2026-04-09-hugin-p0-collectors-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `services/data-ingestion/feeds/base.py` | BaseCollector ABC — Qdrant, embed, dedup, upsert |
| `services/data-ingestion/feeds/acled_collector.py` | ACLED OAuth + conflict event fetch |
| `services/data-ingestion/feeds/ucdp_collector.py` | UCDP version discovery + GED fetch |
| `services/data-ingestion/feeds/firms_collector.py` | NASA FIRMS multi-satellite thermal anomalies |
| `services/data-ingestion/feeds/usgs_collector.py` | USGS earthquakes + nuclear test site enrichment |
| `services/data-ingestion/feeds/military_aircraft_collector.py` | adsb.fi military + OpenSky fallback |
| `services/data-ingestion/feeds/ofac_collector.py` | OFAC SDN XML parser + Neo4j sanctions graph |
| `services/data-ingestion/tests/test_base_collector.py` | BaseCollector unit tests |
| `services/data-ingestion/tests/test_acled_collector.py` | ACLED collector tests |
| `services/data-ingestion/tests/test_ucdp_collector.py` | UCDP collector tests |
| `services/data-ingestion/tests/test_firms_collector.py` | FIRMS collector tests |
| `services/data-ingestion/tests/test_usgs_collector.py` | USGS collector tests |
| `services/data-ingestion/tests/test_military_aircraft_collector.py` | Military aircraft tests |
| `services/data-ingestion/tests/test_ofac_collector.py` | OFAC collector tests |

### Modified Files

| File | Changes |
|------|---------|
| `services/data-ingestion/config.py` | Add ACLED, FIRMS, OpenSky, UCDP settings + interval overrides |
| `services/data-ingestion/scheduler.py` | Register 6 new collector jobs |
| `services/data-ingestion/pyproject.toml` | Add `lxml` dependency |

---

### Task 1: Config Extensions

**Files:**
- Modify: `services/data-ingestion/config.py:46-64`
- Modify: `services/data-ingestion/pyproject.toml:6-18`

- [ ] **Step 1: Add new settings fields to config.py**

Add after the Vision Enrichment block (line 63):

```python
    # --- Hugin P0 Collectors ---

    # ACLED (Armed Conflict Location & Event Data)
    acled_email: str = ""
    acled_password: str = ""
    acled_interval_hours: int = 6

    # UCDP (Uppsala Conflict Data Program)
    ucdp_access_token: str = ""
    ucdp_interval_hours: int = 12

    # NASA FIRMS (Fire Information)
    nasa_earthdata_key: str = ""
    firms_interval_hours: int = 2

    # USGS Earthquake
    usgs_interval_hours: int = 6

    # Military Aircraft (OpenSky fallback)
    opensky_client_id: str = ""
    opensky_client_secret: str = ""
    military_interval_minutes: int = 15
```

- [ ] **Step 2: Add lxml to pyproject.toml dependencies**

Add `"lxml>=5.1",` to the dependencies list (it's already there — verify, skip if present).

- [ ] **Step 3: Update .env.example**

Add to `.env.example`:

```bash
# --- Hugin P0 Collectors ---
ACLED_EMAIL=
ACLED_PASSWORD=
NASA_EARTHDATA_KEY=
OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
UCDP_ACCESS_TOKEN=
```

- [ ] **Step 4: Run config import test**

Run: `cd services/data-ingestion && python -c "from config import settings; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/config.py services/data-ingestion/pyproject.toml .env.example
git commit -m "feat(data-ingestion): add Hugin P0 collector config fields"
```

---

### Task 2: BaseCollector

**Files:**
- Create: `services/data-ingestion/feeds/base.py`
- Create: `services/data-ingestion/tests/test_base_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_base_collector.py`:

```python
"""Tests for BaseCollector shared functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.base import BaseCollector


class ConcreteCollector(BaseCollector):
    """Minimal concrete implementation for testing."""

    async def collect(self) -> None:
        pass


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
        c = ConcreteCollector(settings=mock_settings)
    return c


def test_content_hash_deterministic(collector):
    h1 = collector._content_hash("hello", "world")
    h2 = collector._content_hash("hello", "world")
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex


def test_content_hash_case_insensitive(collector):
    h1 = collector._content_hash("Hello", "World")
    h2 = collector._content_hash("hello", "world")
    assert h1 == h2


def test_point_id_from_hash(collector):
    chash = collector._content_hash("test")
    pid = collector._point_id(chash)
    assert isinstance(pid, int)
    assert pid > 0


def test_content_hash_different_inputs(collector):
    h1 = collector._content_hash("a", "b")
    h2 = collector._content_hash("c", "d")
    assert h1 != h2


@pytest.mark.asyncio
async def test_dedup_check_returns_false_for_new(collector):
    collector.qdrant.retrieve.return_value = []
    result = await collector._dedup_check(12345)
    assert result is False


@pytest.mark.asyncio
async def test_dedup_check_returns_true_for_existing(collector):
    collector.qdrant.retrieve.return_value = [MagicMock()]
    result = await collector._dedup_check(12345)
    assert result is True


@pytest.mark.asyncio
async def test_batch_upsert_empty_list_noop(collector):
    await collector._batch_upsert([])
    collector.qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_batch_upsert_calls_qdrant(collector):
    points = [MagicMock()]
    await collector._batch_upsert(points)
    collector.qdrant.upsert.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && python -m pytest tests/test_base_collector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'feeds.base'`

- [ ] **Step 3: Write BaseCollector implementation**

Create `services/data-ingestion/feeds/base.py`:

```python
"""BaseCollector — shared abstraction for all Hugin P0 collectors."""

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config import Settings

log = structlog.get_logger(__name__)


class BaseCollector(ABC):
    """Gemeinsame Logik für alle Hugin Collectors.

    Subclasses implement `collect()` with source-specific fetch/parse/ingest.
    """

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        self.settings = settings
        self.redis = redis_client
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self.http = httpx.AsyncClient(timeout=settings.http_timeout)
        self._collection_ready = False

    async def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        collections = await asyncio.to_thread(
            lambda: self.qdrant.get_collections().collections
        )
        if not any(c.name == self.settings.qdrant_collection for c in collections):
            await asyncio.to_thread(
                lambda: self.qdrant.create_collection(
                    collection_name=self.settings.qdrant_collection,
                    vectors_config=VectorParams(
                        size=self.settings.embedding_dimensions,
                        distance=Distance.COSINE,
                    ),
                )
            )
            log.info("qdrant_collection_created", collection=self.settings.qdrant_collection)
        self._collection_ready = True

    async def _embed(self, text: str) -> list[float]:
        resp = await self.http.post(
            f"{self.settings.tei_embed_url}/embed",
            json={"inputs": text, "truncate": True},
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data[0], list) else data

    def _content_hash(self, *parts: str) -> str:
        raw = "|".join(p.lower().strip() for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _point_id(self, content_hash: str) -> int:
        return int(content_hash[:16], 16)

    async def _dedup_check(self, point_id: int) -> bool:
        existing = await asyncio.to_thread(
            self.qdrant.retrieve,
            collection_name=self.settings.qdrant_collection,
            ids=[point_id],
        )
        return len(existing) > 0

    async def _batch_upsert(self, points: list[PointStruct]) -> None:
        if not points:
            return
        await asyncio.to_thread(
            self.qdrant.upsert,
            collection_name=self.settings.qdrant_collection,
            points=points,
        )
        log.info("qdrant_batch_upserted", count=len(points))

    async def _build_point(
        self, text: str, payload: dict, content_hash: str
    ) -> PointStruct:
        vector = await self._embed(text)
        point_id = self._point_id(content_hash)
        payload["content_hash"] = content_hash
        payload["ingested_at"] = datetime.now(timezone.utc).isoformat()
        return PointStruct(id=point_id, vector=vector, payload=payload)

    @abstractmethod
    async def collect(self) -> None: ...

    async def close(self) -> None:
        await self.http.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/data-ingestion && python -m pytest tests/test_base_collector.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/base.py services/data-ingestion/tests/test_base_collector.py
git commit -m "feat(data-ingestion): add BaseCollector abstraction for Hugin P0"
```

---

### Task 3: ACLED Collector

**Files:**
- Create: `services/data-ingestion/feeds/acled_collector.py`
- Create: `services/data-ingestion/tests/test_acled_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_acled_collector.py`:

```python
"""Tests for ACLED conflict data collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.acled_collector import ACLEDCollector


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.acled_email = "test@test.com"
    s.acled_password = "testpass"
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


SAMPLE_ACLED_RESPONSE = {
    "success": True,
    "data": [
        {
            "event_id_cnty": "SYR12345",
            "event_date": "2026-04-01",
            "event_type": "Battles",
            "sub_event_type": "Armed clash",
            "actor1": "Syrian Democratic Forces",
            "actor2": "ISIL",
            "admin1": "Hasakah",
            "country": "Syria",
            "latitude": "36.5",
            "longitude": "40.7",
            "fatalities": "3",
            "notes": "SDF clashed with ISIL remnants near Hasakah.",
            "source": "Syrian Observatory for Human Rights",
        }
    ],
}


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = ACLEDCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []  # no duplicates
    return c


def test_build_acled_url(collector):
    url = collector._build_query_url(page=1)
    assert "acleddata.com" in url
    assert "event_type=Battles" in url
    assert "page=1" in url


def test_parse_event(collector):
    raw = SAMPLE_ACLED_RESPONSE["data"][0]
    payload = collector._parse_event(raw)
    assert payload["source"] == "acled"
    assert payload["acled_event_id"] == "SYR12345"
    assert payload["event_type"] == "Battles"
    assert payload["fatalities"] == 3
    assert payload["latitude"] == 36.5
    assert payload["longitude"] == 40.7


def test_parse_event_missing_coords(collector):
    raw = {**SAMPLE_ACLED_RESPONSE["data"][0], "latitude": "", "longitude": ""}
    payload = collector._parse_event(raw)
    assert payload["latitude"] is None
    assert payload["longitude"] is None


@pytest.mark.asyncio
async def test_authenticate_gets_token(collector):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "tok123"}
    mock_resp.raise_for_status = MagicMock()
    collector.http.post = AsyncMock(return_value=mock_resp)
    await collector._authenticate()
    assert collector._token == "tok123"


@pytest.mark.asyncio
async def test_authenticate_failure_raises(collector):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")
    collector.http.post = AsyncMock(return_value=mock_resp)
    with pytest.raises(Exception, match="401"):
        await collector._authenticate()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && python -m pytest tests/test_acled_collector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'feeds.acled_collector'`

- [ ] **Step 3: Write ACLED collector implementation**

Create `services/data-ingestion/feeds/acled_collector.py`:

```python
"""ACLED Armed Conflict Location & Event Data collector."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import structlog

from config import Settings
from feeds.base import BaseCollector
from pipeline import process_item

log = structlog.get_logger(__name__)

ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_URL = "https://acleddata.com/api/acled/read"
ACLED_EVENT_TYPES = "Battles|Explosions/Remote violence|Violence against civilians"


class ACLEDCollector(BaseCollector):
    """Fetch conflict events from ACLED and ingest into Qdrant + Neo4j."""

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        super().__init__(settings, redis_client)
        self._token: str | None = None

    async def _authenticate(self) -> None:
        resp = await self.http.post(
            ACLED_TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": "acled",
                "username": self.settings.acled_email,
                "password": self.settings.acled_password,
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        log.info("acled_authenticated")

    def _build_query_url(self, page: int = 1) -> str:
        today = datetime.now(timezone.utc).date()
        date_from = today - timedelta(days=30)
        params = {
            "event_type": ACLED_EVENT_TYPES,
            "event_date": f"{date_from.isoformat()}|{today.isoformat()}",
            "event_date_where": "BETWEEN",
            "limit": "500",
            "page": str(page),
            "_format": "json",
        }
        return f"{ACLED_API_URL}?{urlencode(params)}"

    def _parse_event(self, raw: dict) -> dict:
        lat_str = raw.get("latitude", "")
        lon_str = raw.get("longitude", "")
        return {
            "source": "acled",
            "title": f"{raw.get('event_type', '')} in {raw.get('admin1', '')}, {raw.get('country', '')}",
            "url": f"https://acleddata.com/data/{raw.get('event_id_cnty', '')}",
            "acled_event_id": raw.get("event_id_cnty", ""),
            "event_type": raw.get("event_type", ""),
            "sub_event_type": raw.get("sub_event_type", ""),
            "fatalities": int(raw.get("fatalities", 0) or 0),
            "actor1": raw.get("actor1", ""),
            "actor2": raw.get("actor2", ""),
            "admin1": raw.get("admin1", ""),
            "country": raw.get("country", ""),
            "latitude": float(lat_str) if lat_str else None,
            "longitude": float(lon_str) if lon_str else None,
            "event_date": raw.get("event_date", ""),
        }

    async def collect(self) -> None:
        log.info("acled_collection_started")
        start = time.monotonic()

        if not self.settings.acled_email or not self.settings.acled_password:
            log.warning("acled_credentials_missing")
            return

        await self._ensure_collection()
        await self._authenticate()

        total_new = 0
        page = 1

        while True:
            url = self._build_query_url(page=page)
            try:
                resp = await self.http.get(
                    url,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if resp.status_code == 401:
                    log.info("acled_token_refresh")
                    await self._authenticate()
                    resp = await self.http.get(
                        url,
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                resp.raise_for_status()
            except Exception as exc:
                log.error("acled_fetch_failed", page=page, error=str(exc))
                break

            data = resp.json().get("data", [])
            if not data:
                break

            from qdrant_client.models import PointStruct

            points: list[PointStruct] = []
            for raw_event in data:
                event_id = raw_event.get("event_id_cnty", "")
                if not event_id:
                    continue

                chash = self._content_hash(event_id)
                pid = self._point_id(chash)

                if await self._dedup_check(pid):
                    continue

                payload = self._parse_event(raw_event)
                notes = raw_event.get("notes", "")
                embed_text = f"{payload['title']}. {notes}"[:2000]

                await process_item(
                    title=payload["title"],
                    text=embed_text,
                    url=payload["url"],
                    source="acled",
                    settings=self.settings,
                    redis_client=self.redis,
                )

                try:
                    point = await self._build_point(embed_text, payload, chash)
                    points.append(point)
                except Exception as exc:
                    log.warning("acled_embed_failed", event_id=event_id, error=str(exc))

            await self._batch_upsert(points)
            total_new += len(points)
            log.info("acled_page_ingested", page=page, new=len(points), fetched=len(data))

            page += 1
            await asyncio.sleep(0.3)  # 300ms defensive rate limit

        elapsed = round(time.monotonic() - start, 2)
        log.info("acled_collection_finished", total_new=total_new, elapsed_seconds=elapsed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/data-ingestion && python -m pytest tests/test_acled_collector.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/acled_collector.py services/data-ingestion/tests/test_acled_collector.py
git commit -m "feat(data-ingestion): add ACLED conflict data collector"
```

---

### Task 4: UCDP Collector

**Files:**
- Create: `services/data-ingestion/feeds/ucdp_collector.py`
- Create: `services/data-ingestion/tests/test_ucdp_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_ucdp_collector.py`:

```python
"""Tests for UCDP GED conflict data collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.ucdp_collector import UCDPCollector, VIOLENCE_TYPES


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 90.0
    s.embedding_dimensions = 1024
    s.ucdp_access_token = ""
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


SAMPLE_UCDP_RESPONSE = {
    "TotalCount": 1,
    "Result": [
        {
            "id": "12345",
            "type_of_violence": 1,
            "best": 5,
            "low": 3,
            "high": 8,
            "country": "Syria",
            "region": "Middle East",
            "latitude": "36.2",
            "longitude": "37.1",
            "date_start": "2026-03-15",
            "date_end": "2026-03-15",
            "side_a": "Government of Syria",
            "side_b": "IS",
            "source_article": "Clash in Aleppo countryside.",
        }
    ],
}


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = UCDPCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_violence_type_labels():
    assert VIOLENCE_TYPES[1] == "state-based"
    assert VIOLENCE_TYPES[2] == "non-state"
    assert VIOLENCE_TYPES[3] == "one-sided"


def test_parse_event(collector):
    raw = SAMPLE_UCDP_RESPONSE["Result"][0]
    payload = collector._parse_event(raw)
    assert payload["source"] == "ucdp"
    assert payload["ucdp_id"] == "12345"
    assert payload["violence_type"] == 1
    assert payload["violence_type_label"] == "state-based"
    assert payload["best_estimate"] == 5
    assert payload["latitude"] == 36.2


@pytest.mark.asyncio
async def test_discover_version_finds_valid(collector):
    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.json.return_value = {"Result": [{"id": "1"}]}

    collector.http.get = AsyncMock(return_value=good_resp)
    version = await collector._discover_version()
    assert version is not None


@pytest.mark.asyncio
async def test_discover_version_tries_fallbacks(collector):
    bad_resp = MagicMock()
    bad_resp.status_code = 404
    bad_resp.json.return_value = {}

    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.json.return_value = {"Result": [{"id": "1"}]}

    collector.http.get = AsyncMock(side_effect=[bad_resp, bad_resp, good_resp])
    version = await collector._discover_version()
    assert version is not None
    assert collector.http.get.call_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && python -m pytest tests/test_ucdp_collector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write UCDP collector implementation**

Create `services/data-ingestion/feeds/ucdp_collector.py`:

```python
"""UCDP GED (Uppsala Conflict Data Program) collector."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from config import Settings
from feeds.base import BaseCollector
from pipeline import process_item

log = structlog.get_logger(__name__)

UCDP_BASE_URL = "https://ucdpapi.pcr.uu.se/api/gedevents"
MAX_PAGES = 6
PAGE_SIZE = 1000

VIOLENCE_TYPES = {1: "state-based", 2: "non-state", 3: "one-sided"}


class UCDPCollector(BaseCollector):
    """Fetch conflict events from UCDP GED API."""

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        super().__init__(settings, redis_client)
        self.http = __import__("httpx").AsyncClient(timeout=90.0)  # UCDP is slow

    async def _discover_version(self) -> str | None:
        current_year = datetime.now(timezone.utc).year
        candidates = [
            f"{current_year - 2000}.1",
            f"{current_year - 2001}.1",
            "25.1",
            "24.1",
        ]
        for version in candidates:
            try:
                resp = await self.http.get(
                    f"{UCDP_BASE_URL}/{version}",
                    params={"pagesize": "1", "page": "0"},
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200 and resp.json().get("Result"):
                    log.info("ucdp_version_found", version=version)
                    return version
            except Exception:
                continue
        log.error("ucdp_no_valid_version")
        return None

    def _auth_headers(self) -> dict[str, str]:
        if self.settings.ucdp_access_token:
            return {"x-ucdp-access-token": self.settings.ucdp_access_token}
        return {}

    def _parse_event(self, raw: dict) -> dict:
        vtype = int(raw.get("type_of_violence", 0))
        lat_str = str(raw.get("latitude", ""))
        lon_str = str(raw.get("longitude", ""))
        return {
            "source": "ucdp",
            "title": f"UCDP: {raw.get('side_a', '')} vs {raw.get('side_b', '')} in {raw.get('country', '')}",
            "url": f"https://ucdp.uu.se/event/{raw.get('id', '')}",
            "ucdp_id": str(raw.get("id", "")),
            "violence_type": vtype,
            "violence_type_label": VIOLENCE_TYPES.get(vtype, "unknown"),
            "best_estimate": int(raw.get("best", 0) or 0),
            "low_estimate": int(raw.get("low", 0) or 0),
            "high_estimate": int(raw.get("high", 0) or 0),
            "country": raw.get("country", ""),
            "region": raw.get("region", ""),
            "latitude": float(lat_str) if lat_str else None,
            "longitude": float(lon_str) if lon_str else None,
            "date_start": raw.get("date_start", ""),
            "date_end": raw.get("date_end", ""),
            "side_a": raw.get("side_a", ""),
            "side_b": raw.get("side_b", ""),
        }

    async def collect(self) -> None:
        log.info("ucdp_collection_started")
        start = time.monotonic()

        await self._ensure_collection()
        version = await self._discover_version()
        if not version:
            return

        today = datetime.now(timezone.utc).date()
        date_from = today - timedelta(days=365)
        total_new = 0

        for page in range(MAX_PAGES):
            try:
                resp = await self.http.get(
                    f"{UCDP_BASE_URL}/{version}",
                    params={
                        "pagesize": str(PAGE_SIZE),
                        "page": str(page),
                        "StartDate": date_from.isoformat(),
                        "EndDate": today.isoformat(),
                    },
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
            except Exception as exc:
                log.error("ucdp_fetch_failed", page=page, error=str(exc))
                break

            results = resp.json().get("Result", [])
            if not results:
                break

            from qdrant_client.models import PointStruct

            points: list[PointStruct] = []
            for raw in results:
                ucdp_id = str(raw.get("id", ""))
                if not ucdp_id:
                    continue

                chash = self._content_hash(ucdp_id)
                pid = self._point_id(chash)

                if await self._dedup_check(pid):
                    continue

                payload = self._parse_event(raw)
                source_text = raw.get("source_article", "")
                embed_text = f"{payload['title']}. {source_text}"[:2000]

                await process_item(
                    title=payload["title"],
                    text=embed_text,
                    url=payload["url"],
                    source="ucdp",
                    settings=self.settings,
                    redis_client=self.redis,
                )

                try:
                    point = await self._build_point(embed_text, payload, chash)
                    points.append(point)
                except Exception as exc:
                    log.warning("ucdp_embed_failed", ucdp_id=ucdp_id, error=str(exc))

            await self._batch_upsert(points)
            total_new += len(points)
            log.info("ucdp_page_ingested", page=page, new=len(points), fetched=len(results))

            if len(results) < PAGE_SIZE:
                break

        total_count = resp.json().get("TotalCount", 0) if resp else 0
        if total_count > MAX_PAGES * PAGE_SIZE:
            log.warning("ucdp_data_truncated", total=total_count, fetched=MAX_PAGES * PAGE_SIZE)

        elapsed = round(time.monotonic() - start, 2)
        log.info("ucdp_collection_finished", total_new=total_new, elapsed_seconds=elapsed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/data-ingestion && python -m pytest tests/test_ucdp_collector.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/ucdp_collector.py services/data-ingestion/tests/test_ucdp_collector.py
git commit -m "feat(data-ingestion): add UCDP conflict data collector"
```

---

### Task 5: FIRMS Collector

**Files:**
- Create: `services/data-ingestion/feeds/firms_collector.py`
- Create: `services/data-ingestion/tests/test_firms_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_firms_collector.py`:

```python
"""Tests for NASA FIRMS thermal anomaly collector."""

from __future__ import annotations

import csv
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.firms_collector import (
    FIRMSCollector,
    FIRMS_BBOXES,
    FIRMS_SATELLITES,
    is_possible_explosion,
)


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.nasa_earthdata_key = "testkey123"
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = FIRMSCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


SAMPLE_CSV = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight\n"
    "36.5000,40.7000,400.5,0.39,0.36,2026-04-01,0130,N,high,2.0NRT,290.1,95.2,N\n"
    "36.5001,40.7001,350.0,0.39,0.36,2026-04-01,0130,N,nominal,2.0NRT,280.0,50.0,D\n"
)


def test_explosion_heuristic_positive():
    assert is_possible_explosion(frp=95.2, brightness=400.5) is True


def test_explosion_heuristic_negative():
    assert is_possible_explosion(frp=50.0, brightness=350.0) is False


def test_explosion_heuristic_boundary():
    assert is_possible_explosion(frp=80.0, brightness=380.0) is False
    assert is_possible_explosion(frp=80.1, brightness=380.1) is True


def test_bboxes_have_correct_format():
    for name, bbox in FIRMS_BBOXES.items():
        parts = bbox.split(",")
        assert len(parts) == 4, f"BBOX {name} should have 4 parts"
        floats = [float(p) for p in parts]
        assert floats[0] < floats[2], f"BBOX {name}: west must be < east"
        assert floats[1] < floats[3], f"BBOX {name}: south must be < north"


def test_satellites_list():
    assert len(FIRMS_SATELLITES) == 3
    assert all(s.startswith("VIIRS_") for s in FIRMS_SATELLITES)


def test_parse_csv(collector):
    rows = collector._parse_csv(SAMPLE_CSV, "ukraine")
    assert len(rows) == 2
    assert rows[0]["latitude"] == 36.5
    assert rows[0]["frp"] == 95.2
    assert rows[0]["possible_explosion"] is True
    assert rows[0]["bbox_name"] == "ukraine"
    assert rows[1]["possible_explosion"] is False


def test_dedup_hash_ignores_satellite(collector):
    h1 = collector._firms_content_hash(36.5, 40.7, "2026-04-01", "0130")
    h2 = collector._firms_content_hash(36.5, 40.7, "2026-04-01", "0130")
    assert h1 == h2  # same location+time = same hash regardless of satellite
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && python -m pytest tests/test_firms_collector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write FIRMS collector implementation**

Create `services/data-ingestion/feeds/firms_collector.py`:

```python
"""NASA FIRMS thermal anomaly collector with explosion heuristic."""

from __future__ import annotations

import asyncio
import csv
import io
import time
from typing import Any

import structlog

from config import Settings
from feeds.base import BaseCollector
from pipeline import process_item

log = structlog.get_logger(__name__)

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

FIRMS_SATELLITES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
]

FIRMS_BBOXES = {
    "ukraine": "22,44,40,53",
    "russia": "20,50,180,82",
    "iran": "44,25,63,40",
    "israel_gaza": "34,29,36,34",
    "syria": "35,32,42,37",
    "taiwan": "119,21,123,26",
    "north_korea": "124,37,131,43",
    "saudi_arabia": "34,16,56,32",
    "turkey": "26,36,45,42",
}


def is_possible_explosion(frp: float, brightness: float) -> bool:
    return frp > 80 and brightness > 380


class FIRMSCollector(BaseCollector):
    """Fetch thermal anomalies from NASA FIRMS (3 satellites × 9 regions)."""

    def _parse_csv(self, csv_text: str, bbox_name: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = []
        for row in reader:
            try:
                lat = round(float(row["latitude"]), 4)
                lon = round(float(row["longitude"]), 4)
                brightness = float(row.get("bright_ti4", 0))
                frp = float(row.get("frp", 0))
                rows.append({
                    "source": "firms",
                    "title": f"Thermal anomaly in {bbox_name}",
                    "url": f"https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;l:noaa21-viirs;@{lon},{lat},10z",
                    "satellite": row.get("satellite", ""),
                    "brightness": brightness,
                    "frp": frp,
                    "confidence": row.get("confidence", ""),
                    "daynight": row.get("daynight", ""),
                    "bbox_name": bbox_name,
                    "latitude": lat,
                    "longitude": lon,
                    "acq_date": row.get("acq_date", ""),
                    "acq_time": row.get("acq_time", ""),
                    "possible_explosion": is_possible_explosion(frp, brightness),
                })
            except (ValueError, KeyError) as exc:
                log.warning("firms_row_parse_error", error=str(exc))
        return rows

    def _firms_content_hash(
        self, lat: float, lon: float, acq_date: str, acq_time: str
    ) -> str:
        return self._content_hash(
            f"{lat:.4f}", f"{lon:.4f}", acq_date, acq_time
        )

    async def collect(self) -> None:
        log.info("firms_collection_started")
        start = time.monotonic()

        if not self.settings.nasa_earthdata_key:
            log.warning("firms_api_key_missing")
            return

        await self._ensure_collection()
        api_key = self.settings.nasa_earthdata_key
        total_new = 0

        for bbox_name, bbox in FIRMS_BBOXES.items():
            for satellite in FIRMS_SATELLITES:
                url = f"{FIRMS_BASE_URL}/{api_key}/{satellite}/{bbox}/1"
                try:
                    resp = await self.http.get(url)
                    if resp.status_code == 429:
                        log.warning("firms_rate_limited", satellite=satellite, bbox=bbox_name)
                        await asyncio.sleep(60)
                        continue
                    resp.raise_for_status()
                except Exception as exc:
                    log.warning("firms_fetch_failed", satellite=satellite, bbox=bbox_name, error=str(exc))
                    continue

                rows = self._parse_csv(resp.text, bbox_name)

                from qdrant_client.models import PointStruct

                points: list[PointStruct] = []
                for row in rows:
                    chash = self._firms_content_hash(
                        row["latitude"], row["longitude"],
                        row["acq_date"], row["acq_time"],
                    )
                    pid = self._point_id(chash)

                    if await self._dedup_check(pid):
                        continue

                    explosion_tag = " [POSSIBLE EXPLOSION]" if row["possible_explosion"] else ""
                    embed_text = (
                        f"{row['title']}{explosion_tag}. "
                        f"FRP={row['frp']}MW, Brightness={row['brightness']}K, "
                        f"Confidence={row['confidence']}, {row['daynight']}."
                    )

                    await process_item(
                        title=row["title"] + explosion_tag,
                        text=embed_text,
                        url=row["url"],
                        source="firms",
                        settings=self.settings,
                        redis_client=self.redis,
                    )

                    try:
                        point = await self._build_point(embed_text, row, chash)
                        points.append(point)
                    except Exception as exc:
                        log.warning("firms_embed_failed", error=str(exc))

                await self._batch_upsert(points)
                total_new += len(points)

                await asyncio.sleep(6)  # 10 req/min rate limit

        elapsed = round(time.monotonic() - start, 2)
        log.info("firms_collection_finished", total_new=total_new, elapsed_seconds=elapsed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/data-ingestion && python -m pytest tests/test_firms_collector.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/firms_collector.py services/data-ingestion/tests/test_firms_collector.py
git commit -m "feat(data-ingestion): add NASA FIRMS thermal anomaly collector"
```

---

### Task 6: USGS Nuclear-Enriched Collector

**Files:**
- Create: `services/data-ingestion/feeds/usgs_collector.py`
- Create: `services/data-ingestion/tests/test_usgs_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_usgs_collector.py`:

```python
"""Tests for USGS earthquake collector with nuclear test site enrichment."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.usgs_collector import (
    USGSCollector,
    NUCLEAR_TEST_SITES,
    concern_score,
    concern_level,
    haversine_km,
)


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = USGSCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_haversine_known_distance():
    # NYC to LA ≈ 3944 km
    d = haversine_km(40.7128, -74.0060, 33.9425, -118.4081)
    assert 3900 < d < 4000


def test_haversine_same_point():
    d = haversine_km(41.28, 129.08, 41.28, 129.08)
    assert d == 0.0


def test_concern_score_near_site():
    # Right on top of Punggye-ri, shallow, M5.5
    score = concern_score(magnitude=5.5, distance_km=5.0, depth_km=2.0)
    assert score > 50  # Should be elevated or higher


def test_concern_score_far_away():
    # 90km away, deep, M4.5
    score = concern_score(magnitude=4.5, distance_km=90.0, depth_km=50.0)
    assert score < 25  # Below concern threshold


def test_concern_score_critical():
    # Direct hit: 0km, M8.0, 1km depth
    score = concern_score(magnitude=8.0, distance_km=0.0, depth_km=1.0)
    assert score >= 75  # Critical


def test_concern_level_thresholds():
    assert concern_level(80.0) == "critical"
    assert concern_level(60.0) == "elevated"
    assert concern_level(30.0) == "moderate"
    assert concern_level(10.0) is None


def test_nuclear_test_sites_count():
    assert len(NUCLEAR_TEST_SITES) == 5
    assert "Punggye-ri (DPRK)" in NUCLEAR_TEST_SITES


SAMPLE_GEOJSON = {
    "features": [
        {
            "id": "us7000test",
            "properties": {
                "mag": 5.2,
                "place": "45km NE of Kilju, North Korea",
                "time": 1712000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test",
            },
            "geometry": {
                "coordinates": [129.1, 41.3, 8.0],  # Near Punggye-ri
            },
        },
        {
            "id": "us7000far",
            "properties": {
                "mag": 6.0,
                "place": "100km S of Tokyo, Japan",
                "time": 1712000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000far",
            },
            "geometry": {
                "coordinates": [139.7, 34.7, 30.0],  # Far from any test site
            },
        },
    ]
}


def test_parse_features(collector):
    results = collector._parse_features(SAMPLE_GEOJSON["features"])
    assert len(results) == 2

    near = results[0]
    assert near["usgs_id"] == "us7000test"
    assert near["magnitude"] == 5.2
    assert near["nearest_test_site"] is not None
    assert near["concern_score"] is not None
    assert near["concern_level"] is not None

    far = results[1]
    assert far["usgs_id"] == "us7000far"
    assert far["nearest_test_site"] is None
    assert far["concern_score"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && python -m pytest tests/test_usgs_collector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write USGS collector implementation**

Create `services/data-ingestion/feeds/usgs_collector.py`:

```python
"""USGS earthquake collector with nuclear test site proximity enrichment."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from config import Settings
from feeds.base import BaseCollector
from pipeline import process_item

log = structlog.get_logger(__name__)

USGS_ENDPOINT = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"

NUCLEAR_TEST_SITES: dict[str, tuple[float, float]] = {
    "Punggye-ri (DPRK)": (41.28, 129.08),
    "Lop Nur (China)": (41.39, 89.03),
    "Novaya Zemlya (Russia)": (73.37, 54.78),
    "Nevada NTS (USA)": (37.07, -116.05),
    "Semipalatinsk (KZ)": (50.07, 78.43),
}

PROXIMITY_RADIUS_KM = 100.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def concern_score(magnitude: float, distance_km: float, depth_km: float) -> float:
    mag_factor = (magnitude / 9.0) * 0.6
    dist_factor = ((PROXIMITY_RADIUS_KM - distance_km) / PROXIMITY_RADIUS_KM) * 0.25
    if depth_km < 5:
        df = 1.0
    elif depth_km < 15:
        df = 0.5
    else:
        df = 0.1
    depth_factor = df * 0.15
    return round((mag_factor + dist_factor + depth_factor) * 100, 1)


def concern_level(score: float) -> str | None:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "elevated"
    if score >= 25:
        return "moderate"
    return None


class USGSCollector(BaseCollector):
    """Fetch earthquakes from USGS and enrich with nuclear test site proximity."""

    def _find_nearest_test_site(
        self, lat: float, lon: float
    ) -> tuple[str, float] | None:
        nearest_name = None
        nearest_dist = float("inf")
        for name, (site_lat, site_lon) in NUCLEAR_TEST_SITES.items():
            dist = haversine_km(lat, lon, site_lat, site_lon)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_name = name
        if nearest_dist <= PROXIMITY_RADIUS_KM:
            return (nearest_name, round(nearest_dist, 1))
        return None

    def _parse_features(self, features: list[dict]) -> list[dict]:
        results = []
        for feat in features:
            props = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [0, 0, 0])
            lon, lat, depth = coords[0], coords[1], coords[2]
            magnitude = float(props.get("mag", 0))
            usgs_id = feat.get("id", "")

            payload = {
                "source": "usgs",
                "title": f"M{magnitude} - {props.get('place', 'Unknown')}",
                "url": props.get("url", f"https://earthquake.usgs.gov/earthquakes/eventpage/{usgs_id}"),
                "usgs_id": usgs_id,
                "magnitude": magnitude,
                "depth_km": round(depth, 1),
                "place": props.get("place", ""),
                "latitude": lat,
                "longitude": lon,
                "event_time": datetime.fromtimestamp(
                    props.get("time", 0) / 1000, tz=timezone.utc
                ).isoformat(),
                "nearest_test_site": None,
                "distance_km": None,
                "concern_score": None,
                "concern_level": None,
            }

            site_match = self._find_nearest_test_site(lat, lon)
            if site_match:
                site_name, dist = site_match
                score = concern_score(magnitude, dist, depth)
                level = concern_level(score)
                if level:  # Only enrich if above threshold
                    payload["nearest_test_site"] = site_name
                    payload["distance_km"] = dist
                    payload["concern_score"] = score
                    payload["concern_level"] = level

            results.append(payload)
        return results

    async def _write_nuclear_enrichment(
        self, usgs_url: str, site_name: str, distance_km: float,
        score: float, level: str
    ) -> None:
        statements = [
            {
                "statement": (
                    "MERGE (s:NuclearTestSite {name: $name}) "
                    "SET s.latitude = $lat, s.longitude = $lon"
                ),
                "parameters": {
                    "name": site_name,
                    "lat": NUCLEAR_TEST_SITES[site_name][0],
                    "lon": NUCLEAR_TEST_SITES[site_name][1],
                },
            },
            {
                "statement": (
                    "MATCH (d:Document {url: $usgs_url})-[:DESCRIBES]->(e:Event) "
                    "MATCH (s:NuclearTestSite {name: $site_name}) "
                    "MERGE (e)-[:NEAR_TEST_SITE {distance_km: $dist, "
                    "concern_score: $score, concern_level: $level}]->(s)"
                ),
                "parameters": {
                    "usgs_url": usgs_url,
                    "site_name": site_name,
                    "dist": distance_km,
                    "score": score,
                    "level": level,
                },
            },
        ]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.settings.neo4j_url}/db/neo4j/tx/commit",
                    json={"statements": statements},
                    auth=(self.settings.neo4j_user, self.settings.neo4j_password),
                )
                resp.raise_for_status()
        except Exception as exc:
            log.warning("usgs_nuclear_neo4j_failed", site=site_name, error=str(exc))

    async def collect(self) -> None:
        log.info("usgs_collection_started")
        start = time.monotonic()

        await self._ensure_collection()

        try:
            resp = await self.http.get(USGS_ENDPOINT)
            resp.raise_for_status()
        except Exception as exc:
            log.error("usgs_fetch_failed", error=str(exc))
            return

        geojson = resp.json()
        features = geojson.get("features", [])
        parsed = self._parse_features(features)

        from qdrant_client.models import PointStruct

        points: list[PointStruct] = []
        for payload in parsed:
            chash = self._content_hash(payload["usgs_id"])
            pid = self._point_id(chash)

            if await self._dedup_check(pid):
                continue

            embed_text = f"{payload['title']}. Depth: {payload['depth_km']}km."
            if payload["concern_level"]:
                embed_text += (
                    f" NUCLEAR CONCERN: {payload['concern_level']} "
                    f"({payload['concern_score']}) near {payload['nearest_test_site']}."
                )

            await process_item(
                title=payload["title"],
                text=embed_text,
                url=payload["url"],
                source="usgs",
                settings=self.settings,
                redis_client=self.redis,
            )

            if payload["concern_level"]:
                await self._write_nuclear_enrichment(
                    payload["url"],
                    payload["nearest_test_site"],
                    payload["distance_km"],
                    payload["concern_score"],
                    payload["concern_level"],
                )

            try:
                point = await self._build_point(embed_text, payload, chash)
                points.append(point)
            except Exception as exc:
                log.warning("usgs_embed_failed", usgs_id=payload["usgs_id"], error=str(exc))

        await self._batch_upsert(points)

        elapsed = round(time.monotonic() - start, 2)
        nuclear_count = sum(1 for p in parsed if p["concern_level"])
        log.info(
            "usgs_collection_finished",
            total_new=len(points),
            nuclear_enriched=nuclear_count,
            elapsed_seconds=elapsed,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/data-ingestion && python -m pytest tests/test_usgs_collector.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/usgs_collector.py services/data-ingestion/tests/test_usgs_collector.py
git commit -m "feat(data-ingestion): add USGS earthquake collector with nuclear enrichment"
```

---

### Task 7: Military Aircraft Collector

**Files:**
- Create: `services/data-ingestion/feeds/military_aircraft_collector.py`
- Create: `services/data-ingestion/tests/test_military_aircraft_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_military_aircraft_collector.py`:

```python
"""Tests for military aircraft collector (adsb.fi + OpenSky fallback)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.military_aircraft_collector import (
    MilitaryAircraftCollector,
    MILITARY_ICAO_RANGES,
    REGION_BBOXES,
    identify_branch,
    classify_region,
)


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.opensky_client_id = ""
    s.opensky_client_secret = ""
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = MilitaryAircraftCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_identify_branch_usaf():
    assert identify_branch("ADF7C8") == "USAF"
    assert identify_branch("AFFFFF") == "USAF"


def test_identify_branch_raf():
    assert identify_branch("400000") == "RAF"
    assert identify_branch("43C000") == "RAF"


def test_identify_branch_nato():
    assert identify_branch("4D0000") == "NATO"


def test_identify_branch_unknown():
    assert identify_branch("000000") is None
    assert identify_branch("FFFFFF") is None


def test_identify_branch_gaf():
    assert identify_branch("3EA000") == "GAF"


def test_identify_branch_faf():
    assert identify_branch("3AA000") == "FAF"


def test_identify_branch_iaf():
    assert identify_branch("738A00") == "IAF"


def test_classify_region():
    assert classify_region(48.0, 35.0) == "ukraine"
    assert classify_region(33.0, 44.0) == "iran"
    assert classify_region(0.0, 0.0) == "unknown"


SAMPLE_ADSB_FI_RESPONSE = {
    "ac": [
        {
            "hex": "ADF7C8",
            "flight": "RCH401  ",
            "lat": 48.5,
            "lon": 35.2,
            "alt_baro": 35000,
            "gs": 450.0,
            "track": 90.0,
            "t": "C17",
            "r": "05-5139",
        },
    ],
    "now": 1712000000,
    "total": 1,
}


def test_parse_adsb_fi(collector):
    aircraft = collector._parse_adsb_fi(SAMPLE_ADSB_FI_RESPONSE)
    assert len(aircraft) == 1
    ac = aircraft[0]
    assert ac["icao24"] == "adf7c8"
    assert ac["callsign"] == "RCH401"
    assert ac["military_branch"] == "USAF"
    assert ac["latitude"] == 48.5
    assert ac["altitude_m"] == 35000 * 0.3048  # ft to m
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && python -m pytest tests/test_military_aircraft_collector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write military aircraft collector implementation**

Create `services/data-ingestion/feeds/military_aircraft_collector.py`:

```python
"""Military aircraft collector — adsb.fi primary, OpenSky fallback."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from config import Settings
from feeds.base import BaseCollector

log = structlog.get_logger(__name__)

ADSB_FI_MIL_URL = "https://api.adsb.fi/v2/mil"

MILITARY_ICAO_RANGES: dict[str, list[tuple[str, str]]] = {
    "USAF": [("ADF7C8", "AFFFFF")],
    "RAF": [("400000", "40003F"), ("43C000", "43CFFF")],
    "FAF": [("3AA000", "3AFFFF"), ("3B7000", "3BFFFF")],
    "GAF": [("3EA000", "3EBFFF"), ("3F4000", "3FBFFF")],
    "IAF": [("738A00", "738BFF")],
    "NATO": [("4D0000", "4D03FF")],
}

REGION_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "ukraine": (22, 44, 40, 53),
    "russia": (20, 50, 180, 82),
    "iran": (44, 25, 63, 40),
    "israel_gaza": (34, 29, 36, 34),
    "syria": (35, 32, 42, 37),
    "taiwan": (119, 21, 123, 26),
    "north_korea": (124, 37, 131, 43),
    "saudi_arabia": (34, 16, 56, 32),
    "turkey": (26, 36, 45, 42),
    "pacific": (107, 10, 143, 46),
    "western": (-10, 13, 57, 85),
}


def identify_branch(icao24: str) -> str | None:
    hex_val = int(icao24, 16)
    for branch, ranges in MILITARY_ICAO_RANGES.items():
        for start, end in ranges:
            if int(start, 16) <= hex_val <= int(end, 16):
                return branch
    return None


def classify_region(lat: float, lon: float) -> str:
    for name, (west, south, east, north) in REGION_BBOXES.items():
        if name in ("pacific", "western"):
            continue  # Skip meta-regions
        if south <= lat <= north and west <= lon <= east:
            return name
    return "unknown"


class MilitaryAircraftCollector(BaseCollector):
    """Collect military aircraft positions from adsb.fi with OpenSky fallback."""

    def _parse_adsb_fi(self, data: dict) -> list[dict]:
        aircraft_list = data.get("ac", [])
        results = []
        for ac in aircraft_list:
            icao24 = ac.get("hex", "").lower().strip()
            lat = ac.get("lat")
            lon = ac.get("lon")
            if not icao24 or lat is None or lon is None:
                continue

            callsign = ac.get("flight", "").strip()
            alt_baro = ac.get("alt_baro", 0) or 0
            gs = ac.get("gs", 0) or 0
            heading = ac.get("track", 0) or 0

            results.append({
                "source": "military_aircraft",
                "title": f"{identify_branch(icao24) or 'Military'} aircraft {callsign} over {classify_region(lat, lon)}",
                "url": f"https://globe.adsb.fi/?icao={icao24}",
                "icao24": icao24,
                "callsign": callsign,
                "origin_country": "",
                "military_branch": identify_branch(icao24),
                "latitude": lat,
                "longitude": lon,
                "altitude_m": round(alt_baro * 0.3048, 1),
                "velocity_ms": round(gs * 0.5144, 1),
                "on_ground": alt_baro == 0 or ac.get("alt_baro") == "ground",
                "heading": heading,
            })
        return results

    async def _write_neo4j(self, aircraft: dict) -> None:
        statements = [
            {
                "statement": (
                    "MERGE (a:MilitaryAircraft {icao24: $icao24}) "
                    "SET a.callsign = $callsign, "
                    "a.military_branch = $branch, "
                    "a.last_seen = $timestamp"
                ),
                "parameters": {
                    "icao24": aircraft["icao24"],
                    "callsign": aircraft["callsign"],
                    "branch": aircraft["military_branch"] or "unknown",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            },
            {
                "statement": (
                    "MERGE (l:Location {name: $location}) "
                    "SET l.latitude = $lat, l.longitude = $lon"
                ),
                "parameters": {
                    "location": classify_region(aircraft["latitude"], aircraft["longitude"]),
                    "lat": aircraft["latitude"],
                    "lon": aircraft["longitude"],
                },
            },
            {
                "statement": (
                    "MATCH (a:MilitaryAircraft {icao24: $icao24}) "
                    "MATCH (l:Location {name: $location}) "
                    "MERGE (a)-[:SPOTTED_AT {timestamp: $ts, altitude: $alt, velocity: $vel}]->(l)"
                ),
                "parameters": {
                    "icao24": aircraft["icao24"],
                    "location": classify_region(aircraft["latitude"], aircraft["longitude"]),
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "alt": aircraft["altitude_m"],
                    "vel": aircraft["velocity_ms"],
                },
            },
        ]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.settings.neo4j_url}/db/neo4j/tx/commit",
                    json={"statements": statements},
                    auth=(self.settings.neo4j_user, self.settings.neo4j_password),
                )
                resp.raise_for_status()
        except Exception as exc:
            log.warning("military_neo4j_failed", icao24=aircraft["icao24"], error=str(exc))

    async def collect(self) -> None:
        log.info("military_aircraft_collection_started")
        start = time.monotonic()

        await self._ensure_collection()

        # Primary: adsb.fi
        try:
            resp = await self.http.get(ADSB_FI_MIL_URL)
            resp.raise_for_status()
            aircraft_data = self._parse_adsb_fi(resp.json())
            log.info("adsb_fi_military_fetched", count=len(aircraft_data))
        except Exception as exc:
            log.warning("adsb_fi_military_failed_trying_opensky", error=str(exc))
            aircraft_data = []
            # Fallback: OpenSky (only if credentials configured)
            if self.settings.opensky_client_id and self.settings.opensky_client_secret:
                aircraft_data = await self._fetch_opensky()

        # Round timestamp to 15-min window for dedup
        now = datetime.now(timezone.utc)
        ts_rounded = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0).isoformat()

        from qdrant_client.models import PointStruct

        points: list[PointStruct] = []
        for ac in aircraft_data:
            chash = self._content_hash(ac["icao24"], ts_rounded)
            pid = self._point_id(chash)

            if await self._dedup_check(pid):
                continue

            await self._write_neo4j(ac)

            embed_text = (
                f"{ac['title']}. "
                f"Alt: {ac['altitude_m']}m, Speed: {ac['velocity_ms']}m/s, "
                f"Heading: {ac['heading']}°."
            )

            try:
                point = await self._build_point(embed_text, ac, chash)
                points.append(point)
            except Exception as exc:
                log.warning("military_embed_failed", icao24=ac["icao24"], error=str(exc))

        await self._batch_upsert(points)

        elapsed = round(time.monotonic() - start, 2)
        log.info(
            "military_aircraft_collection_finished",
            total_new=len(points),
            total_fetched=len(aircraft_data),
            elapsed_seconds=elapsed,
        )

    async def _fetch_opensky(self) -> list[dict]:
        log.info("opensky_fallback_starting")
        # Simplified: would need OAuth token fetch + region queries
        # For now, return empty — OpenSky is a fallback
        log.warning("opensky_fallback_not_yet_implemented")
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/data-ingestion && python -m pytest tests/test_military_aircraft_collector.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/military_aircraft_collector.py services/data-ingestion/tests/test_military_aircraft_collector.py
git commit -m "feat(data-ingestion): add military aircraft collector (adsb.fi + OpenSky)"
```

---

### Task 8: OFAC Sanctions Collector

**Files:**
- Create: `services/data-ingestion/feeds/ofac_collector.py`
- Create: `services/data-ingestion/tests/test_ofac_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_ofac_collector.py`:

```python
"""Tests for OFAC sanctions collector with XML parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.ofac_collector import OFACCollector, parse_sdn_xml


SAMPLE_SDN_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML">
  <publshInformation>
    <Publish_Date>04/01/2026</Publish_Date>
  </publshInformation>
  <sdnEntry>
    <uid>12345</uid>
    <sdnType>Entity</sdnType>
    <lastName>MEGA SHIPPING LLC</lastName>
    <programList>
      <program>IRAN</program>
      <program>SDGT</program>
    </programList>
    <akaList>
      <aka>
        <uid>1001</uid>
        <type>a.k.a.</type>
        <lastName>MEGA MARINE</lastName>
      </aka>
    </akaList>
    <idList>
      <id>
        <uid>2001</uid>
        <idType>IMO Number</idType>
        <idNumber>9123456</idNumber>
        <idCountry>IR</idCountry>
      </id>
      <id>
        <uid>2002</uid>
        <idType>Registration Number</idType>
        <idNumber>REG-99</idNumber>
      </id>
    </idList>
    <addressList>
      <address>
        <uid>3001</uid>
        <country>Iran</country>
        <city>Tehran</city>
      </address>
    </addressList>
  </sdnEntry>
  <sdnEntry>
    <uid>67890</uid>
    <sdnType>Individual</sdnType>
    <lastName>DOE</lastName>
    <firstName>John</firstName>
    <programList>
      <program>UKRAINE-EO13661</program>
    </programList>
  </sdnEntry>
</sdnList>
"""


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = OFACCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_parse_sdn_xml_entity_count():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    assert len(entries) == 2


def test_parse_sdn_xml_entity_fields():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert entity["ofac_id"] == "12345"
    assert entity["entity_type"] == "Entity"
    assert entity["full_name"] == "MEGA SHIPPING LLC"
    assert entity["programs"] == ["IRAN", "SDGT"]


def test_parse_sdn_xml_aliases():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert "MEGA MARINE" in entity["aliases"]


def test_parse_sdn_xml_identifiers():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert len(entity["identifiers"]) == 2
    imo = next(i for i in entity["identifiers"] if i["type"] == "IMO Number")
    assert imo["value"] == "9123456"
    assert imo["country"] == "IR"


def test_parse_sdn_xml_addresses():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert len(entity["addresses"]) == 1
    assert entity["addresses"][0]["country"] == "Iran"
    assert entity["addresses"][0]["city"] == "Tehran"


def test_parse_sdn_xml_individual():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    person = entries[1]
    assert person["entity_type"] == "Individual"
    assert person["full_name"] == "John DOE"
    assert person["programs"] == ["UKRAINE-EO13661"]
    assert person["aliases"] == []
    assert person["identifiers"] == []


def test_build_embed_text(collector):
    entry = {
        "full_name": "MEGA SHIPPING LLC",
        "aliases": ["MEGA MARINE"],
        "programs": ["IRAN", "SDGT"],
    }
    text = collector._build_embed_text(entry)
    assert "MEGA SHIPPING LLC" in text
    assert "MEGA MARINE" in text
    assert "IRAN" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && python -m pytest tests/test_ofac_collector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write OFAC collector implementation**

Create `services/data-ingestion/feeds/ofac_collector.py`:

```python
"""OFAC SDN sanctions list collector with full XML parsing."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from lxml import etree

from config import Settings
from feeds.base import BaseCollector

log = structlog.get_logger(__name__)

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/sdn_advanced.xml"

# Namespace used in OFAC XML
NS = {"ns": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML"}


def _text(el: etree._Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_sdn_xml(xml_text: str) -> list[dict]:
    root = etree.fromstring(xml_text.encode("utf-8"))
    entries = []

    for entry in root.findall(".//ns:sdnEntry", NS):
        uid = _text(entry.find("ns:uid", NS))
        sdn_type = _text(entry.find("ns:sdnType", NS))
        last_name = _text(entry.find("ns:lastName", NS))
        first_name = _text(entry.find("ns:firstName", NS))
        full_name = f"{first_name} {last_name}".strip() if first_name else last_name

        programs = [
            _text(p) for p in entry.findall(".//ns:programList/ns:program", NS)
        ]

        aliases = []
        for aka in entry.findall(".//ns:akaList/ns:aka", NS):
            aka_last = _text(aka.find("ns:lastName", NS))
            aka_first = _text(aka.find("ns:firstName", NS))
            aka_name = f"{aka_first} {aka_last}".strip() if aka_first else aka_last
            if aka_name:
                aliases.append(aka_name)

        identifiers = []
        for id_el in entry.findall(".//ns:idList/ns:id", NS):
            id_type = _text(id_el.find("ns:idType", NS))
            id_value = _text(id_el.find("ns:idNumber", NS))
            id_country = _text(id_el.find("ns:idCountry", NS))
            if id_type and id_value:
                identifiers.append({
                    "type": id_type,
                    "value": id_value,
                    "country": id_country,
                })

        addresses = []
        for addr in entry.findall(".//ns:addressList/ns:address", NS):
            country = _text(addr.find("ns:country", NS))
            city = _text(addr.find("ns:city", NS))
            if country:
                addresses.append({"country": country, "city": city})

        entries.append({
            "ofac_id": uid,
            "entity_type": sdn_type,
            "full_name": full_name,
            "programs": programs,
            "aliases": aliases,
            "identifiers": identifiers,
            "addresses": addresses,
        })

    return entries


class OFACCollector(BaseCollector):
    """Fetch and parse OFAC SDN sanctions list into Neo4j + Qdrant."""

    def _build_embed_text(self, entry: dict) -> str:
        parts = [entry["full_name"]]
        if entry["aliases"]:
            parts.append(f"AKA: {', '.join(entry['aliases'])}")
        if entry["programs"]:
            parts.append(f"Programs: {', '.join(entry['programs'])}")
        return " | ".join(parts)

    async def _write_neo4j_sanctions(self, entry: dict) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        statements = [
            {
                "statement": (
                    "MERGE (e:SanctionedEntity {ofac_id: $uid}) "
                    "SET e.name = $name, e.type = $sdn_type, e.updated_at = $ts"
                ),
                "parameters": {
                    "uid": entry["ofac_id"],
                    "name": entry["full_name"],
                    "sdn_type": entry["entity_type"],
                    "ts": timestamp,
                },
            },
        ]

        for program in entry["programs"]:
            statements.append({
                "statement": (
                    "MERGE (p:SanctionsProgram {name: $program}) "
                    "WITH p "
                    "MATCH (e:SanctionedEntity {ofac_id: $uid}) "
                    "MERGE (e)-[:SANCTIONED_UNDER]->(p)"
                ),
                "parameters": {"program": program, "uid": entry["ofac_id"]},
            })

        for alias in entry["aliases"]:
            statements.append({
                "statement": (
                    "MERGE (a:Alias {name: $alias_name}) "
                    "WITH a "
                    "MATCH (e:SanctionedEntity {ofac_id: $uid}) "
                    "MERGE (e)-[:HAS_ALIAS]->(a)"
                ),
                "parameters": {"alias_name": alias, "uid": entry["ofac_id"]},
            })

        for ident in entry["identifiers"]:
            statements.append({
                "statement": (
                    "MERGE (i:Identifier {type: $id_type, value: $id_value}) "
                    "SET i.country = $id_country "
                    "WITH i "
                    "MATCH (e:SanctionedEntity {ofac_id: $uid}) "
                    "MERGE (e)-[:HAS_ID]->(i)"
                ),
                "parameters": {
                    "id_type": ident["type"],
                    "id_value": ident["value"],
                    "id_country": ident["country"],
                    "uid": entry["ofac_id"],
                },
            })

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.settings.neo4j_url}/db/neo4j/tx/commit",
                    json={"statements": statements},
                    auth=(self.settings.neo4j_user, self.settings.neo4j_password),
                )
                resp.raise_for_status()
        except Exception as exc:
            log.error("ofac_neo4j_failed", ofac_id=entry["ofac_id"], error=str(exc))

    async def collect(self) -> None:
        log.info("ofac_collection_started")
        start = time.monotonic()

        await self._ensure_collection()

        try:
            resp = await self.http.get(SDN_URL, timeout=120.0)
            resp.raise_for_status()
        except Exception as exc:
            log.error("ofac_fetch_failed", error=str(exc))
            return

        entries = parse_sdn_xml(resp.text)
        log.info("ofac_xml_parsed", total_entries=len(entries))

        from qdrant_client.models import PointStruct

        points: list[PointStruct] = []
        for entry in entries:
            chash = self._content_hash("ofac", entry["ofac_id"])
            pid = self._point_id(chash)

            # OFAC re-ingests update existing entries (MERGE in Neo4j)
            # but skip Qdrant re-embed if already present
            is_dup = await self._dedup_check(pid)

            await self._write_neo4j_sanctions(entry)

            if is_dup:
                continue

            embed_text = self._build_embed_text(entry)
            payload = {
                "source": "ofac",
                "title": f"OFAC SDN: {entry['full_name']} ({entry['entity_type']})",
                "url": f"https://sanctionssearch.ofac.treas.gov/Details.aspx?id={entry['ofac_id']}",
                "ofac_id": entry["ofac_id"],
                "entity_type": entry["entity_type"],
                "programs": entry["programs"],
                "aliases": entry["aliases"],
                "identifiers": entry["identifiers"],
                "addresses": entry["addresses"],
            }

            try:
                point = await self._build_point(embed_text, payload, chash)
                points.append(point)
            except Exception as exc:
                log.warning("ofac_embed_failed", ofac_id=entry["ofac_id"], error=str(exc))

        await self._batch_upsert(points)

        elapsed = round(time.monotonic() - start, 2)
        log.info(
            "ofac_collection_finished",
            total_entries=len(entries),
            new_qdrant=len(points),
            elapsed_seconds=elapsed,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/data-ingestion && python -m pytest tests/test_ofac_collector.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/ofac_collector.py services/data-ingestion/tests/test_ofac_collector.py
git commit -m "feat(data-ingestion): add OFAC sanctions collector with XML parsing"
```

---

### Task 9: Scheduler Registration

**Files:**
- Modify: `services/data-ingestion/scheduler.py`

- [ ] **Step 1: Add imports for new collectors**

Add after existing imports (line 20):

```python
from feeds.acled_collector import ACLEDCollector
from feeds.ucdp_collector import UCDPCollector
from feeds.firms_collector import FIRMSCollector
from feeds.usgs_collector import USGSCollector
from feeds.military_aircraft_collector import MilitaryAircraftCollector
from feeds.ofac_collector import OFACCollector
```

- [ ] **Step 2: Add job wrapper functions**

Add after `run_telegram_collector()` (line 107):

```python
async def run_acled_collector() -> None:
    """Collect ACLED conflict events."""
    collector = ACLEDCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("acled_job_failed")
    finally:
        await collector.close()


async def run_ucdp_collector() -> None:
    """Collect UCDP GED conflict events."""
    collector = UCDPCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("ucdp_job_failed")
    finally:
        await collector.close()


async def run_firms_collector() -> None:
    """Collect NASA FIRMS thermal anomalies."""
    collector = FIRMSCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("firms_job_failed")
    finally:
        await collector.close()


async def run_usgs_collector() -> None:
    """Collect USGS earthquakes with nuclear enrichment."""
    collector = USGSCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("usgs_job_failed")
    finally:
        await collector.close()


async def run_military_collector() -> None:
    """Collect military aircraft positions."""
    collector = MilitaryAircraftCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("military_job_failed")
    finally:
        await collector.close()


async def run_ofac_collector() -> None:
    """Collect OFAC sanctions list."""
    collector = OFACCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("ofac_job_failed")
    finally:
        await collector.close()
```

- [ ] **Step 3: Register jobs in create_scheduler()**

Add after the telegram_collector job registration (line 166), before `return scheduler`:

```python
    # --- Hugin P0 Collectors ---

    # ACLED conflict events — default every 6 hours
    scheduler.add_job(
        run_acled_collector,
        trigger=IntervalTrigger(hours=settings.acled_interval_hours),
        id="acled_collector",
        name="ACLED Conflict Collector",
        replace_existing=True,
    )

    # UCDP GED — default every 12 hours
    scheduler.add_job(
        run_ucdp_collector,
        trigger=IntervalTrigger(hours=settings.ucdp_interval_hours),
        id="ucdp_collector",
        name="UCDP GED Collector",
        replace_existing=True,
    )

    # NASA FIRMS — default every 2 hours
    scheduler.add_job(
        run_firms_collector,
        trigger=IntervalTrigger(hours=settings.firms_interval_hours),
        id="firms_collector",
        name="FIRMS Thermal Anomaly Collector",
        replace_existing=True,
    )

    # USGS Earthquakes — default every 6 hours
    scheduler.add_job(
        run_usgs_collector,
        trigger=IntervalTrigger(hours=settings.usgs_interval_hours),
        id="usgs_collector",
        name="USGS Nuclear Earthquake Collector",
        replace_existing=True,
    )

    # Military Aircraft — default every 15 minutes
    scheduler.add_job(
        run_military_collector,
        trigger=IntervalTrigger(minutes=settings.military_interval_minutes),
        id="military_aircraft_collector",
        name="Military Aircraft Collector",
        replace_existing=True,
    )

    # OFAC Sanctions — daily at 03:30 UTC
    scheduler.add_job(
        run_ofac_collector,
        trigger=CronTrigger(hour=3, minute=30, timezone="UTC"),
        id="ofac_collector",
        name="OFAC Sanctions Collector",
        replace_existing=True,
    )
```

- [ ] **Step 4: Add new collectors to initial run**

Add to the `initial_tasks` list in `main()` (line 197-203):

```python
    initial_tasks = [
        run_rss_collector(),
        run_gdelt_collector(),
        run_tle_updater(),
        run_hotspot_updater(),
        run_telegram_collector(),
        run_acled_collector(),
        run_ucdp_collector(),
        run_firms_collector(),
        run_usgs_collector(),
        run_military_collector(),
        # OFAC runs daily via cron, not on initial startup
    ]
```

- [ ] **Step 5: Verify import works**

Run: `cd services/data-ingestion && python -c "from scheduler import create_scheduler; s = create_scheduler(); print(f'{len(s.get_jobs())} jobs registered')"`
Expected: `11 jobs registered`

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/scheduler.py
git commit -m "feat(data-ingestion): register 6 Hugin P0 collectors in scheduler"
```

---

### Task 10: Integration Smoke Test

**Files:**
- None created — verification only

- [ ] **Step 1: Run all data-ingestion tests**

Run: `cd services/data-ingestion && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (existing + 48 new tests across 7 test files)

- [ ] **Step 2: Run ruff lint**

Run: `cd services/data-ingestion && uv run ruff check feeds/ tests/`
Expected: No errors

- [ ] **Step 3: Verify all imports resolve**

Run: `cd services/data-ingestion && python -c "from feeds.base import BaseCollector; from feeds.acled_collector import ACLEDCollector; from feeds.ucdp_collector import UCDPCollector; from feeds.firms_collector import FIRMSCollector; from feeds.usgs_collector import USGSCollector; from feeds.military_aircraft_collector import MilitaryAircraftCollector; from feeds.ofac_collector import OFACCollector; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(data-ingestion): address lint/test issues in Hugin P0 collectors"
```
