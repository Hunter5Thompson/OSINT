"""AIS parsing, empty-cache fallback, and snapshot age."""

import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.vessel import Vessel
from app.services.vessel_service import (
    CACHE_TTL,
    VESSEL_MAX_AGE_S,
    collect_ais_positions,
    get_vessels,
    merge_vessel_snapshot,
    publish_vessel_snapshot,
    vessel_from_ais_message,
)


def _message(
    mmsi: int,
    *,
    name: object = "BALTIC",
    lat: object = 60.1,
    lon: object = 24.9,
    include_lat: bool = True,
) -> str:
    position: dict[str, object] = {"Sog": 10, "Cog": 90}
    if include_lat:
        position["Latitude"] = lat
    if lon is not None:
        position["Longitude"] = lon
    return json.dumps(
        {
            "MetaData": {"MMSI": mmsi, "ShipName": name, "ShipType": 70},
            "Message": {"PositionReport": position},
        }
    )


def test_ais_message_edges() -> None:
    kept = vessel_from_ais_message(json.loads(_message(111, name=None)))
    assert kept is not None
    assert kept.name is None
    assert kept.mmsi == 111

    assert vessel_from_ais_message(json.loads(_message(222, lat=0, lon=0))) is None
    assert vessel_from_ais_message(json.loads(_message(333, include_lat=False))) is None

    equator = vessel_from_ais_message(json.loads(_message(444, lat=0, lon=10)))
    assert equator is not None
    assert (equator.latitude, equator.longitude) == (0.0, 10.0)


def test_merge_keeps_the_max_age_boundary_and_drops_older() -> None:
    now = 1_000_000.0
    fresh = Vessel(mmsi=1, latitude=1, longitude=2)
    stale = Vessel(mmsi=2, latitude=3, longitude=4)
    accumulated = {
        1: (fresh, now - VESSEL_MAX_AGE_S),
        2: (stale, now - VESSEL_MAX_AGE_S - 0.01),
    }

    vessels = merge_vessel_snapshot(accumulated, [], now=now)

    assert [item.mmsi for item in vessels] == [1]


@pytest.mark.asyncio
async def test_empty_snapshot_deletes_the_cache_key() -> None:
    cache = AsyncMock()

    await publish_vessel_snapshot(cache, [])

    cache.delete.assert_awaited_once()
    cache.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_cache_falls_through_to_digitraffic() -> None:
    now_ms = int(time.time() * 1000)
    locations = {
        "features": [
            {
                "properties": {"mmsi": 111, "sog": 5, "cog": 10, "timestampExternal": now_ms},
                "geometry": {"coordinates": [24.9, 60.1]},
            },
            {
                "properties": {"mmsi": 222, "sog": 1, "cog": 1, "timestampExternal": now_ms},
                "geometry": {"coordinates": []},
            },
            {
                "properties": {"mmsi": 333, "sog": 2, "cog": 3, "timestampExternal": now_ms},
                "geometry": {"coordinates": [24.0, 95.0]},
            },
            {
                "properties": {"mmsi": 444, "sog": 4, "cog": 5, "timestampExternal": now_ms},
                "geometry": {"coordinates": [25.0, 60.2]},
            },
        ]
    }
    metadata = [
        {"mmsi": 111, "name": "GOOD", "shipType": 70, "destination": "HEL"},
        {"mmsi": 444, "name": None, "shipType": 70, "destination": None},
    ]

    class _Response:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    proxy = AsyncMock()
    proxy.client.get = AsyncMock(side_effect=[_Response(locations), _Response(metadata)])
    cache = AsyncMock()
    cache.get.return_value = []

    vessels = await get_vessels(proxy, cache)

    assert [(item.mmsi, item.name) for item in vessels] == [(111, "GOOD"), (444, None)]
    cache.set.assert_awaited()
    assert cache.set.await_args.args[2] == CACHE_TTL


@pytest.mark.asyncio
async def test_cached_vessels_skip_digitraffic() -> None:
    cached = Vessel(mmsi=7, latitude=1.5, longitude=2.5).model_dump(mode="json")
    proxy = AsyncMock()
    proxy.client.get = AsyncMock(side_effect=AssertionError("digitraffic should not run"))
    cache = AsyncMock()
    cache.get.return_value = [cached, {"mmsi": "nope"}]

    vessels = await get_vessels(proxy, cache)

    assert [item.mmsi for item in vessels] == [7]


@pytest.mark.asyncio
async def test_digitraffic_transport_failure_propagates() -> None:
    proxy = AsyncMock()
    proxy.client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    cache = AsyncMock()
    cache.get.return_value = None

    with pytest.raises(httpx.ConnectError):
        await get_vessels(proxy, cache)


def test_vessels_router_maps_upstream_failure_to_502() -> None:
    proxy = AsyncMock()
    proxy.client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    cache = AsyncMock()
    cache.get.return_value = None
    app.state.proxy = proxy
    app.state.cache = cache

    response = TestClient(app).get("/api/vessels")

    assert response.status_code == 502
    assert response.json()["code"] == "VESSEL_FETCH_ERROR"


@pytest.mark.asyncio
async def test_collect_ignores_bad_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [
        _message(111, name=None),
        _message(222, lat=0, lon=0),
        _message(333, include_lat=False),
        "not-json",
        _message(444, name="BALTIC", lat=0, lon=10),
    ]

    class _Socket:
        def __init__(self) -> None:
            self._pending = list(messages)

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self) -> "_Socket":
            return self

        async def __anext__(self) -> str:
            if not self._pending:
                raise StopAsyncIteration
            return self._pending.pop(0)

    class _Connect:
        async def __aenter__(self) -> _Socket:
            return _Socket()

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(settings, "aisstream_api_key", "test-key")
    monkeypatch.setattr("websockets.connect", lambda *_args, **_kwargs: _Connect())

    vessels = await collect_ais_positions(window_s=5)

    assert sorted(item.mmsi for item in vessels) == [111, 444]


@pytest.mark.asyncio
async def test_collect_without_api_key_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "aisstream_api_key", "")

    assert await collect_ais_positions(window_s=1) == []
