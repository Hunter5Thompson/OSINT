"""D01: AIS speed/course sentinels become null (unknown), never a fake value."""

import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.vessel import Vessel
from app.services.vessel_service import (
    get_vessels,
    vessel_from_ais_message,
)

NAN = float("nan")
INF = float("inf")


def _ais(sog: object, cog: object) -> dict[str, object]:
    position: dict[str, object] = {"Latitude": 60.1, "Longitude": 24.9}
    if sog is not ...:
        position["Sog"] = sog
    if cog is not ...:
        position["Cog"] = cog
    return {
        "MetaData": {"MMSI": 1, "ShipName": "X", "ShipType": 70},
        "Message": {"PositionReport": position},
    }


@pytest.mark.parametrize(
    ("sog", "expected"),
    [
        (102.3, None),  # AIS "not available"
        (150, None),
        (-1, None),
        (NAN, None),
        (INF, None),
        (..., None),  # missing
        (None, None),
        (True, None),
        ("fast", None),
        (0, 0.0),  # real standstill
        (0.0, 0.0),
        (12.5, 12.5),
        (102.2, 102.2),  # saturation value, valid
    ],
)
def test_aisstream_speed(sog: object, expected: float | None) -> None:
    vessel = vessel_from_ais_message(_ais(sog, 90))
    assert vessel is not None
    assert vessel.speed_knots == expected


@pytest.mark.parametrize(
    ("cog", "expected"),
    [
        (360, None),  # AIS "not available"
        (360.0, None),
        (400, None),
        (-0.1, None),
        (NAN, None),
        (-INF, None),
        (..., None),
        (None, None),
        (False, None),
        (0, 0.0),  # due north is a real course
        (359.9, 359.9),
        (90, 90.0),
    ],
)
def test_aisstream_course(cog: object, expected: float | None) -> None:
    vessel = vessel_from_ais_message(_ais(5, cog))
    assert vessel is not None
    assert vessel.course == expected


def test_position_survives_unknown_measurements() -> None:
    vessel = vessel_from_ais_message(_ais(102.3, 360))
    assert vessel is not None
    assert (vessel.latitude, vessel.longitude) == (60.1, 24.9)
    assert vessel.speed_knots is None
    assert vessel.course is None


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


@pytest.mark.asyncio
async def test_digitraffic_sentinels_become_null() -> None:
    now_ms = int(time.time() * 1000)

    def feat(mmsi: int, sog: object, cog: object) -> dict[str, object]:
        return {
            "properties": {"mmsi": mmsi, "sog": sog, "cog": cog, "timestampExternal": now_ms},
            "geometry": {"coordinates": [24.9, 60.1]},
        }

    locations = {
        "features": [
            feat(1, 102.3, 360),
            feat(2, 0, 0),
            feat(3, 102.2, 359.9),
            feat(4, None, None),
            feat(5, -3, 400),
        ]
    }
    proxy = AsyncMock()
    proxy.client.get = AsyncMock(side_effect=[_Response(locations), _Response([])])
    cache = AsyncMock()
    cache.get.return_value = None

    vessels = {v.mmsi: v for v in await get_vessels(proxy, cache)}

    assert (vessels[1].speed_knots, vessels[1].course) == (None, None)
    assert (vessels[2].speed_knots, vessels[2].course) == (0.0, 0.0)
    assert (vessels[3].speed_knots, vessels[3].course) == (102.2, 359.9)
    assert (vessels[4].speed_knots, vessels[4].course) == (None, None)
    assert (vessels[5].speed_knots, vessels[5].course) == (None, None)


@pytest.mark.asyncio
async def test_old_cache_rows_are_renormalized() -> None:
    rows = [
        {"mmsi": 1, "latitude": 1.0, "longitude": 2.0, "speed_knots": 102.3, "course": 360.0},
        {"mmsi": 2, "latitude": 1.0, "longitude": 2.0, "speed_knots": 0.0, "course": 0.0},
        {"mmsi": 3, "latitude": 1.0, "longitude": 2.0, "speed_knots": 7.5, "course": 359.9},
        {"mmsi": 4, "latitude": 1.0, "longitude": 2.0},
        {"mmsi": 5, "latitude": 1.0, "longitude": 2.0, "speed_knots": None, "course": None},
    ]
    proxy = AsyncMock()
    proxy.client.get = AsyncMock(side_effect=AssertionError("cache should serve"))
    cache = AsyncMock()
    cache.get.return_value = rows

    vessels = {v.mmsi: v for v in await get_vessels(proxy, cache)}

    assert (vessels[1].speed_knots, vessels[1].course) == (None, None)
    assert (vessels[2].speed_knots, vessels[2].course) == (0.0, 0.0)
    assert (vessels[3].speed_knots, vessels[3].course) == (7.5, 359.9)
    assert (vessels[4].speed_knots, vessels[4].course) == (None, None)
    assert (vessels[5].speed_knots, vessels[5].course) == (None, None)


def test_model_default_is_unknown_and_json_has_null() -> None:
    vessel = Vessel(mmsi=1, latitude=1, longitude=2)
    assert vessel.speed_knots is None
    assert vessel.course is None
    dumped = json.loads(vessel.model_dump_json())
    assert dumped["speed_knots"] is None
    assert dumped["course"] is None


def test_api_json_contains_null() -> None:
    proxy = AsyncMock()
    cache = AsyncMock()
    cache.get.return_value = [
        {"mmsi": 1, "latitude": 1.0, "longitude": 2.0, "speed_knots": 102.3, "course": 360.0},
        {"mmsi": 2, "latitude": 1.0, "longitude": 2.0, "speed_knots": 0.0, "course": 0.0},
    ]
    app.state.proxy = proxy
    app.state.cache = cache

    body = TestClient(app).get("/api/vessels").json()

    by_mmsi = {item["mmsi"]: item for item in body}
    assert by_mmsi[1]["speed_knots"] is None and by_mmsi[1]["course"] is None
    assert by_mmsi[2]["speed_knots"] == 0.0 and by_mmsi[2]["course"] == 0.0
