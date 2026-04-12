"""Tests for HAPI humanitarian conflict collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.hapi_collector import HAPICollector, FOCUS_COUNTRIES

SAMPLE_RESPONSE = {
    "data": [
        {
            "location_code": "UKR",
            "reference_period_start": "2026-03-01",
            "event_type": "political_violence",
            "events": 245,
            "fatalities": 89,
        },
        {
            "location_code": "UKR",
            "reference_period_start": "2026-03-01",
            "event_type": "civilian_targeting",
            "events": 52,
            "fatalities": 31,
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
    s.hapi_app_identifier = "dGVzdEBlbWFpbC5jb20="  # base64("test@email.com")
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = HAPICollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestHAPIParser:
    def test_parse_records(self, collector):
        records = collector._parse_records(SAMPLE_RESPONSE, "UKR")
        assert len(records) == 2

        r1 = records[0]
        assert r1["location_code"] == "UKR"
        assert r1["reference_period"] == "2026-03"
        assert r1["event_type"] == "political_violence"
        assert r1["events_count"] == 245
        assert r1["fatalities"] == 89

    def test_parse_records_empty(self, collector):
        records = collector._parse_records({"data": []}, "UKR")
        assert records == []


class TestHAPIFocusCountries:
    def test_all_iso3(self):
        for code in FOCUS_COUNTRIES:
            assert len(code) == 3
            assert code.isalpha()
            assert code.isupper()

    def test_count(self):
        assert len(FOCUS_COUNTRIES) == 20


class TestHAPIContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._content_hash("UKR", "2026-03", "political_violence")
        h2 = collector._content_hash("UKR", "2026-03", "political_violence")
        assert h1 == h2

    def test_different_country_different_hash(self, collector):
        h1 = collector._content_hash("UKR", "2026-03", "political_violence")
        h2 = collector._content_hash("SYR", "2026-03", "political_violence")
        assert h1 != h2
