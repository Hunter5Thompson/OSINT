"""Tests for NASA FIRMS thermal anomaly collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.firms_collector import (
    FIRMS_BBOXES,
    FIRMS_SATELLITES,
    FIRMSCollector,
    is_possible_explosion,
)
from pipeline import ExtractionConfigError, ExtractionTransientError


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


# ── Extraction error skip tests (Task 7) ────────────────────────────


@pytest.mark.asyncio
async def test_firms_transient_skips_upsert(collector):
    """When process_item raises ExtractionTransientError, row is NOT upserted."""
    collector._fetch_csv = AsyncMock(return_value=SAMPLE_CSV)
    collector._dedup_check = AsyncMock(return_value=False)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._ensure_collection = AsyncMock()

    # Force only ONE satellite/bbox iteration for a fast test
    with (
        patch("feeds.firms_collector.FIRMS_SATELLITES", ["VIIRS_SNPP_NRT"]),
        patch("feeds.firms_collector.FIRMS_BBOXES", {"ukraine": "22,44,40,52"}),
        patch(
            "feeds.firms_collector.process_item",
            new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
        ),
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_called_once_with([])


@pytest.mark.asyncio
async def test_firms_config_skips_upsert(collector):
    """When process_item raises ExtractionConfigError, row is NOT upserted + error log."""
    collector._fetch_csv = AsyncMock(return_value=SAMPLE_CSV)
    collector._dedup_check = AsyncMock(return_value=False)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._ensure_collection = AsyncMock()

    with (
        patch("feeds.firms_collector.FIRMS_SATELLITES", ["VIIRS_SNPP_NRT"]),
        patch("feeds.firms_collector.FIRMS_BBOXES", {"ukraine": "22,44,40,52"}),
        patch(
            "feeds.firms_collector.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.firms_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_called_once_with([])
    assert any(
        c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list
    )
