"""Tests for NOAA NHC tropical weather collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.noaa_nhc_collector import NOAANHCCollector

SAMPLE_RESPONSE = {
    "activeStorms": [
        {
            "id": "al042026",
            "name": "Delta",
            "classification": "HU",
            "intensity": 85,
            "pressure": 972,
            "lat": 25.4,
            "lon": -88.2,
            "movement": {"text": "NW at 12 kt"},
            "lastUpdate": "2026-04-12T15:00:00Z",
            "advisoryNumber": "14",
        },
    ]
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
        c = NOAANHCCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestNOAAParser:
    def test_parse_storms(self, collector):
        storms = collector._parse_storms(SAMPLE_RESPONSE)
        assert len(storms) == 1

        s = storms[0]
        assert s["storm_id"] == "al042026"
        assert s["storm_name"] == "Delta"
        assert s["classification"] == "Hurricane"
        assert s["wind_speed_kt"] == 85
        assert s["pressure_mb"] == 972
        assert s["latitude"] == 25.4
        assert s["longitude"] == -88.2
        assert s["advisory_number"] == "14"

    def test_parse_storms_empty(self, collector):
        storms = collector._parse_storms({"activeStorms": []})
        assert storms == []

    def test_classification_mapping(self, collector):
        for code, label in [("TD", "Tropical Depression"), ("TS", "Tropical Storm"), ("HU", "Hurricane")]:
            data = {"activeStorms": [{"id": "t1", "name": "T", "classification": code, "intensity": 50, "pressure": 1000, "lat": 20, "lon": -80, "movement": {"text": "N"}, "lastUpdate": "", "advisoryNumber": "1"}]}
            storms = collector._parse_storms(data)
            assert storms[0]["classification"] == label


class TestNOAAContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._content_hash("al042026", "14")
        h2 = collector._content_hash("al042026", "14")
        assert h1 == h2

    def test_different_advisory_different_hash(self, collector):
        h1 = collector._content_hash("al042026", "14")
        h2 = collector._content_hash("al042026", "15")
        assert h1 != h2
