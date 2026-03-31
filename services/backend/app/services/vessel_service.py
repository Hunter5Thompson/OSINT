"""Vessel data service — AISStream WebSocket cache + Digitraffic REST fallback."""

import structlog

from app.config import settings
from app.models.vessel import Vessel
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "vessels:all"
CACHE_TTL = 60  # seconds

# Finnish Digitraffic — free, no auth, real-time AIS positions (requires gzip)
DIGITRAFFIC_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"


async def get_vessels(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Vessel]:
    """Return vessels from cache (AISStream WS) or Digitraffic REST fallback."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return [Vessel(**v) for v in cached]

    # Fallback: fetch from Digitraffic
    vessels = await _fetch_digitraffic(proxy)
    if vessels:
        await cache.set(CACHE_KEY, [v.model_dump(mode="json") for v in vessels], CACHE_TTL)

    return vessels


async def _fetch_digitraffic(proxy: ProxyService) -> list[Vessel]:
    """Fetch vessel positions from Finnish Digitraffic AIS API."""
    try:
        # Digitraffic requires Accept-Encoding: gzip
        resp = await proxy.client.get(
            DIGITRAFFIC_URL,
            headers={"Accept-Encoding": "gzip"},
        )
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
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

                vessels.append(
                    Vessel(
                        mmsi=int(mmsi),
                        latitude=float(coords[1]),
                        longitude=float(coords[0]),
                        speed_knots=float(props.get("sog", 0) or 0),
                        course=float(props.get("cog", 0) or 0),
                        ship_type=int(props.get("shipType", 0) or 0),
                    )
                )
            except Exception:
                continue

        logger.info("digitraffic_fetched", count=len(vessels))
        return vessels
    except Exception as exc:
        logger.warning("digitraffic_fetch_failed", error=str(exc))
        return []
