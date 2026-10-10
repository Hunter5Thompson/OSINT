"""Tests for NASA FIRMS thermal anomaly collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import feeds.firms_collector as firms_module
from feeds.firms_collector import (
    FIRMS_BBOXES,
    FIRMS_SATELLITES,
    FIRMSCollector,
    _firms_observed_at,
)
from graph_integrity.spatial_normalizer import load_normalization_index
from pipeline import ExtractionConfigError, ExtractionTransientError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        REPOSITORY_ROOT / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799",
        crosswalk_path=(
            REPOSITORY_ROOT / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
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


@pytest.mark.parametrize("time_value", ["930", "0930", 930])
def test_acquisition_time_variants_have_one_hash(collector, time_value):
    assert collector._firms_content_hash(
        36.5, 40.7, "2026-04-01", time_value
    ) == collector._firms_content_hash(36.5, 40.7, "2026-04-01", "0930")
    assert _firms_observed_at("2026-04-01", time_value) == "2026-04-01T09:30:00+00:00"


@pytest.mark.parametrize(
    "time_value", [None, "", True, 930.0, -1, "2400", "2360", "12:30", "00000", "930.0"]
)
def test_invalid_hhmm_has_no_canonical_identity(collector, time_value):
    assert _firms_observed_at("2026-04-01", time_value) is None
    with pytest.raises(ValueError):
        collector._firms_content_hash(36.5, 40.7, "2026-04-01", time_value)


@pytest.mark.parametrize("date_value", ["", "2026-02-30", "20260401", "2026-4-1"])
def test_invalid_acquisition_date_has_no_identity(collector, date_value):
    assert _firms_observed_at(date_value, "0930") is None
    with pytest.raises(ValueError):
        collector._firms_content_hash(36.5, 40.7, date_value, "0930")


def test_canonical_standard_hash_stays_legacy_compatible_and_distinct_times_differ(collector):
    legacy = collector._content_hash("36.5000|40.7000|2026-04-01|0930")
    assert collector._firms_content_hash(36.5, 40.7, "2026-04-01", "0930") == legacy
    assert collector._firms_content_hash(
        36.5, 40.7, "2026-04-01", "0930"
    ) != collector._firms_content_hash(36.5, 40.7, "2026-04-01", "0931")


@pytest.mark.asyncio
async def test_collect_recognizes_old_unpadded_identity_before_new_processing(
    collector, monkeypatch
):
    collector._ensure_collection = AsyncMock()
    monkeypatch.setattr(firms_module, "FIRMS_BBOXES", {"fixture": "1,2,3,4"})
    monkeypatch.setattr(firms_module, "FIRMS_SATELLITES", ["fixture"])
    text = "\n".join(SAMPLE_CSV.splitlines()[:2]).replace(",0130,", ",0930,")
    collector._fetch_csv = AsyncMock(return_value=text)
    old_id = collector._point_id(collector._content_hash("36.5000|40.7000|2026-04-01|930"))

    def existing(point_id, legacy_ids=()):
        return old_id in (point_id, *legacy_ids)

    collector._dedup_check = AsyncMock(side_effect=existing)
    process = AsyncMock()
    monkeypatch.setattr(firms_module, "process_item", process)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    await collector.collect()
    process.assert_not_awaited()
    collector._build_point.assert_not_awaited()


@pytest.mark.asyncio
async def test_format_variants_in_one_batch_are_processed_once(collector, monkeypatch):
    collector._ensure_collection = AsyncMock()
    monkeypatch.setattr(firms_module, "FIRMS_BBOXES", {"fixture": "1,2,3,4"})
    monkeypatch.setattr(firms_module, "FIRMS_SATELLITES", ["fixture"])
    header, row = SAMPLE_CSV.splitlines()[:2]
    text = "\n".join([header, row.replace(",0130,", ",930,"), row.replace(",0130,", ",0930,")])
    collector._fetch_csv = AsyncMock(return_value=text)
    collector._dedup_check = AsyncMock(return_value=False)
    process = AsyncMock()
    monkeypatch.setattr(firms_module, "process_item", process)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    await collector.collect()
    process.assert_awaited_once()
    assert len(collector._batch_upsert.call_args.args[0]) == 1
    evidence = process.call_args.kwargs["source_evidence"]
    assert evidence["acq_time"] == "930"  # original evidence remains original
    assert evidence["identity_schema"] == "firms-location-hhmm-v2"


def test_bad_acquisition_time_does_not_lose_valid_csv_neighbors(collector):
    header, row = SAMPLE_CSV.splitlines()[:2]
    rows = collector._parse_csv(
        "\n".join([header, row, row.replace(",0130,", ",2360,"), row]), "fixture"
    )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_legacy_dedup_uses_one_bounded_lookup(collector, monkeypatch):
    lookup = AsyncMock(return_value=[object()])
    monkeypatch.setattr(firms_module.asyncio, "to_thread", lookup)
    assert await collector._dedup_check(1, (2, 3, 2)) is True
    lookup.assert_awaited_once()
    assert lookup.call_args.kwargs["ids"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_invalid_dedup_result_is_not_a_cache_miss(collector, monkeypatch):
    monkeypatch.setattr(firms_module.asyncio, "to_thread", AsyncMock(return_value=None))
    with pytest.raises((TypeError, ValueError)):
        await collector._dedup_check(1, (2,))


@pytest.mark.asyncio
async def test_database_dedup_error_is_not_a_cache_miss(collector, monkeypatch):
    monkeypatch.setattr(firms_module.asyncio, "to_thread", AsyncMock(side_effect=ConnectionError))
    with pytest.raises(ConnectionError):
        await collector._dedup_check(1, (2,))


def test_legacy_identity_candidates_are_bounded_and_canonical_first(collector):
    hashes = collector._identity_hashes(36.5, 40.7, "2026-04-01", 5)
    assert hashes[0] == collector._firms_content_hash(36.5, 40.7, "2026-04-01", "0005")
    assert len(hashes) == 4
    assert collector._content_hash("36.5000|40.7000|2026-04-01|05") in hashes


# ── Extraction error skip tests (Task 7) ────────────────────────────


@pytest.mark.asyncio
async def test_new_firms_point_retains_validated_observation_time(collector, monkeypatch):
    collector._ensure_collection = AsyncMock()
    monkeypatch.setattr(firms_module, "FIRMS_BBOXES", {"fixture": "1,2,3,4"})
    monkeypatch.setattr(firms_module, "FIRMS_SATELLITES", ["fixture"])
    header, row = SAMPLE_CSV.splitlines()[:2]
    collector._fetch_csv = AsyncMock(return_value="\n".join([header, row]))
    collector._dedup_check = AsyncMock(return_value=False)
    process = AsyncMock()
    monkeypatch.setattr(firms_module, "process_item", process)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    await collector.collect()
    point_row = collector._build_point.call_args.args[1]
    observed = process.call_args.kwargs["observed_at"]
    assert point_row.get("observed_at") == observed == "2026-04-01T01:30:00+00:00"
    assert point_row["acq_time"] == "0130"
    assert point_row.get("published_at") is None


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
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)


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
    assert process.call_args_list[0].kwargs["url"].endswith("@39.7000,47.2000,10z")


@pytest.mark.asyncio
async def test_firms_collector_map_url_uses_lon_lat_contract(collector):
    csv_text = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
        "confidence,version,bright_ti5,frp,daynight\n"
        "48.1000,37.8000,340.0,0.39,0.36,2026-04-01,0130,N,high,2.0NRT,290.0,10.0,N\n"
    )
    collector._fetch_csv = AsyncMock(return_value=csv_text)
    collector._dedup_check = AsyncMock(return_value=False)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._ensure_collection = AsyncMock()
    process = AsyncMock()

    with (
        patch("feeds.firms_collector.FIRMS_SATELLITES", ["VIIRS_SNPP_NRT"]),
        patch("feeds.firms_collector.FIRMS_BBOXES", {"test": "0,0,1,1"}),
        patch("feeds.firms_collector.process_item", new=process),
    ):
        await collector.collect()

    assert process.call_args.kwargs["url"].endswith("@37.8000,48.1000,10z")
