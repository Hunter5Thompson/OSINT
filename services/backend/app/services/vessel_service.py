"""Vessel data service — AISStream burst-fetch + Digitraffic REST fallback."""

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
CACHE_TTL = 60  # seconds
MAX_AGE_MS = 300_000  # 5 minutes — discard stale positions

# Finnish Digitraffic — free, no auth, real-time AIS (Baltic only)
LOCATIONS_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"
METADATA_URL = "https://meri.digitraffic.fi/api/ais/v1/vessels"

# AISStream burst duration
BURST_SECONDS = 15


async def get_vessels(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Vessel]:
    """Return vessels from cache, or fetch via AISStream burst / Digitraffic fallback."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return [Vessel(**v) for v in cached]

    # Primary: AISStream global WebSocket burst
    vessels = await _burst_fetch_aisstream()

    # Fallback: Digitraffic (Baltic only)
    if not vessels:
        vessels = await _fetch_digitraffic(proxy)

    if vessels:
        await cache.set(CACHE_KEY, [v.model_dump(mode="json") for v in vessels], CACHE_TTL)

    return vessels


async def _burst_fetch_aisstream() -> list[Vessel]:
    """Connect to AISStream for a burst, collecting global vessel positions."""
    if not settings.aisstream_api_key:
        logger.warning("aisstream_no_api_key")
        return []

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
                async with asyncio.timeout(BURST_SECONDS):
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

                        # Dedup by MMSI — keep latest position
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
        logger.info("aisstream_burst_complete", count=len(vessels), burst_seconds=BURST_SECONDS)
        return vessels
    except ImportError:
        logger.warning("websockets_not_installed")
        return []
    except Exception as exc:
        logger.warning("aisstream_burst_failed", error=str(exc))
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

        # Build MMSI → metadata lookup
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

                # Filter stale positions (> 5 min old)
                ts = props.get("timestampExternal")
                if ts and (now_ms - ts) > MAX_AGE_MS:
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
