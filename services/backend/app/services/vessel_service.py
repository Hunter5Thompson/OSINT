"""Vessel data service — AISStream WebSocket cache + Digitraffic REST fallback."""

import asyncio
import time

import structlog

from app.models.vessel import Vessel
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "vessels:all"
CACHE_TTL = 60  # seconds
MAX_AGE_MS = 300_000  # 5 minutes — discard stale positions

# Finnish Digitraffic — free, no auth, real-time AIS (requires gzip)
LOCATIONS_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"
METADATA_URL = "https://meri.digitraffic.fi/api/ais/v1/vessels"

# Ship type codes → human-readable categories
SHIP_TYPE_NAMES: dict[int, str] = {
    20: "Wing in ground", 30: "Fishing", 31: "Towing", 32: "Towing (large)",
    33: "Dredging", 34: "Diving ops", 35: "Military ops", 36: "Sailing",
    37: "Pleasure craft", 40: "High speed craft", 50: "Pilot vessel",
    51: "SAR", 52: "Tug", 53: "Port tender", 54: "Anti-pollution",
    55: "Law enforcement", 58: "Medical transport", 59: "Noncombatant",
    60: "Passenger", 70: "Cargo", 80: "Tanker", 90: "Other",
}


def _ship_type_label(code: int) -> str:
    """Map AIS ship type code to label. Codes are ranges (60-69 = Passenger, etc.)."""
    if code in SHIP_TYPE_NAMES:
        return SHIP_TYPE_NAMES[code]
    decade = (code // 10) * 10
    return SHIP_TYPE_NAMES.get(decade, f"Type {code}")


async def get_vessels(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Vessel]:
    """Return vessels from cache (AISStream WS) or Digitraffic REST fallback."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return [Vessel(**v) for v in cached]

    vessels = await _fetch_digitraffic(proxy)
    if vessels:
        await cache.set(CACHE_KEY, [v.model_dump(mode="json") for v in vessels], CACHE_TTL)

    return vessels


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
