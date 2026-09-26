"""Tests for GDACS disaster alert collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.gdacs_collector import GDACSCollector
from pipeline import ExtractionConfigError, ExtractionTransientError

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


    def test_parse_features_null_severity(self, collector):
        """GDACS sometimes returns null severity — should not crash the entire cycle."""
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
                    "properties": {
                        "eventtype": "FL",
                        "eventid": "3003",
                        "eventname": "Flood Test",
                        "alertlevel": "Green",
                        "severity": {"value": None},
                        "country": "Test",
                        "fromdate": "2026-04-10",
                        "todate": "2026-04-10",
                    },
                },
            ],
        }
        events = collector._parse_features(data)
        assert len(events) == 1
        assert events[0]["severity"] == 0.0

    def test_parse_features_non_dict_severity(self, collector):
        """GDACS severity might be a bare number or string — handle gracefully."""
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
                    "properties": {
                        "eventtype": "EQ",
                        "eventid": "4004",
                        "eventname": "Quake",
                        "alertlevel": "Orange",
                        "severity": "invalid",
                        "country": "Test",
                        "fromdate": "2026-04-10",
                        "todate": "2026-04-10",
                    },
                },
            ],
        }
        events = collector._parse_features(data)
        assert len(events) == 1
        assert events[0]["severity"] == 0.0


class TestGDACSContentHash:
    def test_stable_hash(self, collector):
        h1 = collector._content_hash("gdacs", "EQ", "1001")
        h2 = collector._content_hash("gdacs", "EQ", "1001")
        assert h1 == h2

    def test_different_type_different_hash(self, collector):
        h1 = collector._content_hash("gdacs", "EQ", "1001")
        h2 = collector._content_hash("gdacs", "TC", "1001")
        assert h1 != h2


# ── Extraction error skip tests (Task 7) ────────────────────────────


def _gdacs_http_resp():
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = SAMPLE_GEOJSON
    return r


@pytest.mark.asyncio
async def test_gdacs_transient_skips_upsert(collector):
    """When process_item raises ExtractionTransientError, event is NOT upserted."""
    collector.http.get = AsyncMock(return_value=_gdacs_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._embed = AsyncMock(return_value=[0.0] * 1024)
    collector.qdrant.retrieve.return_value = []

    with patch(
        "pipeline.process_item",
        new=AsyncMock(side_effect=ExtractionTransientError("vllm down")),
    ):
        await collector.collect()

    collector._batch_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_gdacs_config_skips_upsert(collector):
    """When process_item raises ExtractionConfigError, event is NOT upserted + error log."""
    collector.http.get = AsyncMock(return_value=_gdacs_http_resp())
    collector._ensure_collection = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._embed = AsyncMock(return_value=[0.0] * 1024)
    collector.qdrant.retrieve.return_value = []

    with (
        patch(
            "pipeline.process_item",
            new=AsyncMock(side_effect=ExtractionConfigError("404 model")),
        ),
        patch("feeds.gdacs_collector.log.error") as mock_err,
    ):
        await collector.collect()

    collector._batch_upsert.assert_not_called()
    assert any(
        c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list
    )


# ── Provenance builder tests (Task 15) ──────────────────────────────


def test_build_gdacs_payload_stamps_provenance_and_no_published():
    from feeds.gdacs_collector import build_gdacs_payload
    event = {"gdacs_id": "EQ_1", "event_type": "EQ", "event_name": "Quake",
             "alert_level": "Orange", "severity": 5.0, "country": "X",
             "latitude": 1.0, "longitude": 2.0,
             "from_date": "2026-05-30", "to_date": "2026-05-31"}
    payload = build_gdacs_payload(event, "desc text")
    assert payload["source_type"] == "dataset"
    assert payload["provider"] == "gdacs.org"
    assert "published_at" not in payload
    assert "credibility_score" not in payload
    assert "ingested_at" in payload
    assert "ingested_epoch" in payload


# ── GDACS MAP API schema change (2026-09): eventtype required, 1 per call,
#    multi-geometry features per event, severity moved to severitydata ────────


def _feature(eid, geom_type, coords, cls=None, **props):
    p = {"eventtype": "TC", "eventid": eid, "eventname": "Storm X",
         "alertlevel": "Orange", "country": "Japan",
         "fromdate": "2026-09-20T00:00:00", "todate": "2026-09-25T00:00:00", **props}
    if cls is not None:
        p["Class"] = cls
    return {"type": "Feature", "geometry": {"type": geom_type, "coordinates": coords},
            "properties": p}


MAP_TC_MULTIGEOM = {
    "type": "FeatureCollection",
    "features": [
        _feature(7, "LineString", [[130.0, 20.0], [131.0, 21.0]], cls="Line_Line_0"),
        _feature(7, "Polygon", [[[130, 20], [131, 20], [131, 21], [130, 20]]], cls="Poly_Cones"),
        _feature(7, "Point", [131.5, 21.5], cls="Point_Polygon_Point_0"),
        _feature(7, "Point", [132.0, 22.0], cls="Point_Centroid",
                 severitydata={"severity": 83.3, "severitytext": "Tropical Storm",
                               "severityunit": "km/h"}),
    ],
}


class TestGDACSMapSchema:
    def test_one_event_per_eventid_using_centroid(self, collector):
        events = collector._parse_features(MAP_TC_MULTIGEOM)
        assert len(events) == 1
        assert events[0]["gdacs_id"] == "TC_7"
        assert (events[0]["latitude"], events[0]["longitude"]) == (22.0, 132.0)

    def test_non_point_geometry_never_becomes_an_event(self, collector):
        data = {"type": "FeatureCollection", "features": [
            _feature(8, "LineString", [[1.0, 2.0], [3.0, 4.0]]),
            _feature(9, "Polygon", [[[1, 2], [3, 4], [5, 6], [1, 2]]]),
        ]}
        assert collector._parse_features(data) == []

    def test_severity_read_from_severitydata(self, collector):
        events = collector._parse_features(MAP_TC_MULTIGEOM)
        assert events[0]["severity"] == 83.3

    def test_empty_eventname_falls_back_to_name(self, collector):
        data = {"type": "FeatureCollection", "features": [
            _feature(10, "Point", [168.4, -21.3], cls="Point_Centroid", eventtype="EQ",
                     eventname="", name="Earthquake in New Caledonia"),
        ]}
        assert collector._parse_features(data)[0]["event_name"] == "Earthquake in New Caledonia"


def _resp(status, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    if status >= 400:
        import httpx
        req = httpx.Request("GET", "https://www.gdacs.org/x")
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            "err", request=req, response=httpx.Response(status, request=req))
    else:
        r.raise_for_status = MagicMock()
    return r


def _wire_collect(collector):
    collector._ensure_collection = AsyncMock()
    collector._batch_upsert = AsyncMock()
    collector._embed = AsyncMock(return_value=[0.0] * 1024)
    collector.qdrant.retrieve.return_value = [MagicMock()]  # existing → no LLM path


@pytest.mark.asyncio
async def test_collect_requests_each_event_type_separately(collector):
    from feeds.gdacs_collector import GDACS_EVENT_TYPES

    _wire_collect(collector)
    collector.http.get = AsyncMock(return_value=_resp(200, {"features": []}))
    await collector.collect()

    requested = [c.kwargs["params"]["eventtype"] for c in collector.http.get.call_args_list]
    assert requested == list(GDACS_EVENT_TYPES)
    assert {"EQ", "TC", "FL", "VO", "DR", "WF"} <= set(GDACS_EVENT_TYPES)


@pytest.mark.asyncio
async def test_collect_isolates_failing_event_types(collector):
    """VO answers 404 when MAP has nothing; a 500 on another type must not
    drop the events of the healthy types."""
    _wire_collect(collector)

    def by_type(url, *, params, timeout):
        t = params["eventtype"]
        if t == "VO":
            return _resp(404)
        if t == "FL":
            return _resp(500)
        if t == "TC":
            return _resp(200, MAP_TC_MULTIGEOM)
        return _resp(200, {"features": []})

    collector.http.get = AsyncMock(side_effect=by_type)
    await collector.collect()

    collector._batch_upsert.assert_awaited_once()
    points = collector._batch_upsert.await_args.args[0]
    assert [p.payload["gdacs_id"] for p in points] == ["TC_7"]


@pytest.mark.asyncio
async def test_collect_dedupes_events_across_responses(collector):
    _wire_collect(collector)
    collector.http.get = AsyncMock(return_value=_resp(200, SAMPLE_GEOJSON))
    await collector.collect()

    points = collector._batch_upsert.await_args.args[0]
    ids = [p.payload["gdacs_id"] for p in points]
    assert sorted(ids) == ["EQ_1001", "TC_2002"]
