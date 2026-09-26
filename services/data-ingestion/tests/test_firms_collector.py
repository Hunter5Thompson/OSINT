"""Tests for NASA FIRMS thermal anomaly collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.firms_collector import (
    FIRMS_BBOXES,
    FIRMS_SATELLITES,
    FIRMSCollector,
)
from graph_integrity.spatial_normalizer import load_normalization_index
from pipeline import ExtractionConfigError, ExtractionTransientError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        REPOSITORY_ROOT
        / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799",
        crosswalk_path=(
            REPOSITORY_ROOT
            / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
        ),
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
    s.neo4j_url = "bolt://localhost:7687"
    s.neo4j_http_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings, spatial_index):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = FIRMSCollector(settings=mock_settings, spatial_index=spatial_index)
    c.qdrant.retrieve.return_value = []
    return c


SAMPLE_CSV = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight\n"
    "36.5000,40.7000,400.5,0.39,0.36,2026-04-01,0130,N,high,2.0NRT,290.1,95.2,N\n"
    "36.5001,40.7001,350.0,0.39,0.36,2026-04-01,0130,N,nominal,2.0NRT,280.0,50.0,D\n"
)


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
    assert rows[0]["fetch_area"] == "ukraine"
    assert "bbox_name" not in rows[0]
    # VIIRS I4 saturates at ~367 K, so a >380 K test can never fire: no flag at all.
    assert all("possible_explosion" not in row for row in rows)


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


@pytest.mark.asyncio
async def test_firms_title_names_resolved_country_not_fetch_box(collector):
    """Rostov lies in the "ukraine" fetch box; the model must read RUS."""
    csv_text = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
        "confidence,version,bright_ti5,frp,daynight\n"
        "47.2000,39.7000,367.0,0.39,0.36,2026-04-01,0130,N,high,2.0NRT,300.0,120.0,N\n"
        "33.3000,44.4000,340.0,0.39,0.36,2026-04-01,0131,N,nominal,2.0NRT,290.0,10.0,N\n"
    )
    collector._fetch_csv = AsyncMock(return_value=csv_text)
    collector._dedup_check = AsyncMock(return_value=False)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._ensure_collection = AsyncMock()
    process = AsyncMock()

    with (
        patch("feeds.firms_collector.FIRMS_SATELLITES", ["VIIRS_SNPP_NRT"]),
        patch("feeds.firms_collector.FIRMS_BBOXES", {"ukraine": "22,44,40,52"}),
        patch("feeds.firms_collector.process_item", new=process),
    ):
        await collector.collect()

    titles = [c.kwargs["title"] for c in process.call_args_list]
    assert titles == [
        "FIRMS thermal anomaly at 47.2000,39.7000 (RUS)",
        "FIRMS thermal anomaly at 33.3000,44.4000 (country unresolved)",
    ]
    rows = [c.args[1] for c in collector._build_point.call_args_list]
    assert [r["country_iso3"] for r in rows] == ["RUS", None]
