"""One bad USGS feature must not erase the rest of the week."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.earthquake_service import get_earthquakes

_NOW_MS = 1_700_000_000_000


def _feature(
    feature_id: str,
    *,
    coords: object = (13.4, 52.5, 10),
    mag: object = 5.1,
    when: object = _NOW_MS,
    tsunami: object = 0,
    place: str = "Berlin",
    geometry: object | None = None,
) -> dict[str, object]:
    if geometry is None and coords is not None:
        coordinates = list(coords) if isinstance(coords, tuple) else coords
        geometry = {"type": "Point", "coordinates": coordinates}
    return {
        "id": feature_id,
        "geometry": geometry,
        "properties": {
            "mag": mag,
            "time": when,
            "tsunami": tsunami,
            "place": place,
            "url": f"https://example.test/{feature_id}",
        },
    }


@pytest.mark.asyncio
async def test_bad_features_are_skipped_and_missing_coords_are_not_invented() -> None:
    proxy = AsyncMock()
    proxy.get_json.return_value = {
        "features": [
            _feature("eq-good"),
            _feature("eq-null-geometry", geometry=None, coords=None),
            _feature("eq-short", coords=[10.0]),
            _feature("eq-null-mag", mag=None),
            _feature("eq-flag", coords=(11.0, 48.0, 5), mag=4.8, tsunami="0", place="Bavaria"),
        ]
    }
    cache = AsyncMock()
    cache.get.return_value = None

    quakes = await get_earthquakes(proxy, cache)

    assert [item.id for item in quakes] == ["eq-good", "eq-flag"]
    assert quakes[1].tsunami is False
    assert all((item.latitude, item.longitude) != (0.0, 0.0) for item in quakes)


@pytest.mark.asyncio
async def test_usgs_string_tsunami_flag() -> None:
    proxy = AsyncMock()
    proxy.get_json.return_value = {"features": [_feature("eq-wave", tsunami="1")]}
    cache = AsyncMock()
    cache.get.return_value = None

    quakes = await get_earthquakes(proxy, cache)

    assert quakes[0].tsunami is True


@pytest.mark.asyncio
async def test_usgs_transport_failure_propagates() -> None:
    proxy = AsyncMock()
    proxy.get_json.side_effect = httpx.ConnectError("down")
    cache = AsyncMock()
    cache.get.return_value = []

    with pytest.raises(httpx.ConnectError):
        await get_earthquakes(proxy, cache)


def test_earthquakes_router_maps_upstream_failure_to_502() -> None:
    proxy = AsyncMock()
    proxy.get_json.side_effect = httpx.ConnectError("down")
    cache = AsyncMock()
    cache.get.return_value = None
    app.state.proxy = proxy
    app.state.cache = cache

    response = TestClient(app).get("/api/earthquakes")

    assert response.status_code == 502
    assert response.json()["code"] == "UPSTREAM_TIMEOUT"
