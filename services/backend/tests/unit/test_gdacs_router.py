"""Tests for the GDACS events router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_point(
    pid: str,
    lat: float,
    lon: float,
    event_type: str = "EQ",
    alert_level: str = "Orange",
) -> object:
    class P:
        id = pid
        payload = {
            "source": "gdacs",
            "event_type": event_type,
            "event_name": f"GDACS Event {pid}",
            "alert_level": alert_level,
            "severity": 5.8,
            "country": "Turkey",
            "latitude": lat,
            "longitude": lon,
            "from_date": "2026-04-10T12:00:00Z",
            "to_date": "2026-04-11T12:00:00Z",
            "ingested_epoch": 1744300000.0,
        }

    return P()


@pytest.mark.asyncio
async def test_gdacs_events_returns_data() -> None:
    """Three Qdrant points → three JSON events with all fields mapped."""
    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.return_value = (
        [
            _make_point("id-a", 38.0, 38.0, "EQ", "Orange"),
            _make_point("id-b", 13.5, 144.8, "TC", "Red"),
            _make_point("id-c", 15.0, 42.0, "FL", "Green"),
        ],
        None,
    )

    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.gdacs.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/gdacs/events")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert body[0]["id"] == "id-a"
    assert body[0]["event_type"] == "EQ"
    assert body[0]["alert_level"] == "Orange"
    assert body[0]["latitude"] == 38.0
    assert body[0]["longitude"] == 38.0
    assert body[0]["severity"] == 5.8


@pytest.mark.asyncio
async def test_gdacs_events_cache_hit() -> None:
    """Cache hit returns cached data without calling Qdrant."""
    cached_payload = [
        {
            "id": "cached-a",
            "event_type": "TC",
            "event_name": "Typhoon Cached",
            "alert_level": "Red",
            "severity": 8.2,
            "country": "Philippines",
            "latitude": 13.5,
            "longitude": 144.8,
            "from_date": "2026-04-10T00:00:00Z",
            "to_date": "2026-04-12T00:00:00Z",
        }
    ]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = cached_payload
    app.state.cache = mock_cache

    mock_qdrant = AsyncMock()
    with patch("app.routers.gdacs.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/gdacs/events")

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "cached-a"
    mock_qdrant.scroll.assert_not_called()


@pytest.mark.asyncio
async def test_gdacs_events_qdrant_down() -> None:
    """Qdrant exception → 503 response."""
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.side_effect = ConnectionError("qdrant unreachable")

    with patch("app.routers.gdacs.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/gdacs/events")

    assert resp.status_code == 503
    assert "qdrant" in resp.json()["detail"].lower()
