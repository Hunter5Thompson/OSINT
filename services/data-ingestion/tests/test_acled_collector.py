"""Tests for ACLED conflict data collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.acled_collector import ACLEDCollector


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.acled_email = "test@test.com"
    s.acled_password = "testpass"
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


SAMPLE_ACLED_RESPONSE = {
    "success": True,
    "data": [
        {
            "event_id_cnty": "SYR12345",
            "event_date": "2026-04-01",
            "event_type": "Battles",
            "sub_event_type": "Armed clash",
            "actor1": "Syrian Democratic Forces",
            "actor2": "ISIL",
            "admin1": "Hasakah",
            "country": "Syria",
            "latitude": "36.5",
            "longitude": "40.7",
            "fatalities": "3",
            "notes": "SDF clashed with ISIL remnants near Hasakah.",
            "source": "Syrian Observatory for Human Rights",
        }
    ],
}


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = ACLEDCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []  # no duplicates
    return c


def test_build_acled_url(collector):
    url = collector._build_query_url(page=1)
    assert "acleddata.com" in url
    assert "event_type=Battles" in url
    assert "page=1" in url


def test_parse_event(collector):
    raw = SAMPLE_ACLED_RESPONSE["data"][0]
    payload = collector._parse_event(raw)
    assert payload["source"] == "acled"
    assert payload["acled_event_id"] == "SYR12345"
    assert payload["event_type"] == "Battles"
    assert payload["fatalities"] == 3
    assert payload["latitude"] == 36.5
    assert payload["longitude"] == 40.7


def test_parse_event_missing_coords(collector):
    raw = {**SAMPLE_ACLED_RESPONSE["data"][0], "latitude": "", "longitude": ""}
    payload = collector._parse_event(raw)
    assert payload["latitude"] is None
    assert payload["longitude"] is None


@pytest.mark.asyncio
async def test_authenticate_gets_token(collector):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "tok123"}
    mock_resp.raise_for_status = MagicMock()
    collector.http.post = AsyncMock(return_value=mock_resp)
    await collector._authenticate()
    assert collector._token == "tok123"


@pytest.mark.asyncio
async def test_authenticate_failure_raises(collector):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")
    collector.http.post = AsyncMock(return_value=mock_resp)
    with pytest.raises(Exception, match="401"):
        await collector._authenticate()
