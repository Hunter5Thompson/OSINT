"""Tests for the FIRMS hotspots router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_point(pid: str, lat: float, lon: float, frp: float, explosion: bool = False) -> object:
    class P:
        id = pid
        payload = {
            "source": "firms",
            "latitude": lat,
            "longitude": lon,
            "frp": frp,
            "brightness": 390.0,
            "confidence": "h",
            "acq_date": "2026-04-11",
            "acq_time": "1423",
            "satellite": "VIIRS_SNPP_NRT",
            "bbox_name": "ukraine",
            "possible_explosion": explosion,
            "ingested_epoch": 1744300000.0,
        }

    return P()


@pytest.mark.asyncio
async def test_firms_hotspots_happy_path() -> None:
    """Three Qdrant points → three JSON hotspots with all fields mapped."""
    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.return_value = (
        [
            _make_point("id-a", 48.1, 37.8, 92.0, explosion=True),
            _make_point("id-b", 48.2, 37.9, 45.0),
            _make_point("id-c", 31.4, 34.4, 12.0),
        ],
        None,
    )

    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/firms/hotspots")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert body[0]["id"] == "id-a"
    assert body[0]["possible_explosion"] is True
    assert body[0]["frp"] == 92.0
    assert body[0]["firms_map_url"].startswith("https://firms.modaps.eosdis.nasa.gov/map/#")
    assert "48.1000" in body[0]["firms_map_url"]
    assert "37.8000" in body[0]["firms_map_url"]


@pytest.mark.asyncio
async def test_firms_hotspots_pagination_concatenates_pages() -> None:
    """Scroll with two pages returns the concatenation."""
    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.side_effect = [
        ([_make_point("id-a", 48.1, 37.8, 50.0)], "next-token"),
        ([_make_point("id-b", 48.2, 37.9, 50.0)], None),
    ]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/firms/hotspots")

    assert resp.status_code == 200
    body = resp.json()
    assert [h["id"] for h in body] == ["id-a", "id-b"]
    assert mock_qdrant.scroll.call_count == 2


@pytest.mark.asyncio
async def test_firms_hotspots_cache_hit_short_circuits_qdrant() -> None:
    cached_payload = [{
        "id": "cached-a", "latitude": 48.1, "longitude": 37.8,
        "frp": 10.0, "brightness": 350.0, "confidence": "n",
        "acq_date": "2026-04-11", "acq_time": "1200",
        "satellite": "VIIRS_SNPP_NRT", "bbox_name": "ukraine",
        "possible_explosion": False,
        "firms_map_url": "https://firms.modaps.eosdis.nasa.gov/map/#d:2026-04-11;@37.8000,48.1000,10z",
    }]
    mock_cache = AsyncMock()
    mock_cache.get.return_value = cached_payload
    app.state.cache = mock_cache

    mock_qdrant = AsyncMock()
    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        client = TestClient(app)
        resp = client.get("/api/v1/firms/hotspots")

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "cached-a"
    mock_qdrant.scroll.assert_not_called()


def test_firms_hotspots_since_hours_too_low_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/firms/hotspots?since_hours=0")
    assert resp.status_code == 422


def test_firms_hotspots_since_hours_too_high_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/firms/hotspots?since_hours=169")
    assert resp.status_code == 422
