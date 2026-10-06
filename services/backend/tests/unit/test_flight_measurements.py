"""D02: missing flight measurements are null (unknown), never invented."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.flight import Aircraft
from app.services.flight_service import (
    _parse_adsb_aircraft,
    _parse_fr24_row,
    _parse_opensky_state,
    get_flights,
)

NAN = float("nan")
INF = float("inf")
FT = 0.3048


def _adsb(**fields: object) -> dict[str, object]:
    row: dict[str, object] = {"hex": "abc123", "lat": 50.0, "lon": 8.0}
    row.update(fields)
    return row


def _opensky(**over: object) -> list[object]:
    row: list[object] = [
        "abc123", "TEST1", "DE", 1_700_000_000, 1_700_000_100, 8.0, 50.0,
        1000.0, False, 200.0, 90.0, 1.5, None, 1200.0, None, 0, 0,
    ]  # fmt: skip
    for key, value in over.items():
        row[int(key[1:])] = value
    return row


def _fr24(**over: object) -> list[object]:
    row: list[object] = [
        "abc123", 50.0, 8.0, 270, 35000, 450, "1000", "F-X", "B738", "D-ABCD",
        1_700_000_000, "FRA", "LHR", "LH1", 0, 0, "DLH1",
    ]  # fmt: skip
    for key, value in over.items():
        row[int(key[1:])] = value
    return row


# ---- adsb.fi ---------------------------------------------------------------
def test_adsb_missing_measurements_are_none() -> None:
    ac = _parse_adsb_aircraft(_adsb())
    assert ac is not None
    assert ac.altitude_m is None
    assert ac.velocity_ms is None
    assert ac.heading is None
    assert ac.vertical_rate is None
    assert ac.last_contact is None
    assert ac.on_ground is False


def test_adsb_real_zero_course_and_speed_kept() -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=0, gs=0, track=0, baro_rate=0))
    assert ac is not None
    assert (ac.altitude_m, ac.velocity_ms, ac.heading, ac.vertical_rate) == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize("sentinel", ["ground", "Ground", "GROUND", " ground "])
def test_adsb_ground_sentinel_case_insensitive(sentinel: str) -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=sentinel))
    assert ac is not None
    assert ac.on_ground is True
    assert ac.altitude_m == 0.0


@pytest.mark.parametrize("not_ground", [0, 35000, None, ["ground"], True])
def test_adsb_only_strings_are_ground(not_ground: object) -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=not_ground))
    assert ac is not None
    assert ac.on_ground is False


@pytest.mark.parametrize("baro", [None, "", "n/a", NAN])
def test_adsb_null_baro_falls_back_to_geom(baro: object) -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=baro, alt_geom=35000))
    assert ac is not None
    assert ac.altitude_m == pytest.approx(35000 * FT)
    assert ac.on_ground is False


def test_adsb_missing_baro_falls_back_to_geom() -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_geom=35000))
    assert ac is not None
    assert ac.altitude_m == pytest.approx(35000 * FT)


def test_adsb_baro_zero_wins_over_nonzero_geom() -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=0, alt_geom=500))
    assert ac is not None
    assert ac.altitude_m == 0.0


def test_adsb_no_usable_altitude_stays_unknown() -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=None, alt_geom=None))
    assert ac is not None
    assert ac.altitude_m is None


@pytest.mark.parametrize("bad", [NAN, INF, -INF, "x", True])
def test_adsb_nonfinite_measurements_become_none_and_keep_position(bad: object) -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=bad, gs=bad, track=bad, baro_rate=bad))
    assert ac is not None
    assert (ac.latitude, ac.longitude) == (50.0, 8.0)
    assert ac.altitude_m is None
    assert ac.velocity_ms is None
    assert ac.heading is None
    assert ac.vertical_rate is None


def test_adsb_normal_values_converted() -> None:
    ac = _parse_adsb_aircraft(_adsb(alt_baro=10000, gs=100, track=359.5, baro_rate=1000))
    assert ac is not None
    assert ac.altitude_m == pytest.approx(10000 * FT)
    assert ac.velocity_ms == pytest.approx(100 * 0.5144)
    assert ac.heading == 359.5
    assert ac.vertical_rate == pytest.approx(1000 * 0.00508)


# ---- OpenSky ---------------------------------------------------------------
def test_opensky_none_course_and_contact_are_none_not_1970() -> None:
    ac = _parse_opensky_state(_opensky(i4=None, i10=None, i11=None, i9=None))
    assert ac is not None
    assert ac.last_contact is None
    assert ac.heading is None
    assert ac.vertical_rate is None
    assert ac.velocity_ms is None


def test_opensky_real_zero_course_kept() -> None:
    ac = _parse_opensky_state(_opensky(i10=0.0, i9=0.0, i11=0.0))
    assert ac is not None
    assert (ac.heading, ac.velocity_ms, ac.vertical_rate) == (0.0, 0.0, 0.0)


def test_opensky_contact_comes_from_last_contact_field_only() -> None:
    ac = _parse_opensky_state(_opensky(i3=1_600_000_000, i4=1_700_000_100))
    assert ac is not None
    assert ac.last_contact == datetime.fromtimestamp(1_700_000_100, tz=UTC)
    # time_position (index 3) must never replace a missing last_contact
    ac = _parse_opensky_state(_opensky(i3=1_600_000_000, i4=None))
    assert ac is not None
    assert ac.last_contact is None


@pytest.mark.parametrize("bad", [NAN, INF, "x", True, 10**30])
def test_opensky_invalid_contact_is_none_and_row_kept(bad: object) -> None:
    ac = _parse_opensky_state(_opensky(i4=bad))
    assert ac is not None
    assert ac.last_contact is None
    assert ac.latitude == 50.0


def test_opensky_null_baro_uses_geo_altitude_and_unknown_when_both_null() -> None:
    ac = _parse_opensky_state(_opensky(i7=None, i13=1200.0))
    assert ac is not None
    assert ac.altitude_m == 1200.0
    ac = _parse_opensky_state(_opensky(i7=None, i13=None))
    assert ac is not None
    assert ac.altitude_m is None
    ac = _parse_opensky_state(_opensky(i7=0.0, i13=900.0))
    assert ac is not None
    assert ac.altitude_m == 0.0


def test_opensky_nonfinite_values_become_none() -> None:
    ac = _parse_opensky_state(_opensky(i7=NAN, i9=INF, i10=NAN, i11=-INF, i13=None))
    assert ac is not None
    assert ac.altitude_m is None
    assert ac.velocity_ms is None
    assert ac.heading is None
    assert ac.vertical_rate is None


# ---- FR24 ------------------------------------------------------------------
def test_fr24_has_no_vertical_rate_and_no_invented_contact() -> None:
    ac = _parse_fr24_row(_fr24())
    assert ac is not None
    assert ac.vertical_rate is None
    assert ac.last_contact is None
    assert ac.heading == 270.0
    assert ac.altitude_m == pytest.approx(35000 * FT)


def test_fr24_missing_measurements_and_ground_case() -> None:
    ac = _parse_fr24_row(_fr24(i3=None, i4=None, i5=None))
    assert ac is not None
    assert (ac.heading, ac.altitude_m, ac.velocity_ms) == (None, None, None)
    ac = _parse_fr24_row(_fr24(i4="Ground", i3=0, i5=0))
    assert ac is not None
    assert ac.on_ground is True
    assert (ac.altitude_m, ac.heading, ac.velocity_ms) == (0.0, 0.0, 0.0)


def test_fr24_nonfinite_become_none() -> None:
    ac = _parse_fr24_row(_fr24(i3=NAN, i4=INF, i5=-INF))
    assert ac is not None
    assert (ac.heading, ac.altitude_m, ac.velocity_ms) == (None, None, None)


# ---- model / cache / API contract -----------------------------------------
def test_model_defaults_are_unknown_not_zero_or_now() -> None:
    ac = Aircraft(icao24="x", latitude=1, longitude=2)
    assert ac.altitude_m is None
    assert ac.velocity_ms is None
    assert ac.heading is None
    assert ac.vertical_rate is None
    assert ac.last_contact is None
    dumped = json.loads(ac.model_dump_json())
    for key in ("altitude_m", "velocity_ms", "heading", "vertical_rate", "last_contact"):
        assert dumped[key] is None


@pytest.mark.asyncio
async def test_cache_round_trip_keeps_null_and_zero() -> None:
    rows = [
        Aircraft(icao24="a", latitude=1, longitude=2).model_dump(mode="json"),
        Aircraft(
            icao24="b", latitude=1, longitude=2, heading=0.0, altitude_m=0.0
        ).model_dump(mode="json"),
    ]
    cache = AsyncMock()
    cache.get.return_value = rows

    flights = {a.icao24: a for a in await get_flights(AsyncMock(), cache)}

    assert flights["a"].heading is None and flights["a"].last_contact is None
    assert flights["b"].heading == 0.0 and flights["b"].altitude_m == 0.0


def test_api_json_contains_null() -> None:
    cache = AsyncMock()
    cache.get.return_value = [Aircraft(icao24="a", latitude=1, longitude=2).model_dump(mode="json")]
    app.state.proxy = AsyncMock()
    app.state.cache = cache

    body = TestClient(app).get("/api/flights").json()

    assert body[0]["heading"] is None
    assert body[0]["altitude_m"] is None
    assert body[0]["last_contact"] is None
