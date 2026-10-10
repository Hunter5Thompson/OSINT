"""TLEUpdater must respect CelesTrak's 2-hour GP update cycle.

CelesTrak answers a re-download within the cycle with 403 ("GP data has not
updated since your last successful download ...") and may block IPs that keep
doing it. Every container restart used to re-fetch all 16 groups.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
import structlog

from config import settings
from feeds.tle_updater import (
    CELESTRAK_BASE,
    CELESTRAK_UPDATE_INTERVAL_S,
    TLEUpdater,
    parse_tle_text,
)
from orbit_elements import OrbitElementError

GROUP = {"name": "starlink", "param": "GROUP=starlink&FORMAT=tle"}
# Synthetic STARLINK fixture with qualified grammar, not an orbital reference.
TLE = (
    "STARLINK-1007\n"
    "1 44713U 19074A   26269.50000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 44713  53.0540 100.0000 0001000  90.0000 270.0000 15.06400000    01\n"
)
TLE = (
    "\n".join(
        line[:68] + str(sum(int(c) if c.isdigit() else c == "-" for c in line[:68]) % 10)
        if line.startswith(("1 ", "2 "))
        else line
        for line in TLE.splitlines()
    )
    + "\n"
)


async def _updater_with_cache(remaining_ttl: int | None) -> TLEUpdater:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    if remaining_ttl is not None:
        await r.set("tle:group:starlink", json.dumps([{"norad_id": "44713"}]), ex=remaining_ttl)
    u = TLEUpdater()
    u._redis = r
    return u


@pytest.mark.asyncio
async def test_group_cached_within_update_cycle_is_not_refetched():
    u = await _updater_with_cache(settings.tle_cache_ttl - 60)  # stored 1 min ago
    u._fetch_group = AsyncMock()
    with patch("feeds.tle_updater.TLE_GROUPS", [GROUP]):
        await u.update()
    u._fetch_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_older_than_update_cycle_is_refetched():
    u = await _updater_with_cache(settings.tle_cache_ttl - CELESTRAK_UPDATE_INTERVAL_S - 60)
    u._fetch_group = AsyncMock(return_value=TLE)
    with patch("feeds.tle_updater.TLE_GROUPS", [GROUP]):
        await u.update()
    u._fetch_group.assert_awaited_once()


@pytest.mark.asyncio
async def test_uncached_group_is_fetched():
    u = await _updater_with_cache(None)
    u._fetch_group = AsyncMock(return_value=TLE)
    with patch("feeds.tle_updater.TLE_GROUPS", [GROUP]):
        await u.update()
    assert json.loads(await u._redis.get("tle:group:starlink"))[0]["norad_id"] == "44713"


@pytest.mark.asyncio
async def test_not_updated_403_is_informational(httpx_mock):
    httpx_mock.add_response(
        url=f"{CELESTRAK_BASE}?{GROUP['param']}",
        status_code=403,
        text="GP data has not updated since your last successful\n"
        "download of GROUP=starlink at 2026-09-26 20:37:49 UTC.\n"
        "Data is updated once every 2 hours.",
    )
    with structlog.testing.capture_logs() as logs:
        assert await TLEUpdater()._fetch_group(GROUP) is None
    events = [(e["event"], e["log_level"]) for e in logs]
    assert ("tle_group_not_updated", "info") in events
    assert not any(e[0] == "tle_fetch_failed" for e in events)


TEXT_CASES = json.loads(
    (
        Path(__file__).resolve().parents[3] / "tests/fixtures/satellites/d07-text-cases.json"
    ).read_text()
)["cases"]


@pytest.mark.parametrize("case", TEXT_CASES, ids=lambda case: case["id"])
def test_shared_text_layout_matrix(case: dict[str, object]) -> None:
    if "error" in case:
        with pytest.raises(OrbitElementError) as caught:
            parse_tle_text(str(case["text"]))
        assert caught.value.code == case["error"]
        return
    result = parse_tle_text(str(case["text"]))
    assert [item["name"] for item in result] == case["names"]
    assert [int(item["norad_id"]) for item in result] == case["ids"]


@pytest.mark.asyncio
async def test_all_unusable_groups_raise_and_preserve_old_cache():
    u = await _updater_with_cache(settings.tle_cache_ttl - CELESTRAK_UPDATE_INTERVAL_S - 60)
    before = await u._redis.get("tle:group:starlink")
    u._fetch_group = AsyncMock(return_value="Error: no GP data")
    with patch("feeds.tle_updater.TLE_GROUPS", [GROUP]), pytest.raises(ValueError):
        await u.update()
    assert await u._redis.get("tle:group:starlink") == before


@pytest.mark.asyncio
async def test_legitimate_empty_group_is_stored():
    u = await _updater_with_cache(None)
    u._fetch_group = AsyncMock(return_value=" \n")
    with patch("feeds.tle_updater.TLE_GROUPS", [GROUP]):
        await u.update()
    assert json.loads(await u._redis.get("tle:group:starlink")) == []


@pytest.mark.asyncio
async def test_not_updated_without_any_cache_is_unavailable():
    u = await _updater_with_cache(None)
    u._fetch_group = AsyncMock(return_value=None)
    with patch("feeds.tle_updater.TLE_GROUPS", [GROUP]), pytest.raises(ValueError):
        await u.update()


@pytest.mark.asyncio
async def test_healthy_group_survives_failed_neighbor(httpx_mock):
    u = await _updater_with_cache(None)
    httpx_mock.add_response(url=f"{CELESTRAK_BASE}?{GROUP['param']}", text=TLE)
    broken = {"name": "broken", "param": "GROUP=broken&FORMAT=tle"}
    httpx_mock.add_response(url=f"{CELESTRAK_BASE}?{broken['param']}", text="Error: no GP data")
    with (
        patch("feeds.tle_updater.TLE_GROUPS", [GROUP, broken]),
        structlog.testing.capture_logs() as logs,
    ):
        await u.update()
    assert json.loads(await u._redis.get("tle:group:starlink"))[0]["norad_id"] == "44713"
    assert await u._redis.get("tle:group:broken") is None
    assert any(
        entry["event"] == "tle_update_finished" and entry["failed_groups"] == 1 for entry in logs
    )


@pytest.mark.asyncio
async def test_transport_failure_is_unavailable(httpx_mock):
    u = await _updater_with_cache(None)
    httpx_mock.add_response(url=f"{CELESTRAK_BASE}?{GROUP['param']}", status_code=500)
    with patch("feeds.tle_updater.TLE_GROUPS", [GROUP]), pytest.raises(ValueError):
        await u.update()
    assert await u._redis.get("tle:group:starlink") is None
