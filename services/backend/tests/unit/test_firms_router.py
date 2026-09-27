"""Tests for the FIRMS hotspots router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_point(
    pid: str, lat: float, lon: float, frp: float, country_iso3: str | None = None,
) -> object:
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
            "fetch_area": "ukraine",
            "country_iso3": country_iso3,
            "ingested_epoch": 1744300000.0,
        }

    return P()


@pytest.mark.asyncio
async def test_firms_hotspots_happy_path() -> None:
    """Three Qdrant points → three JSON hotspots with all fields mapped."""
    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.return_value = (
        [
            _make_point("id-a", 48.1, 37.8, 92.0, country_iso3="UKR"),
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
        resp = client.get("/api/firms/hotspots")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert body[0]["id"] == "id-a"
    assert body[0]["country_iso3"] == "UKR"
    assert body[1]["country_iso3"] is None
    # Fetch boxes are not places; the unreachable explosion flag is gone.
    for hotspot in body:
        assert "bbox_name" not in hotspot
        assert "fetch_area" not in hotspot
        assert "possible_explosion" not in hotspot
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
        resp = client.get("/api/firms/hotspots")

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
        resp = client.get("/api/firms/hotspots")

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "cached-a"
    mock_qdrant.scroll.assert_not_called()


def test_firms_hotspots_since_hours_too_low_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/firms/hotspots?since_hours=0")
    assert resp.status_code == 422


def test_firms_hotspots_since_hours_too_high_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/firms/hotspots?since_hours=169")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_firms_hotspots_legacy_payload_has_no_country() -> None:
    """Points written before country resolution carry only the fetch-box name."""

    class Legacy:
        id = "legacy"
        payload = {
            "source": "firms", "latitude": 47.2, "longitude": 39.7, "frp": 5.0,
            "brightness": 330.0, "confidence": "n", "acq_date": "2026-04-11",
            "acq_time": "0100", "satellite": "N", "bbox_name": "ukraine",
            "possible_explosion": False,
        }

    mock_qdrant = AsyncMock()
    mock_qdrant.scroll.return_value = ([Legacy()], None)
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=mock_qdrant)):
        resp = TestClient(app).get("/api/firms/hotspots")

    assert resp.status_code == 200
    assert resp.json()[0]["country_iso3"] is None


@pytest.mark.asyncio
async def test_firms_cache_rows_are_isolated_and_repaired() -> None:
    good = {
        "id": "cached-good", "latitude": 48.1, "longitude": 37.8,
        "frp": 10.0, "brightness": 350.0, "confidence": "n",
        "acq_date": "2026-04-11", "acq_time": "1200", "satellite": "N",
        "firms_map_url": "https://example.test/map",
    }
    mock_cache = AsyncMock()
    mock_cache.get.return_value = [
        good, None, {**good, "id": "bad", "latitude": 1000},
        {**good, "id": "nonfinite", "frp": float("nan")},
    ]
    app.state.cache = mock_cache
    qdrant = AsyncMock()

    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=qdrant)):
        response = TestClient(app).get("/api/firms/hotspots")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["cached-good"]
    mock_cache.set.assert_awaited_once()
    qdrant.scroll.assert_not_called()


@pytest.mark.asyncio
async def test_firms_bad_cache_root_recovers_and_empty_list_is_a_hit() -> None:
    cache = AsyncMock()
    cache.get.return_value = {"not": "a row list"}
    app.state.cache = cache
    qdrant = AsyncMock()
    qdrant.scroll.return_value = ([], None)

    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=qdrant)):
        response = TestClient(app).get("/api/firms/hotspots")

    assert response.status_code == 200
    assert response.json() == []
    cache.delete.assert_awaited_once_with("firms:hotspots:24h")
    cache.set.assert_awaited_once()
    qdrant.scroll.assert_awaited_once()

    cache.reset_mock()
    cache.get.return_value = []
    qdrant.reset_mock()
    with patch("app.routers.firms.get_qdrant_client", AsyncMock(return_value=qdrant)):
        response = TestClient(app).get("/api/firms/hotspots")
    assert response.status_code == 200
    assert response.json() == []
    qdrant.scroll.assert_not_called()
