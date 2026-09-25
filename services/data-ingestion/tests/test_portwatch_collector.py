"""Tests for IMF PortWatch chokepoint collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.portwatch_collector import CHOKEPOINT_COORDS, PortWatchCollector
from pipeline import ExtractionConfigError, ExtractionTransientError

# Real ArcGIS schema (Daily_Chokepoints_Data, checked 2026-09-25).
SAMPLE_CHOKEPOINT_RESPONSE = {
    "features": [
        {
            "attributes": {
                "date": "2026-09-20", "portid": "chokepoint6", "portname": "Strait of Hormuz",
                "n_total": 42, "n_tanker": 19, "n_container": 14, "n_cargo": 23,
                "capacity": 1_713_133,
            },
        },
        {
            "attributes": {
                "date": "2026-09-20", "portid": "chokepoint4",
                "portname": "Bab el-Mandeb Strait",
                "n_total": 35, "n_tanker": 10, "n_container": 8, "n_cargo": 17,
                "capacity": 865_617,
            },
        },
    ],
    "exceededTransferLimit": False,
}

# Real ArcGIS schema (portwatch_disruptions_database, checked 2026-09-25).
SAMPLE_DISRUPTION_RESPONSE = {
    "features": [
        {
            "attributes": {
                "eventid": 1000552, "eventtype": "TC", "eventname": "IDAI-19",
                "htmldescription": "Red Tropical Cyclone IDAI-19 in Mozambique",
                "alertlevel": "RED", "country": "Mozambique",
                "fromdate": 1552111200000, "todate": 1552608000000,
                "lat": -19.6, "long": 34.8, "affectedports": "port137",
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
        assert r1["record_type"] == "daily_flow"
        assert r1["portid"] == "chokepoint6"
        assert r1["chokepoint"] == "Strait of Hormuz"
        assert r1["date"] == "2026-09-20"
        assert r1["vessel_count"] == 42
        assert r1["tanker_count"] == 19
        assert r1["capacity"] == 1_713_133

    def test_parse_disruption_data(self, collector):
        records = collector._parse_disruption_data(SAMPLE_DISRUPTION_RESPONSE)
        assert len(records) == 1

        r = records[0]
        assert r["record_type"] == "disruption"
        assert r["disruption_id"] == "1000552"
        assert r["name"] == "IDAI-19"
        assert r["description"] == "Red Tropical Cyclone IDAI-19 in Mozambique"
        assert r["country"] == "Mozambique"
        assert r["start_date"] == "2019-03-09"
        assert r["end_date"] == "2019-03-15"
        assert (r["latitude"], r["longitude"]) == (-19.6, 34.8)

    def test_parse_disruption_without_end_or_coords(self, collector):
        data = {"features": [{"attributes": {"eventid": 7, "fromdate": None, "todate": None}}]}
        r = collector._parse_disruption_data(data)[0]
        assert r["start_date"] is None and r["end_date"] is None
        assert "latitude" not in r and "longitude" not in r

    def test_parse_empty(self, collector):
        assert collector._parse_chokepoint_data({"features": []}) == []
        assert collector._parse_disruption_data({"features": []}) == []


class TestChokepoints:
    def test_all_chokepoints_have_coords(self):
        for portid, coords in CHOKEPOINT_COORDS.items():
            assert portid.startswith("chokepoint")
            lat, lon = coords
            assert -90 <= lat <= 90
            assert -180 <= lon <= 180


def _flow_only(collector):
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock(side_effect=lambda text, payload, chash: payload)
    collector._fetch_paginated = AsyncMock(
        side_effect=[SAMPLE_CHOKEPOINT_RESPONSE, {"features": []}]
    )


@pytest.mark.asyncio
async def test_daily_flows_never_go_through_llm_extraction(collector):
    # Numeric flow rows carry nothing to extract; 79k rows through the LLM was the
    # Spark cold-start burst.
    _flow_only(collector)
    with patch("pipeline.process_item", new=AsyncMock()) as mock_process:
        await collector.collect()

    mock_process.assert_not_called()
    upserted = collector._batch_upsert.await_args_list[0].args[0]
    assert [p["chokepoint"] for p in upserted] == ["Strait of Hormuz", "Bab el-Mandeb Strait"]


@pytest.mark.asyncio
async def test_flow_coords_by_portid_and_unknown_gets_no_null_island(collector):
    _flow_only(collector)
    collector._fetch_paginated = AsyncMock(side_effect=[
        {"features": [
            SAMPLE_CHOKEPOINT_RESPONSE["features"][0],
            {"attributes": {"date": "2026-09-20", "portid": "chokepoint99",
                            "portname": "Unknown Strait", "n_total": 1}},
        ]},
        {"features": []},
    ])
    await collector.collect()

    hormuz, unknown = collector._batch_upsert.await_args_list[0].args[0]
    assert (hormuz["latitude"], hormuz["longitude"]) == CHOKEPOINT_COORDS["chokepoint6"]
    assert "latitude" not in unknown and "longitude" not in unknown


@pytest.mark.asyncio
async def test_flows_are_fetched_incrementally_not_full_history(collector):
    _flow_only(collector)
    await collector.collect()

    flow_call = collector._fetch_paginated.await_args_list[0]
    where = flow_call.kwargs["where"]
    assert where.startswith("date >= '") and where.endswith("'")


@pytest.mark.asyncio
async def test_flow_dedup_key_distinguishes_chokepoints_on_same_day(collector):
    _flow_only(collector)
    await collector.collect()
    ids = [c.args[0] for c in collector._dedup_check.await_args_list]
    assert len(set(ids)) == 2


# ── Extraction error skip tests (Task 7) ────────────────────────────
# Only disruptions (narrative text) go through extraction; flows never do.


@pytest.mark.asyncio
async def test_portwatch_transient_skips_disruption_upsert(collector):
    """Transient extraction error → the disruption is not upserted (retried later)."""
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()
    collector._fetch_paginated = AsyncMock(
        side_effect=[{"features": []}, SAMPLE_DISRUPTION_RESPONSE]
    )

    with patch(
        "pipeline.process_item",
        new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_portwatch_config_skips_disruption_upsert(collector):
    """Config extraction error → no disruption upsert + error log."""
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()
    collector._fetch_paginated = AsyncMock(
        side_effect=[{"features": []}, SAMPLE_DISRUPTION_RESPONSE]
    )

    with (
        patch(
            "pipeline.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.portwatch_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_not_called()
    err_keys = [c.args[0] for c in mock_err.call_args_list]
    assert err_keys.count("extraction_skipped_config") == 1
