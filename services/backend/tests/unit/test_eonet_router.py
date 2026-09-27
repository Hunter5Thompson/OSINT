"""Tests for the EONET events router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_point(pid: str, lat: float, lon: float, category: str = "Wildfires") -> object:
    class P:
        id = pid
        payload = {
            "source": "eonet",
            "title": f"Event {pid}",
            "category": category,
            "status": "open",
            "latitude": lat,
            "longitude": lon,
            "event_date": "2026-04-11T00:00:00Z",
            "ingested_epoch": 1744300000.0,
        }

    return P()


@pytest.mark.asyncio
async def test_eonet_events_returns_data() -> None:
    """Three Qdrant points → three JSON events with all fields mapped."""
    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.return_value = (
        [
            _make_point("id-a", 48.1, 37.8, "Wildfires"),
            _make_point("id-b", 35.0, -120.0, "Volcanoes"),
            _make_point("id-c", -8.5, 115.0, "Floods"),
        ],
        None,
    )

    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.eonet.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/eonet/events")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert body[0]["id"] == "id-a"
    assert body[0]["category"] == "Wildfires"
    assert body[0]["latitude"] == 48.1
    assert body[0]["longitude"] == 37.8
    assert body[0]["status"] == "open"


@pytest.mark.asyncio
async def test_eonet_events_cache_hit() -> None:
    """Cache hit returns cached data without calling Qdrant."""
    cached_payload = [
        {
            "id": "cached-a",
            "title": "Cached Wildfire",
            "category": "Wildfires",
            "status": "open",
            "latitude": 48.1,
            "longitude": 37.8,
            "event_date": "2026-04-11T00:00:00Z",
        }
    ]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = cached_payload
    app.state.cache = mock_cache

    mock_qdrant = AsyncMock()
    with patch("app.routers.eonet.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/eonet/events")

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "cached-a"
    mock_qdrant.scroll.assert_not_called()


@pytest.mark.asyncio
async def test_eonet_events_qdrant_down() -> None:
    """Qdrant exception → 503 response."""
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.side_effect = ConnectionError("qdrant unreachable")

    with patch("app.routers.eonet.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/eonet/events")

    assert resp.status_code == 503
    assert "qdrant" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_eonet_cache_rows_are_isolated_and_repaired() -> None:
    good = {
        "id": "cached-good", "title": "Good", "category": "Wildfires",
        "status": "open", "latitude": 48.1, "longitude": 37.8,
        "event_date": "2026-04-11T00:00:00Z",
    }
    cache = AsyncMock()
    cache.get.return_value = [good, None, {**good, "id": "bad", "longitude": 181}]
    app.state.cache = cache
    qdrant = AsyncMock()
    with patch("app.routers.eonet.get_qdrant_client", AsyncMock(return_value=qdrant)):
        response = TestClient(app).get("/api/eonet/events")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["cached-good"]
    cache.set.assert_awaited_once()
    qdrant.scroll.assert_not_called()


@pytest.mark.asyncio
async def test_eonet_all_invalid_cache_is_deleted_and_qdrant_error_is_503() -> None:
    cache = AsyncMock()
    cache.get.return_value = [None, {"id": "broken"}]
    app.state.cache = cache
    qdrant = AsyncMock()
    qdrant.scroll.side_effect = ConnectionError("offline")
    with patch("app.routers.eonet.get_qdrant_client", AsyncMock(return_value=qdrant)):
        response = TestClient(app).get("/api/eonet/events")
    assert response.status_code == 503
    cache.delete.assert_awaited_once_with("eonet:events:168h")


@pytest.mark.asyncio
async def test_eonet_empty_cache_list_is_a_valid_hit() -> None:
    cache = AsyncMock()
    cache.get.return_value = []
    app.state.cache = cache
    qdrant = AsyncMock()
    with patch("app.routers.eonet.get_qdrant_client", AsyncMock(return_value=qdrant)):
        response = TestClient(app).get("/api/eonet/events")
    assert response.status_code == 200
    assert response.json() == []
    qdrant.scroll.assert_not_called()


@pytest.mark.asyncio
async def test_eonet_wrong_cache_root_is_deleted_and_refreshed() -> None:
    cache = AsyncMock()
    cache.get.return_value = {"unexpected": "root"}
    app.state.cache = cache
    qdrant = AsyncMock()
    qdrant.scroll.return_value = ([], None)
    with patch("app.routers.eonet.get_qdrant_client", AsyncMock(return_value=qdrant)):
        response = TestClient(app).get("/api/eonet/events")
    assert response.status_code == 200
    assert response.json() == []
    cache.delete.assert_awaited_once_with("eonet:events:168h")
    cache.set.assert_awaited_once()
