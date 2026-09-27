"""TLE classification and group fallback."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import satellite_service
from app.services.satellite_service import (
    _categorize,
    _detect_country,
    get_satellites,
)


def _tle(name: str, norad: int, inclination: str = "51.6400") -> str:
    line1 = f"1 {norad:05d}U 98067A   24100.00000000  .00000000  00000-0  00000-0 0  9991"
    line2 = (
        f"2 {norad:05d} {inclination} 208.9163 0006703  35.2324  78.1456 15.49568716000001"
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
    cache.get.return_value = []

    with pytest.raises(httpx.ConnectError):
        await get_satellites(proxy, cache)  # type: ignore[arg-type]
