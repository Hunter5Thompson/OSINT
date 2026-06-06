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
    resp = client.get("/api/timeline/window?t_start=2026-05-02T00:00:00Z&t_end=2026-05-01T00:00:00Z")
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
