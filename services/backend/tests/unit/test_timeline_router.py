from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

W = "?t_start=2026-05-01T00:00:00Z&t_end=2026-05-02T00:00:00Z"


@pytest.fixture
def client():
    return TestClient(app)


def test_events_window_returns_samples(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [
            [{
                "id": "gdelt:event:1", "title": None, "codebook_type": "military.airstrike",
                "severity": None, "time": "2026-05-01T06:00:00Z", "time_basis": "indexed",
                "location_name": None, "country": None, "lat": None, "lon": None,
            }],
            [{"total": 1}],
        ]
        resp = client.get(f"/api/timeline/window{W}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "events" and data["tier"] == "coarse"
    assert data["samples"][0]["kind"] == "event"
    assert data["samples"][0]["title"] is None  # GDELT nullable
    assert data["samples"][0]["time_basis"] == "indexed"
    assert data["total_count"] == 1 and data["truncated"] is False


def test_reversed_window_422(client):
    resp = client.get(
        "/api/timeline/window?t_start=2026-05-02T00:00:00Z&t_end=2026-05-01T00:00:00Z"
    )
    assert resp.status_code == 422


def test_limit_over_cap_422(client):
    resp = client.get(f"/api/timeline/window{W}&limit=999")
    assert resp.status_code == 422


def test_events_with_movement_kind_422(client):
    resp = client.get(f"/api/timeline/window{W}&movement_kind=mil_aircraft")
    assert resp.status_code == 422


def test_events_fine_422(client):
    resp = client.get(f"/api/timeline/window{W}&tier=fine")
    assert resp.status_code == 422


def test_movements_mil_aircraft_window(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [
            [{
                "icao24": "abc123", "callsign": "FORTE10", "type_code": "RQ4",
                "military_branch": "USAF", "registration": None,
                "points": [
                    {"ts_ms": 1714521600000, "lat": 50.0, "lon": 30.0,
                     "altitude_m": 18000.0, "speed_ms": 200.0, "heading": 90.0},
                ],
            }],
            [{"total": 1}],  # count query (tracks, not points)
        ]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "movements"
    s = data["samples"][0]
    assert s["kind"] == "track" and s["icao24"] == "abc123"
    assert s["points"][0]["ts_ms"] == 1714521600000
    assert data["total_count"] == 1  # counts TRACKS not points
    assert data["truncated"] is False


_TRK = {
    "icao24": "a", "callsign": None, "type_code": None, "military_branch": None,
    "registration": None, "points": [{"ts_ms": 1, "lat": 0.0, "lon": 0.0}],
}


def test_movements_truncated_uses_pre_limit_count(client):
    # 2 tracks returned (limit hit) but the true match count is 5 -> truncated.
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[_TRK, _TRK], [{"total": 5}]]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft&limit=2"
        )
    data = resp.json()
    assert data["total_count"] == 5 and data["truncated"] is True


def test_movements_not_truncated_when_count_equals_returned(client):
    # exactly `limit` tracks and nothing dropped -> NOT truncated (total > len is False).
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[_TRK, _TRK], [{"total": 2}]]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft&limit=2"
        )
    data = resp.json()
    assert data["total_count"] == 2 and data["truncated"] is False


def test_movements_bbox_antimeridian_plumbing(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [{"total": 0}]]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine"
            "&movement_kind=mil_aircraft&bbox=170,-10,-170,10"
        )
    assert resp.status_code == 200
    assert resp.json()["bbox"] == {"west": 170.0, "south": -10.0, "east": -170.0, "north": 10.0}


def test_events_neo4j_down_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("boom")
        resp = client.get(f"/api/timeline/window{W}")
    assert resp.status_code == 503


def test_movements_neo4j_down_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("boom")
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft"
        )
    assert resp.status_code == 503


@pytest.mark.parametrize("kind", ["civil_aircraft", "ship", "satellite"])
def test_movements_unimplemented_kinds_501(client, kind):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind={kind}"
    )
    assert resp.status_code == 501


def test_window_mixed_naive_tz_reversed_422(client):
    resp = client.get(
        "/api/timeline/window?t_start=2026-05-02T00:00:00Z&t_end=2026-05-01T00:00:00"
    )
    assert resp.status_code == 422


def test_movements_missing_kind_422(client):
    resp = client.get(f"/api/timeline/window{W}&domain=movements&tier=fine")
    assert resp.status_code == 422


def test_movements_coarse_422(client):
    resp = client.get(f"/api/timeline/window{W}&domain=movements&movement_kind=mil_aircraft")
    assert resp.status_code == 422  # tier defaults to coarse


def test_movements_civil_501(client):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=civil_aircraft"
    )
    assert resp.status_code == 501


def test_movements_unknown_kind_422(client):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=bicycle"
    )
    assert resp.status_code == 422
