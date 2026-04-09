# FIRMS-ACLED Cross-Correlation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Batch-Job that correlates FIRMS thermal anomalies with ACLED conflict events and writes `CORROBORATED_BY` relationships to Neo4j with confidence scores.

**Architecture:** Periodic job scrolls Qdrant for new FIRMS `possible_explosion=true` events, finds nearby ACLED events via bbox + haversine filter, scores matches, writes Document-to-Document relationships in Neo4j. Tracks last-run in Redis for incremental processing.

**Tech Stack:** Python 3.12, qdrant-client, httpx (Neo4j HTTP API), redis.asyncio, APScheduler

**Spec:** `docs/superpowers/specs/2026-04-09-firms-acled-correlation-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `services/data-ingestion/feeds/geo.py` | Shared `haversine_km()` extracted from usgs_collector |
| `services/data-ingestion/feeds/correlation_job.py` | Batch correlation logic |
| `services/data-ingestion/tests/test_geo.py` | Geo utility tests |
| `services/data-ingestion/tests/test_correlation_job.py` | Correlation tests |

### Modified Files

| File | Changes |
|------|---------|
| `services/data-ingestion/feeds/usgs_collector.py` | Replace local `haversine_km` with import from `geo.py` |
| `services/data-ingestion/feeds/base.py` | Add `ingested_epoch` to `_build_point()` |
| `services/data-ingestion/config.py` | Add `correlation_*` settings |
| `services/data-ingestion/scheduler.py` | Register correlation job |

---

### Task 1: Extract haversine_km into shared geo module

**Files:**
- Create: `services/data-ingestion/feeds/geo.py`
- Create: `services/data-ingestion/tests/test_geo.py`
- Modify: `services/data-ingestion/feeds/usgs_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_geo.py`:

```python
"""Tests for shared geospatial utilities."""

from feeds.geo import haversine_km


def test_haversine_known_distance():
    """NYC to LA ≈ 3944 km."""
    d = haversine_km(40.7128, -74.0060, 33.9425, -118.4081)
    assert 3900 < d < 4000


def test_haversine_same_point():
    d = haversine_km(41.28, 129.08, 41.28, 129.08)
    assert d == 0.0


def test_haversine_short_distance():
    """Two points ~1.1km apart in central London."""
    d = haversine_km(51.5074, -0.1278, 51.5174, -0.1278)
    assert 1.0 < d < 1.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_geo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'feeds.geo'`

- [ ] **Step 3: Create geo.py with haversine_km**

Create `services/data-ingestion/feeds/geo.py`:

```python
"""Shared geospatial utilities."""

from __future__ import annotations

import math


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in km between two WGS-84 points."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return r * 2 * math.asin(math.sqrt(a))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_geo.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Update usgs_collector.py to import from geo.py**

In `services/data-ingestion/feeds/usgs_collector.py`, replace the local `haversine_km` function (lines 41-50) with an import:

Remove the `import math` (line 5) and the `haversine_km` function definition (lines 41-50). Add import:

```python
from feeds.geo import haversine_km
```

Keep `import math` only if used elsewhere in the file (it is — for `concern_score`). Check: `concern_score` uses `min()` and `max()`, not `math.*`. So `import math` can be removed.

- [ ] **Step 6: Run existing USGS tests to verify nothing broke**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_usgs_collector.py tests/test_geo.py -v`
Expected: All tests PASS (8 USGS + 3 geo)

- [ ] **Step 7: Commit**

```bash
git add services/data-ingestion/feeds/geo.py services/data-ingestion/tests/test_geo.py services/data-ingestion/feeds/usgs_collector.py
git commit -m "refactor(data-ingestion): extract haversine_km into shared geo module"
```

---

### Task 2: Add ingested_epoch to BaseCollector + Config extensions

**Files:**
- Modify: `services/data-ingestion/feeds/base.py:87-94`
- Modify: `services/data-ingestion/config.py` (add before `model_config` at line 87)

- [ ] **Step 1: Add ingested_epoch to _build_point()**

In `services/data-ingestion/feeds/base.py`, modify `_build_point()` (line 93) to add `ingested_epoch`:

```python
    async def _build_point(
        self, text: str, payload: dict, content_hash: str
    ) -> PointStruct:
        vector = await self._embed(text)
        point_id = self._point_id(content_hash)
        payload["content_hash"] = content_hash
        now = datetime.now(UTC)
        payload["ingested_at"] = now.isoformat()
        payload["ingested_epoch"] = now.timestamp()
        return PointStruct(id=point_id, vector=vector, payload=payload)
```

- [ ] **Step 2: Add correlation config fields**

In `services/data-ingestion/config.py`, add before `model_config` (line 87):

```python
    # FIRMS-ACLED Correlation
    correlation_radius_km: float = 50.0
    correlation_time_window_days: int = 1
    correlation_min_score: float = 0.3
    correlation_interval_hours: int = 2
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_base_collector.py -v`
Expected: All 8 tests PASS

- [ ] **Step 4: Commit**

```bash
git add services/data-ingestion/feeds/base.py services/data-ingestion/config.py
git commit -m "feat(data-ingestion): add ingested_epoch to payloads + correlation config"
```

---

### Task 3: Correlation score function + tests

**Files:**
- Create: `services/data-ingestion/feeds/correlation_job.py` (partial — score function only)
- Create: `services/data-ingestion/tests/test_correlation_job.py` (partial — score tests only)

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_correlation_job.py`:

```python
"""Tests for FIRMS-ACLED cross-correlation job."""

from __future__ import annotations

from feeds.correlation_job import correlation_score


def test_score_close_same_day_explosion():
    """5km, same day, possible_explosion, Explosions type, high confidence → ≥ 0.8."""
    score = correlation_score(
        distance_km=5.0,
        days_diff=0,
        possible_explosion=True,
        acled_event_type="Explosions/Remote violence",
        firms_confidence="high",
    )
    assert score >= 0.8


def test_score_far_next_day():
    """45km, next day, no explosion, Battles type, nominal confidence → < 0.5."""
    score = correlation_score(
        distance_km=45.0,
        days_diff=1,
        possible_explosion=False,
        acled_event_type="Battles",
        firms_confidence="nominal",
    )
    assert score < 0.5


def test_score_boundary_50km():
    """Exactly 50km → dist_score = 0.0, base = 0.0."""
    score = correlation_score(
        distance_km=50.0,
        days_diff=0,
        possible_explosion=False,
        acled_event_type="Battles",
        firms_confidence="nominal",
    )
    assert score == 0.0


def test_score_capped_at_1():
    """Maximum bonuses should not exceed 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        possible_explosion=True,
        acled_event_type="Explosions/Remote violence",
        firms_confidence="high",
    )
    assert score == 1.0


def test_score_zero_km_same_day_no_bonus():
    """0km, same day, no bonuses → base = 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        possible_explosion=False,
        acled_event_type="Battles",
        firms_confidence="nominal",
    )
    assert score == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_correlation_job.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write correlation_score function**

Create `services/data-ingestion/feeds/correlation_job.py`:

```python
"""FIRMS-ACLED cross-correlation batch job.

Correlates FIRMS thermal anomalies (possible_explosion=true) with
ACLED conflict events within a configurable radius and time window.
Writes CORROBORATED_BY relationships to Neo4j.
"""

from __future__ import annotations


def correlation_score(
    distance_km: float,
    days_diff: int,
    possible_explosion: bool,
    acled_event_type: str,
    firms_confidence: str,
) -> float:
    """Compute correlation confidence between a FIRMS and ACLED event.

    Returns a score from 0.0 to 1.0.
    """
    # Distance: 0km = 1.0, 50km = 0.0 (linear)
    dist_score = max(0.0, 1.0 - distance_km / 50.0)

    # Time: same day = 1.0, ±1 day = 0.5
    time_score = 1.0 if days_diff == 0 else 0.5

    # Base = distance × time
    base = dist_score * time_score

    # Additive bonuses, capped at 1.0
    bonus = 0.0
    if possible_explosion:
        bonus += 0.3
    if acled_event_type == "Explosions/Remote violence":
        bonus += 0.2
    if firms_confidence == "high":
        bonus += 0.1

    return min(1.0, round(base + bonus, 2))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_correlation_job.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/correlation_job.py services/data-ingestion/tests/test_correlation_job.py
git commit -m "feat(data-ingestion): add FIRMS-ACLED correlation score function"
```

---

### Task 4: Correlation batch job — full implementation

**Files:**
- Modify: `services/data-ingestion/feeds/correlation_job.py`
- Modify: `services/data-ingestion/tests/test_correlation_job.py`

- [ ] **Step 1: Add integration tests**

Append to `services/data-ingestion/tests/test_correlation_job.py`:

```python
import math
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.correlation_job import (
    build_acled_bbox_filter,
    build_firms_filter,
    passes_time_filter,
    CorrelationJob,
)


def test_bbox_filter_equator():
    """At equator, lon_delta ≈ 0.5."""
    f = build_acled_bbox_filter(0.0, 30.0)
    # Extract range conditions from filter
    must = f.must
    lat_cond = next(c for c in must if c.key == "latitude")
    lon_cond = next(c for c in must if c.key == "longitude")
    assert lat_cond.range.gte == pytest.approx(-0.5)
    assert lat_cond.range.lte == pytest.approx(0.5)
    assert lon_cond.range.gte == pytest.approx(29.5, abs=0.05)
    assert lon_cond.range.lte == pytest.approx(30.5, abs=0.05)


def test_bbox_filter_high_latitude():
    """At 60°N, lon_delta should be wider (~1.0°)."""
    f = build_acled_bbox_filter(60.0, 30.0)
    must = f.must
    lon_cond = next(c for c in must if c.key == "longitude")
    lon_width = lon_cond.range.lte - lon_cond.range.gte
    assert lon_width > 1.5  # Should be ~2.0 at 60°N


def test_time_filter_same_day():
    assert passes_time_filter("2026-04-01", "2026-04-01", window_days=1) is True


def test_time_filter_next_day():
    assert passes_time_filter("2026-04-01", "2026-04-02", window_days=1) is True


def test_time_filter_rejects_old():
    assert passes_time_filter("2026-04-01", "2026-04-05", window_days=1) is False


def test_firms_filter_uses_epoch():
    f = build_firms_filter(1712000000.0)
    must = f.must
    epoch_cond = next(c for c in must if c.key == "ingested_epoch")
    assert epoch_cond.range.gte == 1712000000.0


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_url = "redis://localhost:6379/0"
    s.correlation_radius_km = 50.0
    s.correlation_time_window_days = 1
    s.correlation_min_score = 0.3
    return s


@pytest.fixture
def job(mock_settings):
    with patch("feeds.correlation_job.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        j = CorrelationJob(settings=mock_settings)
    return j


@pytest.mark.asyncio
async def test_first_run_uses_7_day_lookback(job):
    """When no last_run key exists, fallback to 7-day window."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    job.redis = mock_redis

    epoch = await job._get_last_run_epoch()
    # Should be ~7 days ago
    from datetime import datetime, UTC
    seven_days_ago = datetime.now(UTC).timestamp() - 7 * 86400
    assert abs(epoch - seven_days_ago) < 60  # within 1 minute


@pytest.mark.asyncio
async def test_failed_pairs_blocks_last_run_update(job):
    """When Neo4j writes fail, last_run must NOT be updated."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="1712000000.0")
    mock_redis.set = AsyncMock()
    job.redis = mock_redis

    # Mock: one FIRMS hit, one ACLED candidate within range
    firms_point = MagicMock()
    firms_point.payload = {
        "source": "firms",
        "latitude": 48.0,
        "longitude": 35.0,
        "acq_date": "2026-04-01",
        "url": "https://firms.example/1",
        "frp": 95.0,
        "brightness": 400.0,
        "confidence": "high",
        "possible_explosion": True,
    }
    acled_point = MagicMock()
    acled_point.payload = {
        "source": "acled",
        "latitude": 48.01,
        "longitude": 35.01,
        "event_date": "2026-04-01",
        "url": "https://acled.example/1",
        "event_type": "Battles",
    }

    # Scroll returns one FIRMS hit, then one ACLED candidate
    call_count = 0

    def mock_scroll(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ([firms_point], None)
        if call_count == 2:
            return ([acled_point], None)
        return ([], None)

    job.qdrant.scroll = mock_scroll

    # Neo4j write fails
    with patch("feeds.correlation_job.httpx.AsyncClient") as mock_http:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=Exception("Neo4j down")
        )
        mock_http.return_value = mock_client

        await job.run()

    # last_run must NOT have been updated
    mock_redis.set.assert_not_called()
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_correlation_job.py -v`
Expected: 5 old tests PASS, 9 new tests FAIL (missing functions)

- [ ] **Step 3: Implement full CorrelationJob**

Update `services/data-ingestion/feeds/correlation_job.py` — add the full batch job after the existing `correlation_score` function:

```python
import asyncio
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    Range,
)

from config import Settings
from feeds.geo import haversine_km

log = structlog.get_logger(__name__)

SCROLL_LIMIT = 200


def build_firms_filter(last_run_epoch: float) -> Filter:
    """Build Qdrant filter for new FIRMS explosion candidates."""
    return Filter(
        must=[
            FieldCondition(
                key="source", match=MatchValue(value="firms")
            ),
            FieldCondition(
                key="possible_explosion",
                match=MatchValue(value=True),
            ),
            FieldCondition(
                key="ingested_epoch",
                range=Range(gte=last_run_epoch),
            ),
        ]
    )


def build_acled_bbox_filter(
    firms_lat: float, firms_lon: float
) -> Filter:
    """Build Qdrant bbox filter for ACLED candidates near a FIRMS hit."""
    lat_delta = 0.5
    lon_delta = 0.5 / max(math.cos(math.radians(firms_lat)), 0.1)
    return Filter(
        must=[
            FieldCondition(
                key="source", match=MatchValue(value="acled")
            ),
            FieldCondition(
                key="latitude",
                range=Range(
                    gte=firms_lat - lat_delta,
                    lte=firms_lat + lat_delta,
                ),
            ),
            FieldCondition(
                key="longitude",
                range=Range(
                    gte=firms_lon - lon_delta,
                    lte=firms_lon + lon_delta,
                ),
            ),
        ]
    )


def passes_time_filter(
    firms_acq_date: str,
    acled_event_date: str,
    window_days: int,
) -> bool:
    """Check if two dates are within the correlation time window."""
    try:
        fd = date.fromisoformat(firms_acq_date)
        ad = date.fromisoformat(acled_event_date)
        return abs((fd - ad).days) <= window_days
    except (ValueError, TypeError):
        return False


class CorrelationJob:
    """Batch job correlating FIRMS thermal anomalies with ACLED events."""

    def __init__(
        self, settings: Settings, redis_client: Any | None = None
    ) -> None:
        self.settings = settings
        self.redis = redis_client
        self.qdrant = QdrantClient(url=settings.qdrant_url)

    async def _get_last_run_epoch(self) -> float:
        """Get last successful run timestamp from Redis."""
        if self.redis:
            val = await self.redis.get("correlation:last_run")
            if val:
                return float(val)
        # Fallback: 7 days ago
        return (datetime.now(UTC) - timedelta(days=7)).timestamp()

    async def _set_last_run(self) -> None:
        """Update last_run timestamp in Redis."""
        if self.redis:
            await self.redis.set(
                "correlation:last_run",
                str(datetime.now(UTC).timestamp()),
            )

    async def _scroll_all(self, scroll_filter: Filter) -> list[dict]:
        """Paginated scroll through all matching Qdrant points.

        Uses asyncio.to_thread to avoid blocking the event loop
        (qdrant-client is synchronous).
        """
        all_points: list[dict] = []
        offset = None
        while True:
            results, next_offset = await asyncio.to_thread(
                self.qdrant.scroll,
                collection_name=self.settings.qdrant_collection,
                scroll_filter=scroll_filter,
                limit=SCROLL_LIMIT,
                offset=offset,
            )
            if not results:
                break
            for point in results:
                all_points.append(point.payload)
            offset = next_offset
            if offset is None:
                break
        return all_points

    async def _write_corroboration(
        self,
        acled_url: str,
        firms_url: str,
        dist: float,
        days: int,
        score: float,
        acled_event_type: str,
        firms_frp: float,
        firms_brightness: float,
    ) -> bool:
        """Write CORROBORATED_BY relationship to Neo4j. Returns True on success."""
        statement = {
            "statements": [
                {
                    "statement": (
                        "MATCH (d1:Document {url: $acled_url}) "
                        "MATCH (d2:Document {url: $firms_url}) "
                        "MERGE (d1)-[r:CORROBORATED_BY]->(d2) "
                        "SET r.distance_km = $dist, "
                        "r.days_diff = $days, "
                        "r.confidence = $score, "
                        "r.correlation_time = $ts, "
                        "r.acled_event_type = $acled_type, "
                        "r.firms_frp = $frp, "
                        "r.firms_brightness = $brightness"
                    ),
                    "parameters": {
                        "acled_url": acled_url,
                        "firms_url": firms_url,
                        "dist": round(dist, 1),
                        "days": days,
                        "score": score,
                        "ts": datetime.now(UTC).isoformat(),
                        "acled_type": acled_event_type,
                        "frp": firms_frp,
                        "brightness": firms_brightness,
                    },
                }
            ]
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.settings.neo4j_url}/db/neo4j/tx/commit",
                    json=statement,
                    auth=(
                        self.settings.neo4j_user,
                        self.settings.neo4j_password,
                    ),
                )
                resp.raise_for_status()
                errors = resp.json().get("errors", [])
                if errors:
                    log.warning(
                        "correlation_neo4j_errors",
                        errors=errors,
                    )
                    return False
            return True
        except Exception as exc:
            log.error(
                "correlation_neo4j_failed",
                acled_url=acled_url,
                error=str(exc),
            )
            return False

    async def run(self) -> None:
        """Execute one correlation batch run."""
        log.info("correlation_job_started")
        start = time.monotonic()

        last_run_epoch = await self._get_last_run_epoch()
        log.info(
            "correlation_last_run",
            epoch=last_run_epoch,
        )

        # Step 1: Get new FIRMS explosion candidates
        firms_filter = build_firms_filter(last_run_epoch)
        firms_hits = await self._scroll_all(firms_filter)
        log.info("correlation_firms_hits", count=len(firms_hits))

        if not firms_hits:
            await self._set_last_run()
            log.info("correlation_job_finished_no_hits")
            return

        # Step 2: For each FIRMS hit, find nearby ACLED events
        total_correlations = 0
        failed_pairs: list[tuple[str, str]] = []

        for firms in firms_hits:
            firms_lat = firms.get("latitude")
            firms_lon = firms.get("longitude")
            firms_date = firms.get("acq_date", "")
            firms_url = firms.get("url", "")
            firms_frp = firms.get("frp", 0.0)
            firms_brightness = firms.get("brightness", 0.0)
            firms_conf = firms.get("confidence", "")

            if firms_lat is None or firms_lon is None:
                continue

            acled_filter = build_acled_bbox_filter(
                firms_lat, firms_lon
            )
            acled_candidates = await self._scroll_all(acled_filter)

            for acled in acled_candidates:
                acled_lat = acled.get("latitude")
                acled_lon = acled.get("longitude")
                acled_date = acled.get("event_date", "")
                acled_url = acled.get("url", "")
                acled_type = acled.get("event_type", "")

                if acled_lat is None or acled_lon is None:
                    continue

                # Haversine filter
                dist = haversine_km(
                    firms_lat, firms_lon, acled_lat, acled_lon
                )
                if dist > self.settings.correlation_radius_km:
                    continue

                # Time filter
                if not passes_time_filter(
                    firms_date,
                    acled_date,
                    self.settings.correlation_time_window_days,
                ):
                    continue

                # Score
                days_diff = abs(
                    (
                        date.fromisoformat(firms_date)
                        - date.fromisoformat(acled_date)
                    ).days
                )
                score = correlation_score(
                    distance_km=dist,
                    days_diff=days_diff,
                    possible_explosion=True,
                    acled_event_type=acled_type,
                    firms_confidence=firms_conf,
                )

                if score < self.settings.correlation_min_score:
                    continue

                # Write to Neo4j
                ok = await self._write_corroboration(
                    acled_url=acled_url,
                    firms_url=firms_url,
                    dist=dist,
                    days=days_diff,
                    score=score,
                    acled_event_type=acled_type,
                    firms_frp=firms_frp,
                    firms_brightness=firms_brightness,
                )
                if ok:
                    total_correlations += 1
                else:
                    failed_pairs.append((acled_url, firms_url))

        # Update last_run only if no failures
        if not failed_pairs:
            await self._set_last_run()
        else:
            log.warning(
                "correlation_partial_failure",
                failed_count=len(failed_pairs),
            )

        elapsed = round(time.monotonic() - start, 2)
        log.info(
            "correlation_job_finished",
            firms_scanned=len(firms_hits),
            correlations_written=total_correlations,
            failed=len(failed_pairs),
            elapsed_seconds=elapsed,
        )
```

- [ ] **Step 4: Run all correlation tests**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_correlation_job.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/ -q`
Expected: ~195+ passed

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/feeds/correlation_job.py services/data-ingestion/tests/test_correlation_job.py
git commit -m "feat(data-ingestion): add FIRMS-ACLED correlation batch job"
```

---

### Task 5: Scheduler registration

**Files:**
- Modify: `services/data-ingestion/scheduler.py`

- [ ] **Step 1: Add import**

Add after existing collector imports (around line 26):

```python
from feeds.correlation_job import CorrelationJob
```

- [ ] **Step 2: Add job wrapper function**

Add after the last `run_*` function (around line 180):

```python
async def run_correlation_job() -> None:
    """Correlate FIRMS thermal anomalies with ACLED conflict events."""
    job = CorrelationJob(
        settings=settings, redis_client=_get_redis_client()
    )
    try:
        await job.run()
    except Exception:
        log.exception("correlation_job_failed")
```

- [ ] **Step 3: Register job in create_scheduler()**

Add after the OFAC job registration (line 287), before `return scheduler`:

First, add the missing import at the top of `scheduler.py` (after `import sys`, around line 7):

```python
from datetime import UTC, datetime, timedelta
```

Then add after the OFAC job registration (line 287), before `return scheduler`:

```python
    # FIRMS-ACLED Correlation — 5 min offset from FIRMS
    correlation_start = datetime.now(UTC) + timedelta(minutes=5)
    scheduler.add_job(
        run_correlation_job,
        trigger=IntervalTrigger(
            hours=settings.correlation_interval_hours,
            start_date=correlation_start,
        ),
        id="firms_acled_correlation",
        name="FIRMS-ACLED Correlation",
        replace_existing=True,
    )
```

Do NOT add to `initial_tasks` — correlation needs existing data.

- [ ] **Step 4: Verify job count**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && python3 -c "from scheduler import create_scheduler; s = create_scheduler(); print(f'{len(s.get_jobs())} jobs registered')"`
Expected: `12 jobs registered`

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/scheduler.py
git commit -m "feat(data-ingestion): register FIRMS-ACLED correlation in scheduler"
```

---

### Task 6: Integration smoke test + lint

**Files:** None created — verification only

- [ ] **Step 1: Run full test suite**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run pytest tests/ -v --tb=short`
Expected: All tests PASS (~195+)

- [ ] **Step 2: Lint new and modified files**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run ruff check feeds/geo.py feeds/correlation_job.py feeds/base.py feeds/usgs_collector.py tests/test_geo.py tests/test_correlation_job.py`
Expected: All checks passed

- [ ] **Step 3: Fix any lint issues**

Run: `uv run ruff check feeds/geo.py feeds/correlation_job.py feeds/base.py feeds/usgs_collector.py tests/test_geo.py tests/test_correlation_job.py --fix`

- [ ] **Step 4: Verify all imports resolve**

Run: `cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && python3 -c "from feeds.correlation_job import CorrelationJob, correlation_score, build_firms_filter, build_acled_bbox_filter, passes_time_filter; from feeds.geo import haversine_km; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 5: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix(data-ingestion): lint fixes for correlation job"
```
