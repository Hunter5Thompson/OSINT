"""Versioned GP producer; legacy TLE caches remain independently available."""

import json
from datetime import UTC, datetime
from typing import Literal, TypedDict, cast

import httpx
import redis.asyncio as aioredis
import structlog
from redis.exceptions import WatchError

from config import settings
from feeds.tle_updater import TLE_GROUPS
from orbit_elements import OMMElements, OrbitElementError, normalize_omm

log = structlog.get_logger(__name__)
UPDATE_CYCLE_S = 7200
FUTURE_TOLERANCE_S = 60
UNCHANGED_MARKER = "has not updated since your last successful"


class GPOrbit(TypedDict):
    format: Literal["omm"]
    elements: OMMElements


class GPRecord(TypedDict):
    norad_id: int
    name: str
    orbit: GPOrbit


class GPRejection(TypedDict):
    index: int
    code: Literal["invalid", "unsupported"]
    reason: str


class GPGroupSnapshot(TypedDict):
    schema_version: Literal[1]
    group: str
    fetched_at: str
    satellites: list[GPRecord]
    status: Literal["ok", "partial"]
    accepted_records: int
    rejections: list[GPRejection]


def decode_gp_group(payload: object, group: str, fetched_at: str) -> GPGroupSnapshot:
    """Isolate individual records; invalid root/all-invalid is never empty success."""
    if not isinstance(payload, list):
        raise ValueError("GP group requires a JSON list")
    records: dict[int, GPRecord] = {}
    rejected: list[GPRejection] = []
    accepted = 0
    for index, raw in enumerate(payload):
        try:
            elements = normalize_omm(raw)
        except OrbitElementError as exc:
            rejected.append({"index": index, "code": exc.code, "reason": exc.reason})
            continue
        accepted += 1
        record: GPRecord = {
            "norad_id": elements["NORAD_CAT_ID"],
            "name": elements["OBJECT_NAME"],
            "orbit": {"format": "omm", "elements": elements},
        }
        previous = records.get(record["norad_id"])
        if previous is None or elements["EPOCH"] > previous["orbit"]["elements"]["EPOCH"]:
            records[record["norad_id"]] = record
    if payload and not accepted:
        raise ValueError("GP group has no usable records")
    return {
        "schema_version": 1,
        "group": group,
        "fetched_at": fetched_at,
        "satellites": list(records.values()),
        "accepted_records": accepted,
        "status": "partial" if rejected else "ok",
        "rejections": rejected,
    }


def valid_cached_record(raw: object) -> GPRecord:
    if not isinstance(raw, dict) or not isinstance(raw.get("orbit"), dict):
        raise ValueError("GP cache requires an orbit record")
    if raw["orbit"].get("format") != "omm":
        raise ValueError("GP cache requires OMM elements")
    elements = normalize_omm(raw["orbit"].get("elements"))
    if type(raw.get("norad_id")) is not int or raw["norad_id"] != elements["NORAD_CAT_ID"]:
        raise ValueError("GP cache catalog identifiers disagree")
    if raw.get("name") != elements["OBJECT_NAME"]:
        raise ValueError("GP cache names disagree")
    return {
        "norad_id": elements["NORAD_CAT_ID"],
        "name": elements["OBJECT_NAME"],
        "orbit": {"format": "omm", "elements": elements},
    }


def valid_cached_group(raw: object, group: str) -> GPGroupSnapshot:
    if (
        not isinstance(raw, dict)
        or type(raw.get("schema_version")) is not int
        or raw["schema_version"] != 1
    ):
        raise ValueError("Unsupported GP cache generation")
    if raw.get("group") != group or not isinstance(raw.get("fetched_at"), str):
        raise ValueError("GP cache source identity/time missing")
    fetched_at = raw["fetched_at"]
    if (
        not fetched_at.endswith("Z")
        or (datetime.now(UTC) - datetime.fromisoformat(fetched_at)).total_seconds()
        < -FUTURE_TOLERANCE_S
    ):
        raise ValueError("GP cache requires a plausible UTC fetch time")
    if not isinstance(raw.get("satellites"), list) or not isinstance(raw.get("rejections"), list):
        raise ValueError("GP cache records/diagnostics missing")
    records = [valid_cached_record(record) for record in raw["satellites"]]
    ids = [record["norad_id"] for record in records]
    accepted = raw.get("accepted_records")
    if (
        type(accepted) is not int
        or accepted < len(records)
        or bool(accepted) != bool(records)
        or len(ids) != len(set(ids))
    ):
        raise ValueError("GP cache source record counts disagree")
    for item in raw["rejections"]:
        if (
            not isinstance(item, dict)
            or type(item.get("index")) is not int
            or item["index"] < 0
            or item.get("code") not in ("invalid", "unsupported")
            or not isinstance(item.get("reason"), str)
        ):
            raise ValueError("GP cache diagnostics invalid")
    if raw.get("status") != ("partial" if raw["rejections"] else "ok"):
        raise ValueError("GP cache coverage disagrees")
    return cast(GPGroupSnapshot, raw)


class GPUpdater:
    def __init__(self, groups: list[str] | None = None) -> None:
        self.groups = groups if groups is not None else [group["name"] for group in TLE_GROUPS]
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def _store_group(self, snapshot: GPGroupSnapshot) -> None:
        redis = await self._get_redis()
        keys = [f"orbits:v1:norad:{record['norad_id']}" for record in snapshot["satellites"]]
        for _attempt in range(3):
            try:
                async with redis.pipeline(transaction=True) as pipe:
                    if keys:
                        await pipe.watch(*keys)
                    updated: list[GPRecord] = []
                    for record, key in zip(snapshot["satellites"], keys, strict=True):
                        cached = await pipe.get(key) if keys else None
                        if cached is not None:
                            try:
                                previous = valid_cached_record(json.loads(cached))
                                if (
                                    previous["orbit"]["elements"]["EPOCH"]
                                    > record["orbit"]["elements"]["EPOCH"]
                                ):
                                    continue
                            except (ValueError, TypeError):
                                log.warning(
                                    "gp_individual_cache_invalid", norad_id=record["norad_id"]
                                )
                        updated.append(record)
                    pipe.multi()
                    pipe.set(
                        f"orbits:v1:group:{snapshot['group']}",
                        json.dumps(snapshot),
                        ex=settings.tle_cache_ttl,
                    )
                    for record in updated:
                        pipe.set(
                            f"orbits:v1:norad:{record['norad_id']}",
                            json.dumps(record),
                            ex=settings.tle_cache_ttl,
                        )
                    await pipe.execute()
                    return
            except WatchError:
                continue
        raise ValueError("GP cache transaction conflicted; snapshot was not written")

    async def _retained_group(self, group: str) -> GPGroupSnapshot | None:
        redis = await self._get_redis()
        cached = await redis.get(f"orbits:v1:group:{group}")
        if cached is None:
            return None
        try:
            return valid_cached_group(json.loads(cached), group)
        except (ValueError, TypeError):
            log.warning("gp_group_cache_invalid", group=group)
            return None

    async def update(self) -> None:
        successful = 0
        failures = 0
        for group in self.groups:
            try:
                retained = await self._retained_group(group)
                if (
                    retained
                    and (
                        datetime.now(UTC) - datetime.fromisoformat(retained["fetched_at"])
                    ).total_seconds()
                    < UPDATE_CYCLE_S
                ):
                    successful += 1
                    log.info("gp_group_fresh_skip", group=group)
                    continue
                async with httpx.AsyncClient(
                    timeout=settings.http_timeout, follow_redirects=True
                ) as client:
                    response = await client.get(
                        settings.celestrak_gp_url, params={"GROUP": group, "FORMAT": "JSON"}
                    )
                    if response.status_code == 403 and UNCHANGED_MARKER in response.text:
                        if not retained:
                            raise ValueError("Unchanged GP source has no valid retained cache")
                        successful += 1
                        log.info("gp_group_not_updated", group=group)
                        continue
                    response.raise_for_status()
                    payload = response.json()
                snapshot = decode_gp_group(
                    payload, group, datetime.now(UTC).isoformat().replace("+00:00", "Z")
                )
                await self._store_group(snapshot)
                successful += 1
                log.info(
                    "gp_group_cached",
                    group=group,
                    accepted_records=snapshot["accepted_records"],
                    rejected_records=len(snapshot["rejections"]),
                )
            except Exception:
                failures += 1
                log.warning("gp_group_failed", group=group)
        log.info("gp_update_finished", successful_groups=successful, failed_groups=failures)
        if failures and not successful:
            raise ValueError("No usable GP groups; existing caches preserved")

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
