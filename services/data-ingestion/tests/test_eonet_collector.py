"""Tests for EONET natural events collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.eonet_collector import EONETCollector
from pipeline import ExtractionConfigError, ExtractionTransientError

SAMPLE_RESPONSE = {
    "events": [
        {
            "id": "EONET_1234",
            "title": "Wildfire - California",
            "categories": [{"id": "wildfires", "title": "Wildfires"}],
            "geometry": [
                {
                    "date": "2026-04-10T12:00:00Z",
                    "type": "Point",
                    "coordinates": [-118.5, 34.0],
                }
            ],
            "closed": None,
        },
        {
            "id": "EONET_5678",
            "title": "Volcano - Etna",
            "categories": [{"id": "volcanoes", "title": "Volcanoes"}],
            "geometry": [
                {
                    "date": "2026-04-09T08:00:00Z",
                    "type": "Point",
                    "coordinates": [15.0, 37.75],
                }
            ],
            "closed": "2026-04-11T00:00:00Z",
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
        c = EONETCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


class TestEONETParser:
    def test_parse_events_extracts_all_fields(self, collector):
        events = collector._parse_events(SAMPLE_RESPONSE)
        assert len(events) == 2

        e1 = events[0]
        assert e1["eonet_id"] == "EONET_1234"
        assert e1["title"] == "Wildfire - California"
        assert e1["category"] == "wildfires"
        assert e1["status"] == "open"
        assert e1["latitude"] == 34.0
        assert e1["longitude"] == -118.5
        assert e1["event_date"] == "2026-04-10T12:00:00Z"

    def test_parse_events_closed_status(self, collector):
        events = collector._parse_events(SAMPLE_RESPONSE)
        e2 = events[1]
        assert e2["status"] == "closed"
        assert e2["category"] == "volcanoes"

    def test_parse_events_empty_input(self, collector):
        events = collector._parse_events({"events": []})
        assert events == []

    def test_parse_events_uses_latest_geometry(self, collector):
        response = {
            "events": [
                {
                    "id": "E1",
                    "title": "Storm",
                    "categories": [{"id": "severeStorms"}],
                    "geometry": [
                        {"date": "2026-04-08T00:00:00Z", "type": "Point", "coordinates": [10.0, 20.0]},
                        {"date": "2026-04-10T00:00:00Z", "type": "Point", "coordinates": [11.0, 21.0]},
                    ],
                    "closed": None,
                }
            ]
        }
        events = collector._parse_events(response)
        assert events[0]["latitude"] == 21.0
        assert events[0]["longitude"] == 11.0
        assert events[0]["event_date"] == "2026-04-10T00:00:00Z"


    def test_parse_events_skips_polygon_geometries(self, collector):
        """EONET returns Polygon geometries for some events — only Point should be used."""
        response = {
            "events": [
                {
                    "id": "E_POLY",
                    "title": "Ice Event",
                    "categories": [{"id": "seaLakeIce"}],
                    "geometry": [
                        {
                            "date": "2026-04-10T00:00:00Z",
                            "type": "Polygon",
                            "coordinates": [[[10, 20], [11, 20], [11, 21], [10, 21], [10, 20]]],
                        }
                    ],
                    "closed": None,
                }
            ]
        }
        events = collector._parse_events(response)
        assert events == []

    def test_parse_events_uses_point_over_polygon(self, collector):
        """When both Point and Polygon exist, only Point geometries are considered."""
        response = {
            "events": [
                {
                    "id": "E_MIXED",
                    "title": "Storm Mixed",
                    "categories": [{"id": "severeStorms"}],
                    "geometry": [
                        {"date": "2026-04-10T00:00:00Z", "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                        {"date": "2026-04-09T00:00:00Z", "type": "Point", "coordinates": [5.0, 10.0]},
                    ],
                    "closed": None,
                }
            ]
        }
        events = collector._parse_events(response)
        assert len(events) == 1
        assert events[0]["latitude"] == 10.0
        assert events[0]["longitude"] == 5.0


class TestEONETContentHash:
    def test_stable_hash_for_same_id(self, collector):
        h1 = collector._content_hash("eonet", "EONET_1234")
        h2 = collector._content_hash("eonet", "EONET_1234")
        assert h1 == h2

    def test_different_hash_for_different_id(self, collector):
        h1 = collector._content_hash("eonet", "EONET_1234")
        h2 = collector._content_hash("eonet", "EONET_5678")
        assert h1 != h2


# ── Extraction error skip tests (Task 7) ────────────────────────────


def _eonet_http_resp():
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = SAMPLE_RESPONSE
    return r


@pytest.mark.asyncio
async def test_eonet_transient_skips_upsert(collector):
    """When process_item raises ExtractionTransientError, event is NOT upserted."""
    collector.http.get = AsyncMock(return_value=_eonet_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    # Force is_new branch
    collector.qdrant.retrieve.return_value = []

    with patch(
        "pipeline.process_item",
        new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
    ):
        await collector.collect()

    # With transient error, the row is skipped — no upsert reached
    collector._batch_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_eonet_config_skips_upsert(collector):
    """When process_item raises ExtractionConfigError, event is NOT upserted + error log."""
    collector.http.get = AsyncMock(return_value=_eonet_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._embed = AsyncMock(return_value=[0.0] * 1024)
    collector.qdrant.retrieve.return_value = []

    with (
        patch(
            "pipeline.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.eonet_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._batch_upsert.assert_not_called()
    assert any(
        c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list
    )
