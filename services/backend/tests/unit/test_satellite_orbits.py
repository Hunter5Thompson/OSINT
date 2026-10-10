"""Behavioral contract for the compatible, versioned GP orbit API."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.main import app
from app.services import satellite_orbit_service, satellite_service

FIXTURES = Path(__file__).resolve().parents[4] / "tests/fixtures/satellites"
GP = json.loads((FIXTURES / "celestrak-100651.json").read_text())
ORBIT_CACHE_KEY = "satellites:orbits:v1"


async def _request(payload: object, monkeypatch: pytest.MonkeyPatch) -> httpx.Response:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["active"])
    app.state.proxy.get_json = AsyncMock(return_value=payload)
    app.state.cache.get.return_value = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/api/satellites/orbits")


async def test_six_digit_gp_api_preserves_elements_and_cache_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _request([GP], monkeypatch)
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    satellite = body["satellites"][0]
    assert satellite["norad_id"] == 100651
    assert satellite["orbit"]["format"] == "omm"
    elements = satellite["orbit"]["elements"]
    assert elements["NORAD_CAT_ID"] == GP["NORAD_CAT_ID"]
    assert elements["EPOCH"] == GP["EPOCH"] + "Z"
    assert elements["INCLINATION"] == GP["INCLINATION"]
    assert satellite["period_min"] == pytest.approx(1440 / GP["MEAN_MOTION"], abs=0.005)
    assert elements["REF_FRAME"] == "TEME"
    assert elements["TIME_SYSTEM"] == "UTC"
    assert elements["CENTER_NAME"] == "EARTH"
    assert elements["MEAN_ELEMENT_THEORY"] == "SGP4"
    assert "tle_line1" not in satellite and "tle_line2" not in satellite
    assert body["coverage"]["completeness"] == "complete"
    assert body["fetched_at"].endswith("Z")
    assert "FORMAT=JSON" in app.state.proxy.get_json.call_args.args[0]
    app.state.cache.set.assert_awaited_once_with(ORBIT_CACHE_KEY, body, 7200)
    app.state.cache.delete.assert_not_awaited()


async def test_gp_transport_uses_explicit_service_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        satellite_orbit_service,
        "settings",
        SimpleNamespace(celestrak_gp_url="http://orbit-fixture:8000/gp.php"),
        raising=False,
    )
    response = await _request([GP], monkeypatch)
    assert response.status_code == 200
    app.state.proxy.get_json.assert_awaited_once_with(
        "http://orbit-fixture:8000/gp.php?GROUP=active&FORMAT=JSON"
    )


@pytest.mark.parametrize("catalog_id", [100651, 1234567, 999999999, "100651"])
async def test_full_supported_catalog_range(
    catalog_id: int | str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _request([{**GP, "NORAD_CAT_ID": catalog_id}], monkeypatch)
    assert response.status_code == 200
    row = response.json()["satellites"][0]
    assert row["norad_id"] == int(catalog_id)
    assert row["orbit"]["elements"]["NORAD_CAT_ID"] == int(catalog_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("NORAD_CAT_ID", 0),
        ("NORAD_CAT_ID", True),
        ("NORAD_CAT_ID", 100651.5),
        ("NORAD_CAT_ID", 1000000000),
        ("EPOCH", "not-a-date"),
        ("EPOCH", "2026-10-09"),
        ("EPOCH", "2026-10-09T05"),
        ("EPOCH", "2026-10-09T05:27:38.1513609"),
        ("MEAN_MOTION", 0),
        ("MEAN_MOTION", "nan"),
        ("ECCENTRICITY", 1),
        ("ECCENTRICITY", -0.01),
        ("INCLINATION", 181),
        ("RA_OF_ASC_NODE", 360),
        ("MEAN_ANOMALY", -1),
        ("BSTAR", "inf"),
        ("MEAN_MOTION", 5e-324),
        pytest.param("NORAD_CAT_ID", "9" * 5000, id="oversized-catalog-string"),
        ("REV_AT_EPOCH", -1),
        ("CLASSIFICATION_TYPE", "banana"),
    ],
)
async def test_invalid_neighbor_is_isolated_and_counted(
    field: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = {**GP, field: value}
    response = await _request([GP, bad], monkeypatch)
    assert response.status_code == 200
    body = response.json()
    assert [row["norad_id"] for row in body["satellites"]] == [100651]
    assert body["coverage"]["completeness"] == "partial"
    group = body["coverage"]["groups"][0]
    assert group["accepted_records"] == 1
    assert group["rejected_invalid"] == 1
    assert group["rejections"][0]["index"] == 1
    assert group["rejections"][0]["code"] == "invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("REF_FRAME", "J2000"),
        ("TIME_SYSTEM", "TAI"),
        ("CENTER_NAME", "MARS"),
        ("MEAN_ELEMENT_THEORY", "SGP4-XP"),
        ("EPHEMERIS_TYPE", 4),
    ],
)
async def test_unsupported_physics_are_reported_separately(
    field: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _request([GP, {**GP, field: value}], monkeypatch)
    assert response.status_code == 200
    group = response.json()["coverage"]["groups"][0]
    assert group["rejected_unsupported"] == 1
    assert group["rejected_invalid"] == 0


@pytest.mark.parametrize(
    "payload", [[{**GP, "MEAN_MOTION": 0}], {"error": "unavailable"}, "error page"]
)
async def test_all_unusable_groups_are_upstream_failure(
    payload: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _request(payload, monkeypatch)
    assert response.status_code == 502
    assert response.json()["code"] == "UPSTREAM_INVALID_DATA"
    app.state.cache.set.assert_not_awaited()


async def test_valid_empty_group_is_cacheable(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _request([], monkeypatch)
    assert response.status_code == 200
    assert response.json()["satellites"] == []
    assert response.json()["coverage"]["completeness"] == "complete"
    app.state.cache.set.assert_awaited_once()


async def test_cached_empty_snapshot_keeps_its_time(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _request([], monkeypatch)
    cached = response.json()
    app.state.cache.get.return_value = cached
    app.state.proxy.get_json.reset_mock()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites/orbits")
    assert response.status_code == 200
    assert response.json() == cached
    app.state.proxy.get_json.assert_not_awaited()


async def test_deduplication_uses_newest_element_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    newer = {**GP, "EPOCH": "2026-10-09T06:27:38.151360"}
    response = await _request([GP, newer, GP], monkeypatch)
    assert response.status_code == 200
    assert len(response.json()["satellites"]) == 1
    assert response.json()["satellites"][0]["orbit"]["elements"]["EPOCH"] == newer["EPOCH"] + "Z"


async def test_all_group_transport_failures_use_error_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["active"])
    app.state.proxy.get_json = AsyncMock(side_effect=httpx.ConnectError("fixture"))
    app.state.cache.get.return_value = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites/orbits")
    assert response.status_code == 502
    assert response.json()["code"] == "UPSTREAM_TIMEOUT"
    app.state.cache.set.assert_not_awaited()


async def test_offset_epoch_is_normalized_to_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await _request([{**GP, "EPOCH": "2026-10-09T07:27:38.151360+02:00"}], monkeypatch)
    assert response.status_code == 200
    assert response.json()["satellites"][0]["orbit"]["elements"]["EPOCH"] == GP["EPOCH"] + "Z"


async def test_partial_group_failure_keeps_healthy_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations", "active"])
    app.state.proxy.get_json = AsyncMock(side_effect=[httpx.ConnectError("fixture"), [GP]])
    app.state.cache.get.return_value = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites/orbits")
    assert response.status_code == 200
    body = response.json()
    assert len(body["satellites"]) == 1
    assert body["coverage"]["completeness"] == "partial"
    assert [group["status"] for group in body["coverage"]["groups"]] == ["failed", "ok"]


async def test_cache_preserves_fetch_time_and_does_not_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _request([GP], monkeypatch)
    assert response.status_code == 200
    cached = response.json()
    cached["fetched_at"] = "2026-10-09T23:06:11.823566Z"
    app.state.cache.reset_mock()
    app.state.cache.get.return_value = cached
    app.state.proxy.get_json.reset_mock()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites/orbits")
    assert response.status_code == 200
    assert response.json() == cached
    app.state.cache.get.assert_awaited_once_with(ORBIT_CACHE_KEY)
    app.state.proxy.get_json.assert_not_awaited()
    app.state.cache.set.assert_not_awaited()


@pytest.mark.parametrize(
    "damage",
    [
        "version",
        "version_bool",
        "id",
        "epoch",
        "coverage",
        "accepted_count",
        "fetch_numeric",
    ],
)
async def test_corrupt_new_cache_is_rejected_without_touching_legacy(
    damage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _request([GP], monkeypatch)
    assert response.status_code == 200
    cached = copy.deepcopy(response.json())
    if damage == "version":
        cached["schema_version"] = 2
    elif damage == "version_bool":
        cached["schema_version"] = True
    elif damage == "id":
        cached["satellites"][0]["norad_id"] = 1
    elif damage == "epoch":
        cached["satellites"][0]["orbit"]["elements"]["EPOCH"] = "2026-10-09"
    elif damage == "accepted_count":
        cached["coverage"]["groups"][0]["accepted_records"] = 0
    elif damage == "fetch_numeric":
        cached["fetched_at"] = 1791587171
    else:
        cached["coverage"]["completeness"] = "complete"
        cached["coverage"]["groups"][0]["rejected_invalid"] = 10
    app.state.cache.get.return_value = cached
    app.state.proxy.get_json.reset_mock()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites/orbits")
    assert response.status_code == 200
    assert response.json()["satellites"][0]["norad_id"] == 100651
    app.state.proxy.get_json.assert_awaited_once()
    app.state.cache.delete.assert_not_awaited()


async def test_legacy_endpoint_response_shape_is_retained() -> None:
    app.state.cache.get.return_value = [
        {"norad_id": 25544, "name": "ISS", "tle_line1": "1 25544", "tle_line2": "2 25544"}
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert response.json()[0]["tle_line1"] == "1 25544"
    app.state.cache.get.assert_awaited_once_with("satellites:tle")


@pytest.mark.parametrize("damage", [None, "checksum", "pair_id", "catalog_id", "alpha5"])
async def test_tle_variant_preserves_valid_pair_and_rejects_bad_cache(
    damage: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _request([GP], monkeypatch)
    assert response.status_code == 200
    cached = response.json()
    _, line1, line2 = (FIXTURES / "iss-valid.tle").read_text().splitlines()
    row = cached["satellites"][0]
    row.update(
        norad_id=25544,
        name="ISS (ZARYA)",
        category="station",
        inclination_deg=51.64,
        period_min=1440 / 15.50103472,
        operator_country="INT",
        satellite_type="station",
    )
    row["orbit"] = {"format": "tle", "line1": line1, "line2": line2}
    if damage == "checksum":
        row["orbit"]["line1"] = line1[:-1] + str((int(line1[-1]) + 1) % 10)
    elif damage == "pair_id":
        row["orbit"]["line2"] = line2[:2] + "25545" + line2[7:]
    elif damage == "catalog_id":
        row["norad_id"] = 100651
    elif damage == "alpha5":
        row["orbit"]["line1"] = line1[:2] + "A5544" + line1[7:]
        row["orbit"]["line2"] = line2[:2] + "A5544" + line2[7:]
    app.state.cache.get.return_value = cached
    app.state.proxy.get_json.reset_mock()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites/orbits")
    assert response.status_code == 200
    if damage is None:
        assert response.json() == cached
        app.state.proxy.get_json.assert_not_awaited()
    else:
        assert response.json()["satellites"][0]["norad_id"] == 100651
        app.state.proxy.get_json.assert_awaited_once()
