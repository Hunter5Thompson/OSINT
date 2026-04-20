"""Tests for NOAA NHC tropical weather collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.noaa_nhc_collector import NOAANHCCollector
from pipeline import ExtractionConfigError, ExtractionTransientError

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


# ── Extraction error skip tests (Task 7) ────────────────────────────


def _nhc_http_resp():
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = SAMPLE_RESPONSE
    return r


@pytest.mark.asyncio
async def test_nhc_transient_skips_upsert(collector):
    """When process_item raises ExtractionTransientError, storm is NOT upserted."""
    collector.http.get = AsyncMock(return_value=_nhc_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()

    with patch(
        "pipeline.process_item",
        new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_nhc_config_skips_upsert(collector):
    """When process_item raises ExtractionConfigError, storm is NOT upserted + error log."""
    collector.http.get = AsyncMock(return_value=_nhc_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()

    with (
        patch(
            "pipeline.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.noaa_nhc_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_not_called()
    assert any(
        c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list
    )
