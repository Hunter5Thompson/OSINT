"""Tests for NOAA NHC tropical weather collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.noaa_nhc_collector import NOAANHCCollector
from pipeline import ExtractionConfigError, ExtractionTransientError

# Shape of the live NHC feed (https://www.nhc.noaa.gov/CurrentStorms.json,
# captured 2026-09-26): numbers as strings, numeric coords in *Numeric fields,
# advisory number under publicAdvisory, movement as degrees + knots.
SAMPLE_RESPONSE = {
    "activeStorms": [
        {
            "id": "al042026",
            "binNumber": "AT4",
            "name": "Delta",
            "classification": "HU",
            "intensity": "85",
            "pressure": "972",
            "latitude": "25.4N",
            "longitude": "88.2W",
            "latitudeNumeric": 25.4,
            "longitudeNumeric": -88.2,
            "movementDir": 315,
            "movementSpeed": 12,
            "lastUpdate": "2026-04-12T15:00:00.000Z",
            "publicAdvisory": {
                "advNum": "014",
                "issuance": "2026-04-12T15:00:00.000Z",
                "url": "https://www.nhc.noaa.gov/text/MIATCPAT4.shtml",
            },
        },
    ]
}


def _storm(**overrides):
    base = dict(SAMPLE_RESPONSE["activeStorms"][0])
    base.update(overrides)
    return base


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
        assert s["advisory_number"] == "014"
        assert s["movement"] == "NW at 12 kt"
        assert s["advisory_url"] == "https://www.nhc.noaa.gov/text/MIATCPAT4.shtml"
        assert s["last_update"] == "2026-04-12T15:00:00.000Z"

    def test_storm_without_numeric_position_is_skipped(self, collector):
        """Never fall back to (0, 0) — a null-island storm is worse than none."""
        data = {"activeStorms": [_storm(latitudeNumeric=None, longitudeNumeric=None)]}
        assert collector._parse_storms(data) == []

    def test_stationary_and_missing_movement(self, collector):
        still = collector._parse_storms({"activeStorms": [_storm(movementSpeed=0)]})
        unknown = collector._parse_storms(
            {"activeStorms": [_storm(movementDir=None, movementSpeed=None)]})
        assert still[0]["movement"] == "stationary"
        assert unknown[0]["movement"] == "unknown"

    def test_unparseable_numbers_do_not_crash(self, collector):
        s = collector._parse_storms(
            {"activeStorms": [_storm(intensity="N/A", pressure="")]})[0]
        assert (s["wind_speed_kt"], s["pressure_mb"]) == (0, 0)

    def test_parse_storms_empty(self, collector):
        storms = collector._parse_storms({"activeStorms": []})
        assert storms == []

    def test_classification_mapping(self, collector):
        for code, label in [
            ("TD", "Tropical Depression"),
            ("TS", "Tropical Storm"),
            ("HU", "Hurricane"),
        ]:
            data = {"activeStorms": [_storm(classification=code)]}
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


def test_collector_reads_the_current_storms_feed():
    from feeds.noaa_nhc_collector import _NHC_URL

    assert _NHC_URL == "https://www.nhc.noaa.gov/CurrentStorms.json"


@pytest.mark.asyncio
async def test_nhc_uses_public_advisory_url(collector):
    collector.http.get = AsyncMock(return_value=_nhc_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock(return_value=MagicMock())
    process = AsyncMock()

    with patch("pipeline.process_item", new=process):
        await collector.collect()

    assert process.await_args.kwargs["url"] == "https://www.nhc.noaa.gov/text/MIATCPAT4.shtml"
