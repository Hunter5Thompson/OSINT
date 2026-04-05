"""Vessel data service — AISStream background collector + Digitraffic fallback."""

import asyncio
import json
import time

import structlog

from app.config import settings
from app.models.vessel import Vessel
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


async def get_vessels(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Vessel]:
    """Return vessels from cache. Background collector keeps cache fresh."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return [Vessel(**v) for v in cached]

    # Cache miss (collector hasn't run yet) — quick Digitraffic fallback
    vessels = await _fetch_digitraffic(proxy)
    if vessels:
        await cache.set(CACHE_KEY, [v.model_dump(mode="json") for v in vessels], CACHE_TTL)
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
    # Accumulated vessel store: MMSI → (Vessel, timestamp)
    accumulated: dict[int, tuple[Vessel, float]] = {}

    while True:
        try:
            new_vessels = await _collect_aisstream()
            now = time.time()

            # Merge new data into accumulated store
            if new_vessels:
                for v in new_vessels:
                    accumulated[v.mmsi] = (v, now)

            # Evict stale entries (older than VESSEL_MAX_AGE_S)
            cutoff = now - VESSEL_MAX_AGE_S
            stale_keys = [k for k, (_, ts) in accumulated.items() if ts < cutoff]
            for k in stale_keys:
                del accumulated[k]

            # Write accumulated data to cache
            all_vessels = [v.model_dump(mode="json") for v, _ in accumulated.values()]
            await cache.set(CACHE_KEY, all_vessels, CACHE_TTL)
            logger.info(
                "aisstream_cache_updated",
                total=len(all_vessels),
                new=len(new_vessels) if new_vessels else 0,
                evicted=len(stale_keys),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("aisstream_collector_error", error=str(exc))

        await asyncio.sleep(COLLECT_INTERVAL)


async def _collect_aisstream() -> list[Vessel]:
    """Connect to AISStream and collect vessel positions."""
    try:
        import websockets

        subscribe_msg = json.dumps({
            "APIKey": settings.aisstream_api_key,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport"],
        })

        seen: dict[int, Vessel] = {}

        async with websockets.connect(
            settings.aisstream_ws_url,
            close_timeout=5,
        ) as ws:
            await ws.send(subscribe_msg)

            try:
                async with asyncio.timeout(COLLECT_SECONDS):
                    async for msg in ws:
                        data = json.loads(msg)
                        meta = data.get("MetaData", {})
                        pos_report = data.get("Message", {}).get("PositionReport")
                        if not pos_report:
                            continue

                        mmsi = meta.get("MMSI", 0)
                        if not mmsi:
                            continue

                        lat = pos_report.get("Latitude", 0)
                        lon = pos_report.get("Longitude", 0)
                        if lat == 0 and lon == 0:
                            continue

                        seen[mmsi] = Vessel(
                            mmsi=mmsi,
                            name=meta.get("ShipName", "").strip() or None,
                            latitude=lat,
                            longitude=lon,
                            speed_knots=pos_report.get("Sog", 0),
                            course=pos_report.get("Cog", 0),
                            ship_type=meta.get("ShipType", 0),
                            destination=None,
                        )
            except TimeoutError:
                pass

        vessels = list(seen.values())
        logger.info("aisstream_collect_complete", count=len(vessels), seconds=COLLECT_SECONDS)
        return vessels
    except ImportError:
        logger.warning("websockets_not_installed")
        return []
    except Exception as exc:
        logger.warning("aisstream_collect_failed", error=str(exc))
        return []


async def _fetch_digitraffic(proxy: ProxyService) -> list[Vessel]:
    """Fetch vessel positions + metadata from Finnish Digitraffic AIS API."""
    try:
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

        meta_map: dict[int, dict] = {}
        for m in metadata_list:
            mmsi = m.get("mmsi")
            if mmsi:
                meta_map[int(mmsi)] = m

        now_ms = int(time.time() * 1000)
        features = locations.get("features", [])
        vessels: list[Vessel] = []

        for f in features:
            try:
                props = f.get("properties", {})
                coords = f.get("geometry", {}).get("coordinates", [])
                if not coords or len(coords) < 2:
                    continue

                mmsi = props.get("mmsi")
                if not mmsi:
                    continue

                ts = props.get("timestampExternal")
                if ts and (now_ms - ts) > VESSEL_MAX_AGE_S * 1000:
                    continue

                mmsi_int = int(mmsi)
                meta = meta_map.get(mmsi_int, {})

                vessels.append(
                    Vessel(
                        mmsi=mmsi_int,
                        name=meta.get("name", "").strip() or None,
                        latitude=float(coords[1]),
                        longitude=float(coords[0]),
                        speed_knots=float(props.get("sog", 0) or 0),
                        course=float(props.get("cog", 0) or 0),
                        ship_type=int(meta.get("shipType", 0) or 0),
                        destination=meta.get("destination", "").strip() or None,
                    )
                )
            except Exception:
                continue

        logger.info("digitraffic_fetched", count=len(vessels), total_features=len(features))
        return vessels
    except Exception as exc:
        logger.warning("digitraffic_fetch_failed", error=str(exc))
        return []
