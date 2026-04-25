"""Tests for IMF PortWatch chokepoint collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.portwatch_collector import CHOKEPOINT_COORDS, PortWatchCollector
from pipeline import ExtractionConfigError, ExtractionTransientError

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
        for _name, coords in CHOKEPOINT_COORDS.items():
            assert isinstance(coords, tuple)
            assert len(coords) == 2
            lat, lon = coords
            assert -90 <= lat <= 90
            assert -180 <= lon <= 180


# ── Extraction error skip tests (Task 7) ────────────────────────────
# Covers BOTH call sites: _CHOKEPOINTS_URL (line 124) and _DISRUPTIONS_URL (line 170)


@pytest.mark.asyncio
async def test_portwatch_transient_skips_both_upserts(collector):
    """Transient error in either call site → no Qdrant upsert for that record."""
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()
    # Return chokepoint records first, disruption records second
    collector._fetch_paginated = AsyncMock(
        side_effect=[SAMPLE_CHOKEPOINT_RESPONSE, SAMPLE_DISRUPTION_RESPONSE]
    )

    with patch(
        "pipeline.process_item",
        new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
    ):
        await collector.collect()

    # Neither call site upserted anything
    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_portwatch_config_skips_both_upserts(collector):
    """Config error in either call site → no Qdrant upsert + error log."""
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()
    collector._fetch_paginated = AsyncMock(
        side_effect=[SAMPLE_CHOKEPOINT_RESPONSE, SAMPLE_DISRUPTION_RESPONSE]
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
    # Error log emitted for both call sites (chokepoint + disruption)
    err_keys = [c.args[0] for c in mock_err.call_args_list]
    assert err_keys.count("extraction_skipped_config") >= 2
