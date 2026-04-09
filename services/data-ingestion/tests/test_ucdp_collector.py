"""Tests for UCDP GED conflict data collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.ucdp_collector import VIOLENCE_TYPES, UCDPCollector


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 90.0
    s.embedding_dimensions = 1024
    s.ucdp_access_token = ""
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


SAMPLE_UCDP_RESPONSE = {
    "TotalCount": 1,
    "Result": [
        {
            "id": "12345",
            "type_of_violence": 1,
            "best": 5,
            "low": 3,
            "high": 8,
            "country": "Syria",
            "region": "Middle East",
            "latitude": "36.2",
            "longitude": "37.1",
            "date_start": "2026-03-15",
            "date_end": "2026-03-15",
            "side_a": "Government of Syria",
            "side_b": "IS",
            "source_article": "Clash in Aleppo countryside.",
        }
    ],
}


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = UCDPCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_violence_type_labels():
    assert VIOLENCE_TYPES[1] == "state-based"
    assert VIOLENCE_TYPES[2] == "non-state"
    assert VIOLENCE_TYPES[3] == "one-sided"


def test_parse_event(collector):
    raw = SAMPLE_UCDP_RESPONSE["Result"][0]
    payload = collector._parse_event(raw)
    assert payload["source"] == "ucdp"
    assert payload["ucdp_id"] == "12345"
    assert payload["violence_type"] == 1
    assert payload["violence_type_label"] == "state-based"
    assert payload["best_estimate"] == 5
    assert payload["latitude"] == 36.2


@pytest.mark.asyncio
async def test_discover_version_finds_valid(collector):
    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.json.return_value = {"Result": [{"id": "1"}]}

    collector.http.get = AsyncMock(return_value=good_resp)
    version = await collector._discover_version()
    assert version is not None


@pytest.mark.asyncio
async def test_discover_version_tries_fallbacks(collector):
    bad_resp = MagicMock()
    bad_resp.status_code = 404
    bad_resp.json.return_value = {}

    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.json.return_value = {"Result": [{"id": "1"}]}

    collector.http.get = AsyncMock(side_effect=[bad_resp, bad_resp, good_resp])
    version = await collector._discover_version()
    assert version is not None
    assert collector.http.get.call_count == 3
