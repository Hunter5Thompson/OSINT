"""Flight parsers keep one bad aircraft from blanking the globe."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.flight import Aircraft
from app.services.flight_service import _is_military_callsign, get_flights


def _opensky_state(
    icao: str,
    callsign: str,
    lon: float,
    lat: float,
    *,
    short: bool = False,
) -> list[object]:
    row: list[object] = [
        icao,
        callsign,
        "DE",
        1_700_000_000,
        1_700_000_000,
        lon,
        lat,
        1000.0,
        False,
        200.0,
        90.0,
        1.0,
        None,
        None,
        None,
        0,
        0,
    ]
    return row[:7] if short else row


@pytest.mark.parametrize(
    ("callsign", "military"),
    [
        ("RCH123", True),
        ("REACH90", True),
        (" rrr1001 ", True),
        ("HAWK12", True),
        ("HAWKER", False),
        ("VIPER12", True),
        ("VIPERX", False),
        ("DLH400", False),
        (None, False),
        ("", False),
    ],
)
def test_military_callsign_requires_a_numeric_suffix(callsign: str | None, military: bool) -> None:
    assert _is_military_callsign(callsign) is military


@pytest.mark.asyncio
async def test_adsb_ground_and_null_callsign_do_not_drop_the_feed() -> None:
    proxy = AsyncMock()
    proxy.get_json.return_value = {
        "ac": [
            {
                "hex": "aaa111",
                "flight": None,
                "lat": 50.0,
                "lon": 8.0,
                "alt_baro": "ground",
                "gs": 0,
                "track": 0,
                "dbFlags": 0,
            },
            {
                "hex": "bbb222",
                "flight": "DLH400",
                "lat": 50.1,
                "lon": 8.1,
                "alt_baro": 35000,
                "gs": 400,
                "track": 180,
                "dbFlags": 0,
            },
        ]
    }
    cache = AsyncMock()
    cache.get.return_value = None

    aircraft = await get_flights(proxy, cache)

    assert proxy.get_json.await_count == 1
    assert [(item.icao24, item.on_ground, item.callsign) for item in aircraft] == [
        ("aaa111", True, None),
        ("bbb222", False, "DLH400"),
    ]
    assert aircraft[0].altitude_m == 0


@pytest.mark.asyncio
async def test_adsb_military_flag_or_callsign() -> None:
    proxy = AsyncMock()
    proxy.get_json.return_value = {
        "ac": [
            {
                "hex": "abc123",
                "flight": "RCH442",
                "lat": 48.0,
                "lon": 11.0,
                "alt_baro": 10000,
                "dbFlags": 0,
            },
            {
                "hex": "def456",
                "flight": "DLH1",
                "lat": 49.0,
                "lon": 12.0,
                "alt_baro": 10000,
                "dbFlags": 1,
            },
        ]
    }
    cache = AsyncMock()
    cache.get.return_value = None

    aircraft = await get_flights(proxy, cache)

    assert [item.is_military for item in aircraft] == [True, True]


@pytest.mark.asyncio
async def test_short_opensky_row_does_not_drop_the_rest_and_hawker_is_civil() -> None:
    proxy = AsyncMock()
    proxy.get_json.side_effect = [
        {"ac": []},
        {
            "states": [
                _opensky_state("short1", "HAWKER", 8.0, 50.0, short=True),
                _opensky_state("full01", "HAWKER", 8.2, 50.2),
                _opensky_state("full02", "GAF6801", 8.3, 50.3),
            ]
        },
    ]
    cache = AsyncMock()
    cache.get.return_value = None

    aircraft = await get_flights(proxy, cache)

    assert [(item.icao24, item.is_military) for item in aircraft] == [
        ("full01", False),
        ("full02", True),
    ]


@pytest.mark.asyncio
async def test_empty_flight_cache_is_a_miss() -> None:
    proxy = AsyncMock()
    proxy.get_json.return_value = {
        "ac": [{"hex": "abc123", "flight": "DLH1", "lat": 50.0, "lon": 8.0, "alt_baro": 1000}]
    }
    cache = AsyncMock()
    cache.get.return_value = []

    aircraft = await get_flights(proxy, cache)

    assert [item.icao24 for item in aircraft] == ["abc123"]


@pytest.mark.asyncio
async def test_every_flight_source_down_raises() -> None:
    proxy = AsyncMock()
    proxy.get_json.side_effect = httpx.ConnectError("down")
    proxy.client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    cache = AsyncMock()
    cache.get.return_value = None

    with pytest.raises(httpx.ConnectError):
        await get_flights(proxy, cache)


def test_flights_router_maps_total_upstream_failure_to_502() -> None:
    proxy = AsyncMock()
    proxy.get_json.side_effect = httpx.ConnectError("down")
    proxy.client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    cache = AsyncMock()
    cache.get.return_value = None
    app.state.proxy = proxy
    app.state.cache = cache

    response = TestClient(app).get("/api/flights")

    assert response.status_code == 502
    assert response.json()["code"] == "UPSTREAM_TIMEOUT"


def test_military_route_filters_on_the_parsed_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = [
        Aircraft(icao24="mil", latitude=1, longitude=2, is_military=True),
        Aircraft(icao24="civ", latitude=3, longitude=4, is_military=False),
    ]
    monkeypatch.setattr(
        "app.routers.flights.flight_service.get_flights",
        AsyncMock(return_value=sample),
    )

    response = TestClient(app).get("/api/flights/military")

    assert response.status_code == 200
    assert [item["icao24"] for item in response.json()] == ["mil"]
