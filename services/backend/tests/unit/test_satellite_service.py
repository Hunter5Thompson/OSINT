"""TLE classification and group fallback."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app.orbit_elements import OrbitElementError
from app.services import satellite_service
from app.services.satellite_service import (
    _categorize,
    _detect_country,
    _detect_type,
    get_satellites,
)


def _tle(name: str, norad: int, inclination: str = "51.6400") -> str:
    # Synthetic classification fixtures, never published reference orbits.
    def checksum(line: str) -> str:
        return line[:68] + str(sum(int(c) if c.isdigit() else c == "-" for c in line[:68]) % 10)

    line1 = checksum(f"1 {norad:05d}U 98067A   24100.00000000  .00000000  00000-0  00000-0 0  9990")
    line2 = checksum(
        f"2 {norad:05d} {float(inclination):8.4f} 208.9163 0006703"
        "  35.2324  78.1456 15.49568716000000"
    )
    return f"{name}\n{line1}\n{line2}\n"


class _Proxy:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    async def get_text(self, url: str) -> str:
        self.urls.append(url)
        for key, value in self.payloads.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return str(value)
        raise httpx.ConnectError(f"unexpected {url}")


@pytest.mark.parametrize(
    ("name", "inclination", "category", "country"),
    [
        ("SWISSCUBE", 98.0, "active", None),
        ("MISSION EXTENSION", 50.0, "active", None),
        ("USA-293", 97.0, "military", "US"),
        ("USA 293", 97.0, "military", "US"),
        ("COSMOS 1408", 82.0, "military", "RU"),
        ("COSMOS 2251", 74.0, "military", "RU"),
        ("ISS (ZARYA)", 51.6, "station", "INT"),
        ("CSS (TIANHE)", 41.5, "station", None),
    ],
)
def test_name_classification_uses_tokens(
    name: str,
    inclination: float,
    category: str,
    country: str | None,
) -> None:
    assert _categorize(name, inclination) == category
    assert _detect_country(name) == country


@pytest.mark.parametrize(
    ("name", "category", "country", "satellite_type"),
    [
        ("AGPS-1", "active", None, "unknown"),
        ("USES-1", "active", None, "unknown"),
        ("SES-12", "active", None, "comms"),
        ("SES12", "active", None, "comms"),
        ("GPS III-1", "gps", "US", "gps"),
        ("QZS-1", "gps", "JP", "gps"),
        ("QZSS 2", "gps", "JP", "gps"),
        ("QZSX-1", "active", None, "unknown"),
        ("AEHF-6", "military", "US", "comms"),
        ("MUOS 5", "military", "US", "comms"),
        ("DSP-23", "military", "US", "unknown"),
        ("MILSTAR-2", "military", "US", "comms"),
        ("WGS-10", "military", "US", "comms"),
    ],
)
def test_family_tokens_and_explicit_aliases(
    name: str,
    category: str,
    country: str | None,
    satellite_type: str,
) -> None:
    assert _categorize(name, 50.0) == category
    assert _detect_country(name) == country
    assert _detect_type(name, category) == satellite_type


@pytest.mark.asyncio
async def test_error_substring_inside_a_tle_name_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations"])
    proxy = _Proxy({"GROUP=stations": _tle("TERRIER ERROR", 99991)})
    cache = AsyncMock()
    cache.get.return_value = None

    satellites = await get_satellites(proxy, cache)  # type: ignore[arg-type]

    assert [item.name for item in satellites] == ["TERRIER ERROR"]


@pytest.mark.asyncio
async def test_error_page_is_skipped_and_the_next_group_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations", "military"])
    proxy = _Proxy(
        {
            "GROUP=stations": "Error: no GP data",
            "GROUP=military": _tle("USA-293", 42999, "97.4000"),
        }
    )
    cache = AsyncMock()
    cache.get.return_value = None

    satellites = await get_satellites(proxy, cache)  # type: ignore[arg-type]

    assert len(satellites) == 1
    assert satellites[0].category == "military"
    assert satellites[0].operator_country == "US"
    assert satellites[0].satellite_type == "recon"


@pytest.mark.asyncio
async def test_active_group_is_fetched_after_a_large_targeted_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations", "active"])
    targeted = "".join(_tle(f"STARLINK-{index}", 50000 + index) for index in range(501))
    proxy = _Proxy(
        {
            "GROUP=stations": targeted,
            "GROUP=active": _tle("NOAA 20", 43013, "98.7000"),
        }
    )
    cache = AsyncMock()
    cache.get.return_value = None

    satellites = await get_satellites(proxy, cache)  # type: ignore[arg-type]

    assert any("GROUP=active" in url for url in proxy.urls)
    assert {item.norad_id for item in satellites} >= {50000, 50500, 43013}


@pytest.mark.asyncio
async def test_all_celestrak_groups_down_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations", "active"])
    proxy = _Proxy({})
    cache = AsyncMock()
    cache.get.return_value = None

    with pytest.raises(httpx.ConnectError):
        await get_satellites(proxy, cache)  # type: ignore[arg-type]


TEXT_CASES = json.loads(
    (
        Path(__file__).resolve().parents[4] / "tests/fixtures/satellites/d07-text-cases.json"
    ).read_text()
)["cases"]


@pytest.mark.parametrize("case", TEXT_CASES, ids=lambda case: case["id"])
def test_shared_text_layout_matrix(case: dict[str, object]) -> None:
    if "error" in case:
        with pytest.raises(OrbitElementError) as caught:
            satellite_service._parse_tle_text(str(case["text"]))
        assert caught.value.code == case["error"]
        return
    result = satellite_service._parse_tle_text(str(case["text"]))
    assert [item.name for item in result] == case["names"]
    assert [item.norad_id for item in result] == case["ids"]


@pytest.mark.parametrize(
    "payload", ["Error: no GP data", "GP data has not updated since your last successful download"]
)
async def test_all_unusable_groups_raise(payload: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations"])
    cache = AsyncMock()
    cache.get.return_value = None
    with pytest.raises(OrbitElementError):
        await get_satellites(_Proxy({"GROUP=stations": payload}), cache)  # type: ignore[arg-type]
    cache.set.assert_not_awaited()


async def test_comment_does_not_discard_healthy_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations"])
    text = (
        Path(__file__).resolve().parents[4] / "tests/fixtures/satellites/iss-valid.tle"
    ).read_text()
    cache = AsyncMock()
    cache.get.return_value = None
    result = await get_satellites(_Proxy({"GROUP=stations": "# not updated\n" + text}), cache)  # type: ignore[arg-type]
    assert [sat.norad_id for sat in result] == [25544]


async def test_empty_source_is_cached_as_empty_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations"])
    cache = AsyncMock()
    cache.get.return_value = None
    assert await get_satellites(_Proxy({"GROUP=stations": "  \n"}), cache) == []  # type: ignore[arg-type]
    cache.set.assert_awaited_once_with(satellite_service.CACHE_KEY, [], satellite_service.CACHE_TTL)


async def test_cached_empty_is_a_snapshot() -> None:
    cache = AsyncMock()
    cache.get.return_value = []
    assert await get_satellites(_Proxy({}), cache) == []  # type: ignore[arg-type]


@pytest.mark.parametrize("payload, expected_status", [("Error: no GP data", 502), (" ", 200)])
async def test_legacy_http_distinguishes_invalid_and_empty(
    payload: str, expected_status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app

    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations"])
    app.state.cache.get.return_value = None
    app.state.proxy.get_text = AsyncMock(return_value=payload)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/satellites")
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json() == []


async def test_partial_group_diagnostics_are_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    import structlog

    monkeypatch.setattr(satellite_service, "_CELESTRAK_GROUPS", ["stations", "broken"])
    cache = AsyncMock()
    cache.get.return_value = None
    proxy = _Proxy(
        {"GROUP=stations": _tle("ISS (ZARYA)", 25544), "GROUP=broken": "Error: no GP data"}
    )
    with structlog.testing.capture_logs() as logs:
        result = await get_satellites(proxy, cache)  # type: ignore[arg-type]
    assert [sat.norad_id for sat in result] == [25544]
    assert any(
        entry["event"] == "celestrak_group_failed" and entry["reason"] == "invalid"
        for entry in logs
    )
    assert any(
        entry["event"] == "celestrak_total" and entry["failed_groups"] == 1 for entry in logs
    )
