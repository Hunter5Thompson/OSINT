"""Vessel data service — AISStream background collector + Digitraffic fallback."""

import asyncio
import json
import math
import time
from typing import Any

import structlog
from pydantic import ValidationError

from app.config import settings
from app.models.vessel import Vessel, normalize_cog, normalize_sog
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "vessels:all"
CACHE_TTL = 180  # seconds — collector refreshes every 60s, buffer for misses
VESSEL_MAX_AGE_S = 600  # 10 minutes — discard positions older than this

# Finnish Digitraffic — free, no auth, real-time AIS (Baltic only)
LOCATIONS_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"
METADATA_URL = "https://meri.digitraffic.fi/api/ais/v1/vessels"

# AISStream collection window per cycle
COLLECT_SECONDS = 45
COLLECT_INTERVAL = 60  # seconds between collection cycles

# Background task handle
_collector_task: asyncio.Task[None] | None = None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _finite_degrees(value: object, *, limit: float) -> float | None:
    number = _finite_number(value)
    if number is None or not -limit <= number <= limit:
        return None
    return number


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or isinstance(value, float):
        return None
    if not isinstance(value, (int, str)):
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    if number <= 0:
        return None
    return number


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return {str(key): item for key, item in value.items()}


def vessel_from_ais_message(data: object) -> Vessel | None:
    """Parse one AISStream position. Missing fields and null names are skipped, not fatal."""
    payload = _as_dict(data)
    if payload is None:
        return None
    meta = _as_dict(payload.get("MetaData"))
    message = _as_dict(payload.get("Message"))
    if meta is None or message is None:
        return None
    pos = _as_dict(message.get("PositionReport"))
    if pos is None:
        return None
    if "Latitude" not in pos or "Longitude" not in pos:
        return None
    mmsi = _positive_int(meta.get("MMSI"))
    if mmsi is None:
        return None
    latitude = _finite_degrees(pos.get("Latitude"), limit=90)
    longitude = _finite_degrees(pos.get("Longitude"), limit=180)
    if latitude is None or longitude is None:
        return None
    # AIS uses 0,0 as "position unavailable", including the Gulf of Guinea sentinel.
    if latitude == 0 and longitude == 0:
        return None
    ship_type = _positive_int(meta.get("ShipType")) or 0
    return Vessel(
        mmsi=mmsi,
        name=_optional_text(meta.get("ShipName")),
        latitude=latitude,
        longitude=longitude,
        speed_knots=normalize_sog(pos.get("Sog")),
        course=normalize_cog(pos.get("Cog")),
        ship_type=ship_type,
        destination=None,
    )


def vessels_from_cache(cached: object) -> list[Vessel] | None:
    """Return a non-empty validated list. Empty and corrupt caches are misses."""
    if not isinstance(cached, list) or not cached:
        return None
    vessels: list[Vessel] = []
    for item in cached:
        if not isinstance(item, dict):
            continue
        try:
            vessels.append(Vessel.model_validate(item))
        except ValidationError:
            continue
    return vessels or None


def merge_vessel_snapshot(
    accumulated: dict[int, tuple[Vessel, float]],
    new_vessels: list[Vessel],
    *,
    now: float,
) -> list[Vessel]:
    """Merge a burst into the accumulator and drop positions older than the max age."""
    for vessel in new_vessels:
        accumulated[vessel.mmsi] = (vessel, now)
    cutoff = now - VESSEL_MAX_AGE_S
    stale = [key for key, (_, seen_at) in accumulated.items() if seen_at < cutoff]
    for key in stale:
        del accumulated[key]
    return [vessel for vessel, _ in accumulated.values()]


async def publish_vessel_snapshot(cache: CacheService, vessels: list[Vessel]) -> None:
    """Store a non-empty snapshot. An empty snapshot deletes the key so fallbacks can run."""
    if vessels:
        await cache.set(
            CACHE_KEY,
            [vessel.model_dump(mode="json") for vessel in vessels],
            CACHE_TTL,
        )
        return
    await cache.delete(CACHE_KEY)


async def get_vessels(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Vessel]:
    """Return vessels from cache. An empty cache falls through to Digitraffic."""
    cached = vessels_from_cache(await cache.get(CACHE_KEY))
    if cached is not None:
        return cached
    vessels = await _fetch_digitraffic(proxy)
    if vessels:
        await cache.set(
            CACHE_KEY,
            [vessel.model_dump(mode="json") for vessel in vessels],
            CACHE_TTL,
        )
    return vessels


async def start_collector(cache: CacheService) -> None:
    """Start the background AISStream collector task."""
    global _collector_task
    if _collector_task and not _collector_task.done():
        return
    if not settings.aisstream_api_key:
        logger.warning("aisstream_collector_disabled", reason="no API key")
        return
    _collector_task = asyncio.create_task(_collector_loop(cache))
    logger.info("aisstream_collector_started")


async def stop_collector() -> None:
    """Stop the background collector."""
    global _collector_task
    if _collector_task and not _collector_task.done():
        _collector_task.cancel()
        try:
            await _collector_task
        except asyncio.CancelledError:
            pass
    _collector_task = None
    logger.info("aisstream_collector_stopped")


async def _collector_loop(cache: CacheService) -> None:
    """Continuously collect AIS data, accumulating across cycles."""
    accumulated: dict[int, tuple[Vessel, float]] = {}

    while True:
        try:
            new_vessels = await collect_ais_positions(window_s=COLLECT_SECONDS)
            vessels = merge_vessel_snapshot(accumulated, new_vessels, now=time.time())
            await publish_vessel_snapshot(cache, vessels)
            logger.info(
                "aisstream_cache_updated",
                total=len(vessels),
                new=len(new_vessels),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("aisstream_collector_error", error=str(exc))

        await asyncio.sleep(COLLECT_INTERVAL)


async def collect_ais_positions(*, window_s: float) -> list[Vessel]:
    """Connect to AISStream and collect vessel positions.

    One bad message is ignored. A missing API key or a dropped socket returns
    whatever was parsed, or an empty list.
    """
    if not settings.aisstream_api_key:
        logger.warning("aisstream_no_api_key")
        return []

    seen: dict[int, Vessel] = {}
    try:
        import websockets

        subscribe_msg = json.dumps({
            "APIKey": settings.aisstream_api_key,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport"],
        })

        async with websockets.connect(
            settings.aisstream_ws_url,
            close_timeout=5,
        ) as ws:
            await ws.send(subscribe_msg)
            try:
                async with asyncio.timeout(window_s):
                    async for msg in ws:
                        vessel = _vessel_from_raw_message(msg)
                        if vessel is not None:
                            seen[vessel.mmsi] = vessel
            except TimeoutError:
                pass
        logger.info("aisstream_collect_complete", count=len(seen), seconds=window_s)
    except ImportError:
        logger.warning("websockets_not_installed")
    except Exception as exc:
        logger.warning("aisstream_collect_failed", error=str(exc))
    return list(seen.values())


def _vessel_from_raw_message(msg: object) -> Vessel | None:
    if isinstance(msg, bytes):
        try:
            msg = msg.decode("utf-8")
        except UnicodeError:
            return None
    if not isinstance(msg, str):
        return None
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return None
    return vessel_from_ais_message(data)


async def _fetch_digitraffic(proxy: ProxyService) -> list[Vessel]:
    """Fetch vessel positions + metadata from Finnish Digitraffic AIS API.

    Transport errors propagate so the REST route can answer 502. A single bad
    feature is skipped.
    """
    loc_resp, meta_resp = await asyncio.wait_for(
        asyncio.gather(
            proxy.client.get(LOCATIONS_URL, headers={"Accept-Encoding": "gzip"}),
            proxy.client.get(METADATA_URL, headers={"Accept-Encoding": "gzip"}),
        ),
        timeout=20.0,
    )
    loc_resp.raise_for_status()
    meta_resp.raise_for_status()

    locations = loc_resp.json()
    metadata_list = meta_resp.json()
    if not isinstance(locations, dict) or not isinstance(metadata_list, list):
        return []

    meta_map: dict[int, dict[str, Any]] = {}
    for item in metadata_list:
        if not isinstance(item, dict):
            continue
        try:
            mmsi = int(item.get("mmsi") or 0)
        except (TypeError, ValueError):
            continue
        if mmsi > 0:
            meta_map[mmsi] = item

    now_ms = int(time.time() * 1000)
    features = locations.get("features", [])
    if not isinstance(features, list):
        return []
    vessels: list[Vessel] = []

    for feature in features:
        parsed = _parse_digitraffic_feature(feature, meta_map, now_ms=now_ms)
        if parsed is not None:
            vessels.append(parsed)

    logger.info("digitraffic_fetched", count=len(vessels), total_features=len(features))
    return vessels


def _parse_digitraffic_feature(
    feature: object,
    meta_map: dict[int, dict[str, Any]],
    *,
    now_ms: int,
) -> Vessel | None:
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(props, dict) or not isinstance(geometry, dict):
        return None
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        mmsi = int(props.get("mmsi") or 0)
    except (TypeError, ValueError):
        return None
    if mmsi <= 0:
        return None
    raw_ts = props.get("timestampExternal")
    if isinstance(raw_ts, (int, float)) and not isinstance(raw_ts, bool):
        if (now_ms - raw_ts) > VESSEL_MAX_AGE_S * 1000:
            return None
    latitude = _finite_degrees(coords[1], limit=90)
    longitude = _finite_degrees(coords[0], limit=180)
    if latitude is None or longitude is None:
        return None
    meta = meta_map.get(mmsi, {})
    try:
        ship_type = int(meta.get("shipType") or 0)
    except (TypeError, ValueError):
        ship_type = 0
    return Vessel(
        mmsi=mmsi,
        name=_optional_text(meta.get("name")),
        latitude=latitude,
        longitude=longitude,
        speed_knots=props.get("sog"),
        course=props.get("cog"),
        ship_type=ship_type,
        destination=_optional_text(meta.get("destination")),
    )
