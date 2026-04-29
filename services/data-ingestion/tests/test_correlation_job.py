"""Tests for FIRMS cross-correlation job."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.correlation_job import (
    CorrelationJob,
    build_conflict_bbox_filter,
    build_firms_filter,
    correlation_score,
    passes_time_filter,
)


def test_score_close_same_day_explosion():
    """5km, same day, possible_explosion, Explosions type, high confidence → ≥ 0.8."""
    score = correlation_score(
        distance_km=5.0,
        days_diff=0,
        possible_explosion=True,
        conflict_codebook_type="military.airstrike",
        firms_confidence="high",
    )
    assert score >= 0.8


def test_score_far_next_day():
    """45km, next day, no explosion, Battles type, nominal confidence → < 0.5."""
    score = correlation_score(
        distance_km=45.0,
        days_diff=1,
        possible_explosion=False,
        conflict_codebook_type="other.unclassified",
        firms_confidence="nominal",
    )
    assert score < 0.5


def test_score_boundary_50km():
    """Exactly 50km → dist_score = 0.0, base = 0.0."""
    score = correlation_score(
        distance_km=50.0,
        days_diff=0,
        possible_explosion=False,
        conflict_codebook_type="other.unclassified",
        firms_confidence="nominal",
    )
    assert score == 0.0


def test_score_capped_at_1():
    """Maximum bonuses should not exceed 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        possible_explosion=True,
        conflict_codebook_type="military.airstrike",
        firms_confidence="high",
    )
    assert score == 1.0


def test_score_zero_km_same_day_no_bonus():
    """0km, same day, no bonuses → base = 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        possible_explosion=False,
        conflict_codebook_type="other.unclassified",
        firms_confidence="nominal",
    )
    assert score == 1.0


def test_bbox_filter_equator():
    """At equator, lon_delta ≈ 0.5."""
    f = build_conflict_bbox_filter(0.0, 30.0)
    must = f.must
    lat_cond = next(c for c in must if c.key == "latitude")
    lon_cond = next(c for c in must if c.key == "longitude")
    assert lat_cond.range.gte == pytest.approx(-0.5)
    assert lat_cond.range.lte == pytest.approx(0.5)
    assert lon_cond.range.gte == pytest.approx(29.5, abs=0.05)
    assert lon_cond.range.lte == pytest.approx(30.5, abs=0.05)


def test_bbox_filter_high_latitude():
    """At 60°N, lon_delta should be wider (~1.0°)."""
    f = build_conflict_bbox_filter(60.0, 30.0)
    must = f.must
    lon_cond = next(c for c in must if c.key == "longitude")
    lon_width = lon_cond.range.lte - lon_cond.range.gte
    assert lon_width > 1.5


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
    s.neo4j_url = "bolt://localhost:7687"
    s.neo4j_http_url = "http://localhost:7474"
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
    from datetime import UTC, datetime
    seven_days_ago = datetime.now(UTC).timestamp() - 7 * 86400
    assert abs(epoch - seven_days_ago) < 60


@pytest.mark.asyncio
async def test_failed_pairs_blocks_last_run_update(job):
    """When Neo4j writes fail, last_run must NOT be updated."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="1712000000.0")
    mock_redis.set = AsyncMock()
    job.redis = mock_redis

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
    conflict_point = MagicMock()
    conflict_point.payload = {
        "source": "gdelt",
        "latitude": 48.01,
        "longitude": 35.01,
        "seen_date": "2026-04-01T12:00:00",
        "url": "https://gdelt.example/1",
        "codebook_type": "military.airstrike",
    }

    call_count = 0
    def mock_scroll(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ([firms_point], None)
        if call_count == 2:
            return ([conflict_point], None)
        return ([], None)

    job.qdrant.scroll = mock_scroll

    with patch("feeds.correlation_job.httpx.AsyncClient") as mock_http:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Neo4j down"))
        mock_http.return_value = mock_client

        await job.run()

    mock_redis.set.assert_not_called()
