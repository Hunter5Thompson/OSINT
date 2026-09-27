"""Tests for HAPI humanitarian conflict collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.hapi_collector import FOCUS_COUNTRIES, HAPICollector
from pipeline import ExtractionConfigError, ExtractionTransientError

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

    def test_nullable_and_malformed_counts_are_isolated_per_record(self, collector):
        records = collector._parse_records({"data": [
            {
                "reference_period_start": "2026-03-01",
                "event_type": "political_violence",
                "events": None,
                "fatalities": "",
            },
            {
                "reference_period_start": "2026-03-01",
                "event_type": "civilian_targeting",
                "events": "bad-count",
                "fatalities": 2,
            },
            {
                "reference_period_start": "2026-03-01",
                "event_type": "negative-count",
                "events": -1,
                "fatalities": 2,
            },
            {
                "reference_period_start": "2026-03-01",
                "event_type": "explosions",
                "events": 3,
                "fatalities": 0,
            },
        ]}, "UKR")

        assert [record["event_type"] for record in records] == [
            "political_violence", "explosions"
        ]
        assert records[0]["events_count"] is None
        assert records[0]["fatalities"] is None
        assert records[1]["events_count"] == 3
        assert records[1]["fatalities"] == 0

    def test_invalid_identity_fields_are_skipped_between_valid_records(self, collector):
        records = collector._parse_records({"data": [
            {
                "reference_period_start": "2026-03-01",
                "event_type": "political_violence",
                "events": 1,
                "fatalities": 0,
            },
            {
                "reference_period_start": None,
                "event_type": "civilian_targeting",
                "events": 2,
                "fatalities": 1,
            },
            {
                "reference_period_start": "2026-04-01",
                "event_type": None,
                "events": 3,
                "fatalities": 0,
            },
            {
                "reference_period_start": "not-a-date",
                "event_type": "explosions",
                "events": 4,
                "fatalities": 0,
            },
            {
                "reference_period_start": "2026-05-01",
                "event_type": "explosions",
                "events": 5,
                "fatalities": 0,
            },
        ]}, "UKR")

        assert [(record["reference_period"], record["event_type"]) for record in records] == [
            ("2026-03", "political_violence"),
            ("2026-05", "explosions"),
        ]


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

    def test_hapi_document_constraint_is_operator_run_and_scoped(self):
        migration = Path(__file__).parents[1] / "migrations/hapi_document_id_unique.cypher"
        statement = migration.read_text()
        assert "MATCH (d:HAPIDocument)" in statement
        assert "d.doc_id AS doc_id" in statement
        assert "CREATE CONSTRAINT hapi_document_id_unique IF NOT EXISTS" in statement
        assert "FOR (d:HAPIDocument) REQUIRE d.doc_id IS UNIQUE" in statement
        assert "Apply this before enabling parallel HAPI writers" in statement


# ── Extraction error skip tests (Task 7) ────────────────────────────


def _hapi_http_resp():
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = SAMPLE_RESPONSE
    return r


@pytest.mark.asyncio
async def test_hapi_transient_skips_upsert(collector):
    """When process_item raises ExtractionTransientError, record is NOT upserted."""
    collector.http.get = AsyncMock(return_value=_hapi_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()

    with (
        patch("feeds.hapi_collector.FOCUS_COUNTRIES", ["UKR"]),
        patch("feeds.hapi_collector.asyncio.sleep", new=AsyncMock()),
        patch(
            "pipeline.process_item",
            new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
        ),
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_hapi_config_skips_upsert(collector):
    """When process_item raises ExtractionConfigError, record is NOT upserted + error log."""
    collector.http.get = AsyncMock(return_value=_hapi_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()

    with (
        patch("feeds.hapi_collector.FOCUS_COUNTRIES", ["UKR"]),
        patch("feeds.hapi_collector.asyncio.sleep", new=AsyncMock()),
        patch(
            "pipeline.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.hapi_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_not_called()
    assert any(
        c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list
    )


@pytest.mark.asyncio
async def test_hapi_passes_canonical_record_identity_to_pipeline(collector):
    collector.http.get = AsyncMock(return_value=_hapi_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._batch_upsert = AsyncMock()
    collector._build_point = AsyncMock()

    with (
        patch("feeds.hapi_collector.FOCUS_COUNTRIES", ["UKR"]),
        patch("feeds.hapi_collector.asyncio.sleep", new=AsyncMock()),
        patch("pipeline.process_item", new=AsyncMock()) as process,
    ):
        await collector.collect()

    kwargs = process.await_args_list[0].kwargs
    record_hash = collector._content_hash("UKR", "2026-03", "political_violence")
    assert kwargs["source"] == "hapi"
    assert kwargs["url"] == "https://hapi.humdata.org/api/v2/coordination-context/conflict-events"
    assert kwargs["content_hash"] == record_hash
    assert kwargs["document_id"] == f"hapi:conflict-events:{record_hash}"
