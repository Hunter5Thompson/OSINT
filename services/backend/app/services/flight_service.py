"""Flight data service - fetches from OpenSky Network and adsb.fi."""

from datetime import datetime, timezone

import structlog

from app.config import settings
from app.models.flight import Aircraft
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "flights:all"


async def get_flights(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Aircraft]:
    """Fetch flight data, trying cache first, then OpenSky, then adsb.fi."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return [Aircraft(**a) for a in cached]

    aircraft = await _fetch_opensky(proxy)
    if not aircraft:
        aircraft = await _fetch_adsb_fi(proxy)

    if aircraft:
        await cache.set(
            CACHE_KEY,
            [a.model_dump(mode="json") for a in aircraft],
            settings.flight_cache_ttl_s,
        )

    return aircraft


async def _fetch_opensky(proxy: ProxyService) -> list[Aircraft]:
    """Fetch from OpenSky Network API."""
    try:
        auth = None
        if settings.opensky_user and settings.opensky_pass:
            auth = (settings.opensky_user, settings.opensky_pass)

        data = await proxy.get_json(settings.opensky_api_url, auth=auth)
        states = data.get("states", [])
        if not states:
            return []

        aircraft: list[Aircraft] = []
        for s in states:
            if s[6] is None or s[5] is None:
                continue
            aircraft.append(
                Aircraft(
                    icao24=s[0],
                    callsign=(s[1] or "").strip() or None,
                    longitude=float(s[5]),
                    latitude=float(s[6]),
                    altitude_m=float(s[7] or 0),
                    velocity_ms=float(s[9] or 0),
                    heading=float(s[10] or 0),
                    vertical_rate=float(s[11] or 0),
                    on_ground=bool(s[8]),
                    last_contact=datetime.fromtimestamp(s[4] or 0, tz=timezone.utc),
                )
            )
        logger.info("opensky_fetched", count=len(aircraft))
        return aircraft
    except Exception:
        logger.warning("opensky_fetch_failed")
        return []


async def _fetch_adsb_fi(proxy: ProxyService) -> list[Aircraft]:
    """Fallback: fetch from adsb.fi API."""
    try:
        data = await proxy.get_json(settings.adsb_fi_api_url)
        ac_list = data.get("ac", [])

        aircraft: list[Aircraft] = []
        for ac in ac_list:
            lat = ac.get("lat")
            lon = ac.get("lon")
            if lat is None or lon is None:
                continue
            raw_db_flags = ac.get("dbFlags", 0)
            try:
                db_flags = int(raw_db_flags or 0)
            except (TypeError, ValueError):
                db_flags = 0
            aircraft.append(
                Aircraft(
                    icao24=ac.get("hex", ""),
                    callsign=ac.get("flight", "").strip() or None,
                    latitude=float(lat),
                    longitude=float(lon),
                    altitude_m=float(ac.get("alt_baro", 0) or 0) * 0.3048,
                    velocity_ms=float(ac.get("gs", 0) or 0) * 0.5144,
                    heading=float(ac.get("track", 0) or 0),
                    vertical_rate=float(ac.get("baro_rate", 0) or 0) * 0.00508,
                    on_ground=ac.get("alt_baro") == "ground",
                    is_military=bool(db_flags & 1),
                    aircraft_type=ac.get("t"),
                )
            )
        logger.info("adsb_fi_fetched", count=len(aircraft))
        return aircraft
    except Exception:
        logger.warning("adsb_fi_fetch_failed")
        return []
