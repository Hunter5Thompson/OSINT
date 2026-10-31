"""TLE (Two-Line Element) Updater.

Fetches satellite orbital data from CelesTrak and caches in Redis.
"""

from __future__ import annotations

import time

import httpx
import redis.asyncio as aioredis
import structlog

from config import settings
from orbit_elements import scan_tle_text

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# CelesTrak TLE Groups
# ---------------------------------------------------------------------------
CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"
# CelesTrak refreshes GP data once every 2 h and answers a re-download within
# that window with 403 (repeat offenders risk an IP block).
CELESTRAK_UPDATE_INTERVAL_S = 7200
_NOT_UPDATED_MARKER = "has not updated since your last successful"

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
    """Read independently validated named and bare TLE pairs."""
    scan = scan_tle_text(raw)
    if scan.diagnostics:
        log.warning(
            "tle_rows_rejected",
            invalid=sum(item.code == "invalid" for item in scan.diagnostics),
            unsupported=sum(item.code == "unsupported" for item in scan.diagnostics),
        )
    return [
        {
            "name": record.name,
            "norad_id": str(record.elements.norad_id),
            "tle_line1": record.line1,
            "tle_line2": record.line2,
        }
        for record in scan.records
    ]


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
                if resp.status_code == 403 and _NOT_UPDATED_MARKER in resp.text:
                    log.info("tle_group_not_updated", group=group["name"])
                    return None
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            log.warning("tle_fetch_failed", group=group["name"], error=str(exc))
            raise

    async def _cached_within_update_cycle(self, group_name: str) -> bool:
        """True if the group was stored less than one CelesTrak cycle ago
        (derived from the remaining TTL of the key written by _store_group)."""
        r = await self._get_redis()
        remaining = await r.ttl(f"tle:group:{group_name}")
        return remaining > settings.tle_cache_ttl - CELESTRAK_UPDATE_INTERVAL_S

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
        failures = 0
        retained_groups = 0
        start = time.monotonic()

        for group in TLE_GROUPS:
            try:
                if await self._cached_within_update_cycle(group["name"]):
                    retained_groups += 1
                    log.info("tle_group_fresh_skip", group=group["name"])
                    continue
                raw = await self._fetch_group(group)
                if raw is None:
                    r = await self._get_redis()
                    if not await r.exists(f"tle:group:{group['name']}"):
                        raise ValueError("Unchanged TLE source has no retained cache")
                    retained_groups += 1
                    continue

                satellites = parse_tle_text(raw)
                await self._store_group(group["name"], satellites)
                log.info(
                    "tle_group_cached",
                    group=group["name"],
                    satellite_count=len(satellites),
                )
                total_sats += len(satellites)
            except Exception:
                failures += 1
                log.exception("tle_group_error", group=group["name"])

        elapsed = round(time.monotonic() - start, 2)
        log.info(
            "tle_update_finished",
            total_satellites=total_sats,
            failed_groups=failures,
            retained_groups=retained_groups,
            elapsed_seconds=elapsed,
        )
        if failures and not total_sats and not retained_groups:
            raise ValueError("No usable TLE groups; previous cache preserved")

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
