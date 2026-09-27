"""Tests for USGS earthquake collector with nuclear test site enrichment."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client.models import PointStruct

from feeds.usgs_collector import (
    NUCLEAR_TEST_SITES,
    USGSCollector,
    concern_level,
    concern_score,
    haversine_km,
)
from pipeline import ExtractionConfigError, ExtractionTransientError


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "bolt://localhost:7687"
    s.neo4j_http_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = USGSCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_haversine_known_distance():
    d = haversine_km(40.7128, -74.0060, 33.9425, -118.4081)
    assert 3900 < d < 4000


def test_haversine_same_point():
    d = haversine_km(41.28, 129.08, 41.28, 129.08)
    assert d == 0.0


def test_concern_score_near_site():
    score = concern_score(magnitude=5.5, distance_km=5.0, depth_km=2.0)
    assert score > 50


def test_concern_score_far_away():
    score = concern_score(magnitude=4.5, distance_km=90.0, depth_km=50.0)
    assert score < 25


def test_concern_score_critical():
    score = concern_score(magnitude=8.0, distance_km=0.0, depth_km=1.0)
    assert score >= 75


def test_concern_level_thresholds():
    assert concern_level(80.0) == "critical"
    assert concern_level(60.0) == "elevated"
    assert concern_level(30.0) == "moderate"
    assert concern_level(10.0) is None


def test_nuclear_test_sites_count():
    assert len(NUCLEAR_TEST_SITES) == 5
    assert "Punggye-ri (DPRK)" in NUCLEAR_TEST_SITES


SAMPLE_GEOJSON = {
    "features": [
        {
            "id": "us7000test",
            "properties": {
                "mag": 5.2,
                "place": "45km NE of Kilju, North Korea",
                "time": 1712000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test",
            },
            "geometry": {
                "coordinates": [129.1, 41.3, 8.0],
            },
        },
        {
            "id": "us7000far",
            "properties": {
                "mag": 6.0,
                "place": "100km S of Tokyo, Japan",
                "time": 1712000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000far",
            },
            "geometry": {
                "coordinates": [139.7, 34.7, 30.0],
            },
        },
    ]
}


def test_parse_features(collector):
    results = collector._parse_features(SAMPLE_GEOJSON["features"])
    assert len(results) == 2

    near = results[0]
    assert near["usgs_id"] == "us7000test"
    assert near["magnitude"] == 5.2
    assert near["nearest_test_site"] is not None
    assert near["concern_score"] is not None
    assert near["concern_level"] is not None

    far = results[1]
    assert far["usgs_id"] == "us7000far"
    assert far["nearest_test_site"] is None
    assert far["concern_score"] is None


def test_null_depth_stays_unknown_without_concern_enrichment(collector):
    feature = {
        "id": "depth-unknown",
        "properties": {"mag": 5.2, "place": "near Punggye-ri", "time": 1712000000000},
        "geometry": {"coordinates": [129.1, 41.3, None]},
    }
    event = collector._parse_features([feature])[0]
    assert event["depth_km"] is None
    assert event["concern_score"] is None
    assert event["concern_level"] is None


def test_zero_depth_keeps_existing_near_site_concern_score(collector):
    feature = {
        "id": "depth-zero",
        "properties": {"mag": 5.2, "place": "Punggye-ri", "time": 1712000000000},
        "geometry": {"coordinates": [129.08, 41.28, 0]},
    }

    event = collector._parse_features([feature])[0]

    assert event["depth_km"] == 0.0
    assert event["nearest_test_site"] == "Punggye-ri (DPRK)"
    assert event["concern_score"] == concern_score(
        5.2, event["distance_to_site_km"], 0.0
    )
    assert event["concern_level"] == concern_level(event["concern_score"])


def test_bad_timestamp_row_isolated_and_numeric_string_milliseconds_allowed(collector):
    good = {
        "id": "good-before",
        "properties": {"mag": 4.5, "place": "Japan", "time": 1712000000000},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    bad = {
        "id": "bad-time",
        "properties": {"mag": 5.0, "place": "bad", "time": "broken"},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    numeric_string = {
        "id": "good-after",
        "properties": {"mag": 4.5, "place": "Japan", "time": "1712000000000"},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    events = collector._parse_features([good, bad, numeric_string])
    assert [event["usgs_id"] for event in events] == ["good-before", "good-after"]
    assert events[0]["event_time"] == events[1]["event_time"]


@pytest.mark.parametrize(
    "bad_time",
    [None, True, float("nan"), float("inf"), 10**400, "broken"],
)
def test_invalid_time_values_are_isolated(collector, bad_time):
    good = {
        "id": "good",
        "properties": {"mag": 4.5, "place": "Japan", "time": 1712000000000},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    invalid = {
        "id": "bad",
        "properties": {"mag": 5.0, "place": "bad", "time": bad_time},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    events = collector._parse_features([good, invalid, good | {"id": "good-after"}])
    assert [event["usgs_id"] for event in events] == ["good", "good-after"]


def test_missing_required_time_is_isolated(collector):
    good = {
        "id": "good",
        "properties": {"mag": 4.5, "place": "Japan", "time": 1712000000000},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    missing = {
        "id": "missing-time",
        "properties": {"mag": 5.0, "place": "bad"},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    events = collector._parse_features([good, missing, good | {"id": "good-after"}])
    assert [event["usgs_id"] for event in events] == ["good", "good-after"]


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf")])
def test_nonfinite_magnitude_isolated_from_valid_neighbors(collector, bad_value):
    good = {
        "id": "good",
        "properties": {"mag": 4.5, "place": "Japan", "time": 1712000000000},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    bad = {
        "id": "bad",
        "properties": {"mag": bad_value, "place": "bad", "time": 1712000000000},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    events = collector._parse_features([good, bad, good | {"id": "good-after"}])
    assert [event["usgs_id"] for event in events] == ["good", "good-after"]


@pytest.mark.parametrize(
    "coordinates",
    [[float("nan"), 0, 1], [0, float("inf"), 1], [181, 0, 1], [0, 91, 1]],
)
def test_invalid_coordinates_are_isolated_from_valid_neighbors(collector, coordinates):
    good = {
        "id": "good",
        "properties": {"mag": 4.5, "place": "Japan", "time": 1712000000000},
        "geometry": {"coordinates": [139.7, 34.7, 30]},
    }
    bad = {
        "id": "bad",
        "properties": {"mag": 5.0, "place": "bad", "time": 1712000000000},
        "geometry": {"coordinates": coordinates},
    }
    events = collector._parse_features([good, bad, good | {"id": "good-after"}])
    assert [event["usgs_id"] for event in events] == ["good", "good-after"]


@pytest.mark.asyncio
async def test_unknown_depth_is_preserved_in_evidence_and_qdrant_payload(collector):
    event = {
        "id": "unknown-depth",
        "properties": {
            "mag": 5.2,
            "place": "near Punggye-ri",
            "time": 1712000000000,
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/unknown-depth",
        },
        "geometry": {"coordinates": [129.1, 41.3, None]},
    }
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=False)
    collector._write_near_test_site = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector.http.get = AsyncMock()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"features": [event]}
    collector.http.get.return_value = response

    async def build_point(text, payload, content_hash):
        return PointStruct(id=1, vector=[0.0], payload=payload.copy())

    collector._build_point = AsyncMock(side_effect=build_point)
    with patch("feeds.usgs_collector.process_item", new=AsyncMock()) as process:
        await collector.collect()

    evidence = process.await_args.kwargs["source_evidence"]
    assert "Depth: unknown" in process.await_args.kwargs["text"]
    assert "Depth: None" not in process.await_args.kwargs["text"]
    assert evidence["depth_km"] is None
    assert evidence["concern_score"] is None
    assert evidence["concern_level"] is None
    payload = collector._batch_upsert.await_args.args[0][0].payload
    assert payload["depth_km"] is None
    assert payload["concern_score"] is None
    assert payload["concern_level"] is None


@pytest.mark.asyncio
async def test_unknown_depth_writes_null_concern_values_to_neo4j_payload(collector):
    event = collector._parse_features([{
        "id": "unknown-depth-near-site",
        "properties": {
            "mag": 5.2,
            "place": "near Punggye-ri",
            "time": 1712000000000,
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/unknown-depth-near-site",
        },
        "geometry": {"coordinates": [129.08, 41.28, None]},
    }])[0]
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "errors": [],
        "results": [{"columns": ["written"], "data": [{"row": [1]}]}],
    }
    collector.http.post = AsyncMock(return_value=response)

    assert await collector._write_near_test_site(event) == 1

    payload = collector.http.post.await_args.kwargs["json"]
    parameters = payload["statements"][0]["parameters"]
    assert parameters["concern_score"] is None
    assert parameters["concern_level"] is None


# ── Extraction error skip tests (Task 7) ────────────────────────────


def _usgs_http_resp():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = SAMPLE_GEOJSON
    return resp


@pytest.mark.asyncio
async def test_usgs_transient_skips_upsert(collector):
    """When process_item raises ExtractionTransientError, event is NOT upserted."""
    collector.http.get = AsyncMock(return_value=_usgs_http_resp())
    collector._dedup_check = AsyncMock(return_value=False)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._ensure_collection = AsyncMock()
    collector._write_near_test_site = AsyncMock()

    with patch(
        "feeds.usgs_collector.process_item",
        new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    # batch_upsert called once with an empty list (no points accumulated)
    collector._batch_upsert.assert_called_once_with([])


@pytest.mark.asyncio
async def test_usgs_config_skips_upsert(collector):
    """When process_item raises ExtractionConfigError, event is NOT upserted + error log."""
    collector.http.get = AsyncMock(return_value=_usgs_http_resp())
    collector._dedup_check = AsyncMock(return_value=False)
    collector._build_point = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._ensure_collection = AsyncMock()
    collector._write_near_test_site = AsyncMock()

    with (
        patch(
            "feeds.usgs_collector.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.usgs_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._build_point.assert_not_called()
    collector._batch_upsert.assert_called_once_with([])
    assert any(
        c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("written", [0, 1])
async def test_proximity_uses_current_graph_contract_and_reports_actual_writes(collector, written):
    event = collector._parse_features(SAMPLE_GEOJSON["features"])[0]

    async def post(url, *, json, auth):
        query = json["statements"][0]["statement"]
        assert "[:DESCRIBES]" in query
        assert "RETURN count(r) AS written" in query
        response = MagicMock()
        response.json.return_value = {
            "errors": [],
            "results": [
                {"columns": ["written"], "data": [{"row": [written]}]},
            ],
        }
        return response

    collector.http.post = post
    assert await collector._write_near_test_site(event) == written


@pytest.mark.asyncio
async def test_existing_qdrant_point_still_retries_proximity_edge(collector):
    collector._ensure_collection = AsyncMock()
    collector._dedup_check = AsyncMock(return_value=True)
    collector._batch_upsert = AsyncMock()
    collector._write_near_test_site = AsyncMock(return_value=1)
    response = MagicMock()
    response.json.return_value = SAMPLE_GEOJSON
    collector.http.get = AsyncMock(return_value=response)
    await collector.collect()
    collector._write_near_test_site.assert_awaited_once()
