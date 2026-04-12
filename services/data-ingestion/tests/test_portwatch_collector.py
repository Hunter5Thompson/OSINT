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
