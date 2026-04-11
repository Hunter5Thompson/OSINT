"""Tests for the Aircraft tracks router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.asyncio
async def test_aircraft_tracks_happy_path() -> None:
    """Two aircraft, one with 3 points and one with 1 point."""
    rows = [
        {
            "icao24": "AE1234",
            "callsign": "RCH842",
            "type_code": "C17",
            "military_branch": "USAF",
            "registration": "05-5140",
            "points": [
                {"lat": 51.0, "lon": 12.0, "altitude_m": 10000, "speed_ms": 240, "heading": 90, "timestamp": 1744300000},
                {"lat": 51.2, "lon": 12.3, "altitude_m": 10100, "speed_ms": 242, "heading": 92, "timestamp": 1744300900},
                {"lat": 51.4, "lon": 12.6, "altitude_m": 10200, "speed_ms": 245, "heading": 94, "timestamp": 1744301800},
            ],
        },
        {
            "icao24": "AE5678",
            "callsign": None,
            "type_code": "KC135",
            "military_branch": "USAF",
            "registration": "58-0100",
            "points": [
                {"lat": 49.0, "lon": 8.0, "altitude_m": 9000, "speed_ms": 220, "heading": 180, "timestamp": 1744302000},
            ],
        },
    ]

    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.aircraft.read_query", AsyncMock(return_value=rows)):
        client = TestClient(app)
        resp = client.get("/api/v1/aircraft/tracks")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["icao24"] == "AE1234"
    assert len(body[0]["points"]) == 3
    assert body[0]["points"][0]["altitude_m"] == 10000
    assert body[1]["callsign"] is None
    assert len(body[1]["points"]) == 1


@pytest.mark.asyncio
async def test_aircraft_tracks_cache_hit_short_circuits_neo4j() -> None:
    cached = [{
        "icao24": "AE9999",
        "callsign": "TEST01",
        "type_code": "F16",
        "military_branch": "USAF",
        "registration": "87-0001",
        "points": [{
            "lat": 40.0, "lon": -70.0,
            "altitude_m": 5000, "speed_ms": 200, "heading": 270,
            "timestamp": 1744300000,
        }],
    }]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = cached
    app.state.cache = mock_cache

    read_mock = AsyncMock()
    with patch("app.routers.aircraft.read_query", read_mock):
        client = TestClient(app)
        resp = client.get("/api/v1/aircraft/tracks")

    assert resp.status_code == 200
    assert resp.json()[0]["icao24"] == "AE9999"
    read_mock.assert_not_called()


@pytest.mark.asyncio
async def test_aircraft_tracks_empty_neo4j_returns_empty_list() -> None:
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.aircraft.read_query", AsyncMock(return_value=[])):
        client = TestClient(app)
        resp = client.get("/api/v1/aircraft/tracks")

    assert resp.status_code == 200
    assert resp.json() == []


def test_aircraft_tracks_since_hours_too_low_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/aircraft/tracks?since_hours=0")
    assert resp.status_code == 422


def test_aircraft_tracks_since_hours_too_high_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/aircraft/tracks?since_hours=73")
    assert resp.status_code == 422


def test_aircraft_tracks_query_filters_null_coordinates() -> None:
    """Cypher text must filter null lat/lon so the router doesn't rely on Python-side filtering."""
    from app.routers.aircraft import _TRACK_QUERY
    assert "r.latitude IS NOT NULL" in _TRACK_QUERY
    assert "r.longitude IS NOT NULL" in _TRACK_QUERY
