"""Earthquake data service - fetches from USGS GeoJSON feed."""

import math
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError

from app.config import settings
from app.models.earthquake import Earthquake
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "earthquakes:4.5_week"
CACHE_TTL = 300  # 5 minutes


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


def _truthy_flag(value: object) -> bool:
    """USGS sends 0/1. The string '0' is not a tsunami."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _parse_feature(feature: object) -> Earthquake | None:
    if not isinstance(feature, dict):
        return None
    feature_id = feature.get("id")
    if not isinstance(feature_id, str) or not feature_id:
        return None
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    longitude = _finite_degrees(coords[0], limit=180)
    latitude = _finite_degrees(coords[1], limit=90)
    if latitude is None or longitude is None:
        return None
    if len(coords) > 2 and coords[2] is not None:
        depth = _finite_number(coords[2])
        if depth is None:
            return None
    else:
        depth = 0.0
    props = feature.get("properties")
    if not isinstance(props, dict):
        props = {}
    magnitude = _finite_number(props.get("mag"))
    raw_time = _finite_number(props.get("time"))
    if magnitude is None or raw_time is None:
        return None
    try:
        when = datetime.fromtimestamp(raw_time / 1000, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None
    place = props.get("place")
    url = props.get("url")
    return Earthquake(
        id=feature_id,
        longitude=longitude,
        latitude=latitude,
        depth_km=depth,
        magnitude=magnitude,
        place=place if isinstance(place, str) and place else "Unknown",
        time=when,
        tsunami=_truthy_flag(props.get("tsunami", 0)),
        url=url if isinstance(url, str) else None,
    )


def _earthquakes_from_cache(cached: object) -> list[Earthquake] | None:
    if not isinstance(cached, list) or not cached:
        return None
    earthquakes: list[Earthquake] = []
    for item in cached:
        if not isinstance(item, dict):
            continue
        try:
            earthquakes.append(Earthquake.model_validate(item))
        except ValidationError:
            continue
    return earthquakes or None


async def get_earthquakes(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Earthquake]:
    """Fetch earthquake data from USGS, cached for 5 minutes.

    Transport failures propagate. One bad GeoJSON feature does not drop the rest.
    """
    fresh = _earthquakes_from_cache(await cache.get(CACHE_KEY))
    if fresh is not None:
        return fresh

    earthquakes = await _fetch_usgs(proxy)
    if earthquakes:
        await cache.set(
            CACHE_KEY, [item.model_dump(mode="json") for item in earthquakes], CACHE_TTL
        )
    return earthquakes


async def _fetch_usgs(proxy: ProxyService) -> list[Earthquake]:
    """Fetch from USGS GeoJSON feed."""
    data = await proxy.get_json(settings.usgs_api_url)
    features = data.get("features", []) if isinstance(data, dict) else []
    if not isinstance(features, list):
        return []
    earthquakes = [
        parsed for feature in features if (parsed := _parse_feature(feature)) is not None
    ]
    logger.info("usgs_fetched", count=len(earthquakes), skipped=len(features) - len(earthquakes))
    return earthquakes
