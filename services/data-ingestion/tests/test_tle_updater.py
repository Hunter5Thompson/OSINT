"""TLEUpdater must respect CelesTrak's 2-hour GP update cycle.

CelesTrak answers a re-download within the cycle with 403 ("GP data has not
updated since your last successful download ...") and may block IPs that keep
doing it. Every container restart used to re-fetch all 16 groups.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
import structlog

from config import settings
from feeds.tle_updater import CELESTRAK_BASE, CELESTRAK_UPDATE_INTERVAL_S, TLEUpdater

GROUP = {"name": "starlink", "param": "GROUP=starlink&FORMAT=tle"}
TLE = (
    "STARLINK-1007\n"
    "1 44713U 19074A   26269.50000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 44713  53.0540 100.0000 0001000  90.0000 270.0000 15.06400000    01\n"
)


async def _updater_with_cache(remaining_ttl: int | None) -> TLEUpdater:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    if remaining_ttl is not None:
        await r.set("tle:group:starlink", json.dumps([{"norad_id": "44713"}]),
                    ex=remaining_ttl)
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
        url=f"{CELESTRAK_BASE}?{GROUP['param']}", status_code=403,
        text="GP data has not updated since your last successful\n"
             "download of GROUP=starlink at 2026-09-26 20:37:49 UTC.\n"
             "Data is updated once every 2 hours.")
    with structlog.testing.capture_logs() as logs:
        assert await TLEUpdater()._fetch_group(GROUP) is None
    events = [(e["event"], e["log_level"]) for e in logs]
    assert ("tle_group_not_updated", "info") in events
    assert not any(e[0] == "tle_fetch_failed" for e in events)
