"""Tests for FIRMS cross-correlation job."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.correlation_job import (
    CorrelationJob,
    build_firms_filter,
    correlation_score,
    passes_time_filter,
)


def test_score_close_same_day_explosion():
    """5km, same day, possible_explosion, Explosions type, high confidence → ≥ 0.8."""
    score = correlation_score(
        distance_km=5.0,
        days_diff=0,
        conflict_codebook_type="military.airstrike",
        firms_confidence="high",
    )
    assert score >= 0.8


def test_score_far_next_day():
    """45km, next day, no explosion, Battles type, nominal confidence → < 0.5."""
    score = correlation_score(
        distance_km=45.0,
        days_diff=1,
        conflict_codebook_type="other.unclassified",
        firms_confidence="nominal",
    )
    assert score < 0.5


def test_score_boundary_50km():
    """Exactly 50km → dist_score = 0.0, base = 0.0."""
    score = correlation_score(
        distance_km=50.0,
        days_diff=0,
        conflict_codebook_type="other.unclassified",
        firms_confidence="nominal",
    )
    assert score == 0.0


def test_score_capped_at_1():
    """Maximum bonuses should not exceed 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        conflict_codebook_type="military.airstrike",
        firms_confidence="high",
    )
    assert score == 1.0


def test_score_zero_km_same_day_no_bonus():
    """0km, same day, no bonuses → base = 1.0."""
    score = correlation_score(
        distance_km=0.0,
        days_diff=0,
        conflict_codebook_type="other.unclassified",
        firms_confidence="nominal",
    )
    assert score == 1.0


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


def test_new_thermal_observations_do_not_require_explosion_label():
    assert all(c.key != "possible_explosion" for c in build_firms_filter(0).must)


@pytest.mark.asyncio
async def test_current_gdelt_event_is_joined_by_id_without_gkg_coordinates(job):
    firms = MagicMock(
        payload={
            "latitude": 48.0,
            "longitude": 35.0,
            "acq_date": "2026-04-01",
            "url": "https://firms.example/1",
            "confidence": "nominal",
        }
    )
    job._scroll_all = AsyncMock(side_effect=[[firms], []])
    job._get_last_run_epoch = AsyncMock(return_value=0)
    job._set_last_run = AsyncMock()
    job._event_candidates = AsyncMock(
        return_value=[
            {
                "event_id": "gdelt:event:1",
                "latitude": 48.01,
                "longitude": 35.01,
                "event_date": "2026-04-01",
                "time_basis": "indexed",
                "codebook_type": "military.airstrike",
            }
        ]
    )
    job._write_proximity = AsyncMock(return_value=1)
    await job.run()
    job._event_candidates.assert_awaited_once()
    job._write_proximity.assert_awaited_once()
    assert job._write_proximity.await_args.kwargs["event_id"] == "gdelt:event:1"
    assert job._scroll_all.await_count == 1


@pytest.mark.asyncio
async def test_proximity_write_rejects_a_zero_edge_acknowledgement(job):
    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {
        "errors": [],
        "results": [
            {"columns": ["written"], "data": [{"row": [0]}]},
        ],
    }
    client.post.return_value = response
    with pytest.raises(RuntimeError, match="not linked"):
        await job._write_proximity(
            client,
            firms_url="f",
            event_id="e",
            score=0.5,
            distance_km=1.0,
            days_diff=0,
            time_basis="indexed",
        )


@pytest.mark.asyncio
async def test_candidates_require_current_admitted_derivations(job):
    from config import Settings

    settings = Settings()
    job.settings.spatial_catalog_path = settings.spatial_catalog_path
    job.settings.spatial_country_crosswalk_path = settings.spatial_country_crosswalk_path
    job._graph_rows = AsyncMock(return_value=[])
    await job._event_candidates(
        None, {"acq_date": "2026-04-01", "latitude": 48.0, "longitude": 35.0}
    )
    _, statement, parameters = job._graph_rows.await_args.args
    assert "l.spatial_derivation_revision IN $derivations" in statement
    assert parameters["derivations"]
