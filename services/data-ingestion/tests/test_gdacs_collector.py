"""Tests for GDACS disaster alert collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.gdacs_collector import GDACSCollector

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


class TestGDACSContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._content_hash("gdacs", "EQ", "1001")
        h2 = collector._content_hash("gdacs", "EQ", "1001")
        assert h1 == h2

    def test_different_type_different_hash(self, collector):
        h1 = collector._content_hash("gdacs", "EQ", "1001")
        h2 = collector._content_hash("gdacs", "TC", "1001")
        assert h1 != h2
