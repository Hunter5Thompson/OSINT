from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_event_detail_returns_payload(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.return_value = [{
            "id": "gdelt:1", "title": None, "codebook_type": "military.airstrike",
            "severity": None, "time": "2026-06-01T00:00:00Z", "time_basis": "indexed",
            "source": "gdelt", "url": "http://x", "location_name": "Kyiv",
            "country": "UA", "lat": 50.4, "lon": 30.5,
        }]
        resp = client.get("/api/timeline/events/gdelt:1")
    assert resp.status_code == 200
    d = resp.json()
    assert d["id"] == "gdelt:1" and d["source"] == "gdelt" and d["country"] == "UA"


def test_event_detail_unknown_404(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.return_value = []
        resp = client.get("/api/timeline/events/nope")
    assert resp.status_code == 404
