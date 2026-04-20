"""Tests for GDACS disaster alert collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.gdacs_collector import GDACSCollector
from pipeline import ExtractionConfigError, ExtractionTransientError

SAMPLE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [95.0, 3.5]},
            "properties": {
                "eventtype": "EQ",
                "eventid": "1001",
                "eventname": "Earthquake Indonesia",
                "alertlevel": "Red",
                "severity": {"value": 6.8},
                "country": "Indonesia",
                "fromdate": "2026-04-10",
                "todate": "2026-04-10",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-80.0, 25.0]},
            "properties": {
                "eventtype": "TC",
                "eventid": "2002",
                "eventname": "Tropical Cyclone Alpha",
                "alertlevel": "Orange",
                "severity": {"value": 4.2},
                "country": "United States",
                "fromdate": "2026-04-08",
                "todate": "2026-04-12",
            },
        },
    ],
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
        c = GDACSCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestGDACSParser:
    def test_parse_features_extracts_all_fields(self, collector):
        events = collector._parse_features(SAMPLE_GEOJSON)
        assert len(events) == 2

        e1 = events[0]
        assert e1["gdacs_id"] == "EQ_1001"
        assert e1["event_type"] == "EQ"
        assert e1["event_name"] == "Earthquake Indonesia"
        assert e1["alert_level"] == "Red"
        assert e1["severity"] == 6.8
        assert e1["country"] == "Indonesia"
        assert e1["latitude"] == 3.5
        assert e1["longitude"] == 95.0

    def test_parse_features_tropical_cyclone(self, collector):
        events = collector._parse_features(SAMPLE_GEOJSON)
        e2 = events[1]
        assert e2["event_type"] == "TC"
        assert e2["alert_level"] == "Orange"

    def test_parse_features_empty_input(self, collector):
        events = collector._parse_features({"type": "FeatureCollection", "features": []})
        assert events == []


    def test_parse_features_null_severity(self, collector):
        """GDACS sometimes returns null severity — should not crash the entire cycle."""
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
                    "properties": {
                        "eventtype": "FL",
                        "eventid": "3003",
                        "eventname": "Flood Test",
                        "alertlevel": "Green",
                        "severity": {"value": None},
                        "country": "Test",
                        "fromdate": "2026-04-10",
                        "todate": "2026-04-10",
                    },
                },
            ],
        }
        events = collector._parse_features(data)
        assert len(events) == 1
        assert events[0]["severity"] == 0.0

    def test_parse_features_non_dict_severity(self, collector):
        """GDACS severity might be a bare number or string — handle gracefully."""
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
                    "properties": {
                        "eventtype": "EQ",
                        "eventid": "4004",
                        "eventname": "Quake",
                        "alertlevel": "Orange",
                        "severity": "invalid",
                        "country": "Test",
                        "fromdate": "2026-04-10",
                        "todate": "2026-04-10",
                    },
                },
            ],
        }
        events = collector._parse_features(data)
        assert len(events) == 1
        assert events[0]["severity"] == 0.0


class TestGDACSContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._content_hash("gdacs", "EQ", "1001")
        h2 = collector._content_hash("gdacs", "EQ", "1001")
        assert h1 == h2

    def test_different_type_different_hash(self, collector):
        h1 = collector._content_hash("gdacs", "EQ", "1001")
        h2 = collector._content_hash("gdacs", "TC", "1001")
        assert h1 != h2


# ── Extraction error skip tests (Task 7) ────────────────────────────


def _gdacs_http_resp():
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = SAMPLE_GEOJSON
    return r


@pytest.mark.asyncio
async def test_gdacs_transient_skips_upsert(collector):
    """When process_item raises ExtractionTransientError, event is NOT upserted."""
    collector.http.get = AsyncMock(return_value=_gdacs_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._embed = AsyncMock(return_value=[0.0] * 1024)
    collector.qdrant.retrieve.return_value = []

    with patch(
        "pipeline.process_item",
        new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
    ):
        await collector.collect()

    collector._batch_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_gdacs_config_skips_upsert(collector):
    """When process_item raises ExtractionConfigError, event is NOT upserted + error log."""
    collector.http.get = AsyncMock(return_value=_gdacs_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._embed = AsyncMock(return_value=[0.0] * 1024)
    collector.qdrant.retrieve.return_value = []

    with (
        patch(
            "pipeline.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.gdacs_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._batch_upsert.assert_not_called()
    assert any(
        c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list
    )
