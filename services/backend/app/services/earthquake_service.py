"""Earthquake data service - fetches from USGS GeoJSON feed."""

from datetime import datetime, timezone

import structlog

from app.config import settings
from app.models.earthquake import Earthquake
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "earthquakes:4.5_week"
CACHE_TTL = 300  # 5 minutes


async def get_earthquakes(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Earthquake]:
    """Fetch earthquake data from USGS, cached for 5 minutes."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return [Earthquake(**e) for e in cached]

    earthquakes = await _fetch_usgs(proxy)
    if earthquakes:
        await cache.set(
            CACHE_KEY, [e.model_dump(mode="json") for e in earthquakes], CACHE_TTL
        )

    return earthquakes


async def _fetch_usgs(proxy: ProxyService) -> list[Earthquake]:
    """Fetch from USGS GeoJSON feed."""
    try:
        data = await proxy.get_json(settings.usgs_api_url)
        features = data.get("features", [])

        earthquakes: list[Earthquake] = []
        for f in features:
            props = f.get("properties", {})
            coords = f.get("geometry", {}).get("coordinates", [0, 0, 0])

            earthquakes.append(
                Earthquake(
                    id=f.get("id", ""),
                    longitude=float(coords[0]),
                    latitude=float(coords[1]),
                    depth_km=float(coords[2]) if len(coords) > 2 else 0.0,
                    magnitude=float(props.get("mag", 0)),
                    place=props.get("place", "Unknown"),
                    time=datetime.fromtimestamp(
                        props.get("time", 0) / 1000, tz=timezone.utc
                    ),
                    tsunami=bool(props.get("tsunami", 0)),
                    url=props.get("url"),
                )
            )

        logger.info("usgs_fetched", count=len(earthquakes))
        return earthquakes
    except Exception:
        logger.warning("usgs_fetch_failed")
        return []
