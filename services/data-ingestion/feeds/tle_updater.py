"""TLE (Two-Line Element) Updater — fetches satellite orbital data from CelesTrak and caches in Redis."""

from __future__ import annotations

import time

import httpx
import redis.asyncio as aioredis
import structlog

from config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# CelesTrak TLE Groups
# ---------------------------------------------------------------------------
CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"

TLE_GROUPS: list[dict[str, str]] = [
    {"name": "active", "param": "GROUP=active&FORMAT=tle"},
    {"name": "stations", "param": "GROUP=stations&FORMAT=tle"},
    {"name": "visual", "param": "GROUP=visual&FORMAT=tle"},
    {"name": "weather", "param": "GROUP=weather&FORMAT=tle"},
    {"name": "resource", "param": "GROUP=resource&FORMAT=tle"},
    {"name": "military", "param": "GROUP=military&FORMAT=tle"},
    {"name": "geodetic", "param": "GROUP=geodetic&FORMAT=tle"},
    {"name": "engineering", "param": "GROUP=engineering&FORMAT=tle"},
    {"name": "education", "param": "GROUP=education&FORMAT=tle"},
    {"name": "gnss", "param": "GROUP=gnss&FORMAT=tle"},
    {"name": "gps-ops", "param": "GROUP=gps-ops&FORMAT=tle"},
    {"name": "galileo", "param": "GROUP=galileo&FORMAT=tle"},
    {"name": "beidou", "param": "GROUP=beidou&FORMAT=tle"},
    {"name": "geo", "param": "GROUP=geo&FORMAT=tle"},
    {"name": "starlink", "param": "GROUP=starlink&FORMAT=tle"},
    {"name": "oneweb", "param": "GROUP=oneweb&FORMAT=tle"},
]


def parse_tle_text(raw: str) -> list[dict[str, str]]:
    """Parse raw TLE text into structured satellite records.

    TLE format is 3 lines per satellite:
        Line 0: Satellite name
        Line 1: TLE line 1
        Line 2: TLE line 2
    """
    lines = [ln.rstrip() for ln in raw.strip().splitlines() if ln.strip()]
    satellites: list[dict[str, str]] = []

    i = 0
    while i + 2 < len(lines):
        # Heuristic: TLE line 1 starts with "1 ", TLE line 2 starts with "2 "
        # The name line does NOT start with "1 " or "2 "
        name_line = lines[i]
        line1 = lines[i + 1]
        line2 = lines[i + 2]

        if line1.startswith("1 ") and line2.startswith("2 "):
            norad_id = line1[2:7].strip()
            satellites.append(
                {
                    "name": name_line.strip(),
                    "norad_id": norad_id,
                    "tle_line1": line1,
                    "tle_line2": line2,
                }
            )
            i += 3
        else:
            # Malformed — skip one line and retry
            i += 1

    return satellites


class TLEUpdater:
    """Fetch TLE data from CelesTrak and store in Redis with TTL."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
        return self._redis

    async def _fetch_group(self, group: dict[str, str]) -> str | None:
        """Fetch TLE data for a single CelesTrak group."""
        url = f"{CELESTRAK_BASE}?{group['param']}"
        try:
            async with httpx.AsyncClient(
                timeout=settings.http_timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            log.warning("tle_fetch_failed", group=group["name"], error=str(exc))
            return None

    async def _store_group(self, group_name: str, satellites: list[dict[str, str]]) -> None:
        """Store parsed satellite data in Redis as a hash with TTL."""
        r = await self._get_redis()

        # Store full group as a JSON list
        import json

        key = f"tle:group:{group_name}"
        await r.set(key, json.dumps(satellites), ex=settings.tle_cache_ttl)

        # Store individual satellites for quick lookup by NORAD ID
        pipe = r.pipeline()
        for sat in satellites:
            sat_key = f"tle:norad:{sat['norad_id']}"
            pipe.set(sat_key, json.dumps(sat), ex=settings.tle_cache_ttl)
        await pipe.execute()

    async def update(self) -> None:
        """Fetch all TLE groups and cache in Redis."""
        log.info("tle_update_started", group_count=len(TLE_GROUPS))
        total_sats = 0
        start = time.monotonic()

        for group in TLE_GROUPS:
            try:
                raw = await self._fetch_group(group)
                if raw is None:
                    continue

                satellites = parse_tle_text(raw)
                if not satellites:
                    log.warning("tle_empty_group", group=group["name"])
                    continue

                await self._store_group(group["name"], satellites)
                log.info(
                    "tle_group_cached",
                    group=group["name"],
                    satellite_count=len(satellites),
                )
                total_sats += len(satellites)
            except Exception:
                log.exception("tle_group_error", group=group["name"])

        elapsed = round(time.monotonic() - start, 2)
        log.info("tle_update_finished", total_satellites=total_sats, elapsed_seconds=elapsed)

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
