"""Flight data service - fetches from OpenSky Network and adsb.fi."""

import math
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError

from app.config import settings
from app.models.flight import Aircraft
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "flights:all"

# Longer prefixes first so REACH wins over RCH and the suffix is a digit, not HAWKER.
_MILITARY_CALLSIGN_PREFIXES = tuple(
    sorted(
        (
            "RCH",
            "EVAC",
            "DUKE",
            "VALOR",
            "REACH",
            "FORGE",
            "COBRA",
            "HAWK",
            "VIPER",
            "RAPTOR",
            "REAPER",
            "SIGINT",
            "FORTE",
            "NCHO",
            "TOPCAT",
            "RRR",  # Royal Air Force
            "IAM",  # Italian Air Force
            "GAF",  # German Air Force
            "FAF",  # French Air Force
            "CNV",  # US Navy
            "RFR",  # French Air Force
        ),
        key=len,
        reverse=True,
    )
)

# FR24 public feed URL (no auth needed)
_FR24_URL = (
    "https://data-cloud.flightradar24.com/zones/fcgi/feed.js"
    "?faa=1&satellite=1&mlat=1&adsb=1&gnd=0&air=1&vehicles=0"
    "&estimated=0&maxage=14400&gliders=0&stats=0"
)


def _is_military_callsign(callsign: str | None) -> bool:
    """Military when the prefix is the whole token or is followed by a number.

    ``HAWK12`` matches. ``HAWKER`` does not: the letters after the prefix belong
    to a different callsign.
    """
    if not isinstance(callsign, str):
        return False
    normalized = callsign.strip().upper()
    if not normalized:
        return False
    for prefix in _MILITARY_CALLSIGN_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        rest = normalized[len(prefix) :].lstrip(" -")
        if rest == "" or rest[0].isdigit():
            return True
    return False


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


def _measurement(value: object) -> float | None:
    """A finite number, or None for missing/blank/invalid. Never invents 0."""
    if value is None or value == "":
        return None
    return _finite_number(value)


def _is_ground(value: object) -> bool:
    """The ground sentinel is a string; numbers (including 0) are altitudes."""
    return isinstance(value, str) and value.strip().lower() == "ground"


def _optional_callsign(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _aircraft_from_cache(cached: object) -> list[Aircraft] | None:
    if not isinstance(cached, list) or not cached:
        return None
    aircraft: list[Aircraft] = []
    for item in cached:
        if not isinstance(item, dict):
            continue
        try:
            aircraft.append(Aircraft.model_validate(item))
        except ValidationError:
            continue
    return aircraft or None


async def get_flights(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Aircraft]:
    """Fetch flight data: cache, then adsb.fi, OpenSky, and the FR24 public feed.

    A single malformed aircraft is skipped. The function raises only when every
    source failed at the transport layer, so the router can answer 502 instead of
    an empty globe.
    """
    fresh = _aircraft_from_cache(await cache.get(CACHE_KEY))
    if fresh is not None:
        return fresh

    saw_payload = False
    last_error: Exception | None = None
    for fetcher in (_fetch_adsb_fi, _fetch_opensky, _fetch_fr24):
        try:
            aircraft = await fetcher(proxy)
        except Exception as exc:
            last_error = exc
            logger.warning("flight_source_failed", source=fetcher.__name__, error=str(exc))
            continue
        saw_payload = True
        if aircraft:
            await cache.set(
                CACHE_KEY,
                [item.model_dump(mode="json") for item in aircraft],
                settings.flight_cache_ttl_s,
            )
            return aircraft
    if not saw_payload and last_error is not None:
        raise last_error
    return []


def _parse_adsb_aircraft(ac: object) -> Aircraft | None:
    if not isinstance(ac, dict):
        return None
    lat = _finite_degrees(ac.get("lat"), limit=90)
    lon = _finite_degrees(ac.get("lon"), limit=180)
    if lat is None or lon is None:
        return None
    icao = ac.get("hex")
    if not isinstance(icao, str) or not icao.strip():
        return None
    raw_alt = ac.get("alt_baro")
    on_ground = _is_ground(raw_alt)
    altitude_feet = _measurement(raw_alt) if not on_ground else None
    if altitude_feet is None and not on_ground:
        altitude_feet = _measurement(ac.get("alt_geom"))
    if on_ground:
        altitude_m: float | None = 0.0
    else:
        altitude_m = None if altitude_feet is None else altitude_feet * 0.3048
    speed_knots = _measurement(ac.get("gs"))
    heading = _measurement(ac.get("track"))
    vertical_fpm = _measurement(ac.get("baro_rate"))
    raw_flags = ac.get("dbFlags", 0)
    try:
        db_flags = int(raw_flags or 0)
    except (TypeError, ValueError):
        db_flags = 0
    callsign = _optional_callsign(ac.get("flight"))
    aircraft_type = ac.get("t")
    return Aircraft(
        icao24=icao.strip(),
        callsign=callsign,
        latitude=lat,
        longitude=lon,
        altitude_m=altitude_m,
        velocity_ms=None if speed_knots is None else speed_knots * 0.5144,
        heading=heading,
        vertical_rate=None if vertical_fpm is None else vertical_fpm * 0.00508,
        on_ground=on_ground,
        is_military=bool(db_flags & 1) or _is_military_callsign(callsign),
        aircraft_type=aircraft_type if isinstance(aircraft_type, str) else None,
    )


async def _fetch_adsb_fi(proxy: ProxyService) -> list[Aircraft]:
    """Fetch from adsb.fi. Transport errors propagate; bad rows are skipped."""
    data = await proxy.get_json(settings.adsb_fi_api_url)
    ac_list = data.get("ac", []) if isinstance(data, dict) else []
    if not isinstance(ac_list, list):
        return []
    aircraft = [parsed for item in ac_list if (parsed := _parse_adsb_aircraft(item)) is not None]
    logger.info("adsb_fi_fetched", count=len(aircraft))
    return aircraft


def _parse_opensky_state(state: object) -> Aircraft | None:
    if not isinstance(state, list) or len(state) < 12:
        return None
    lat = _finite_degrees(state[6], limit=90)
    lon = _finite_degrees(state[5], limit=180)
    if lat is None or lon is None or not state[0]:
        return None
    callsign = _optional_callsign(state[1])
    altitude = _measurement(state[7])
    if altitude is None and len(state) > 13:
        altitude = _measurement(state[13])
    speed = _measurement(state[9])
    heading = _measurement(state[10])
    vertical = _measurement(state[11])
    # Field contract: index 4 is last_contact. Never substitute time_position.
    last_contact: datetime | None = None
    raw_contact = _measurement(state[4])
    if raw_contact is not None:
        try:
            last_contact = datetime.fromtimestamp(raw_contact, tz=UTC)
        except (OSError, OverflowError, ValueError):
            last_contact = None
    return Aircraft(
        icao24=str(state[0]),
        callsign=callsign,
        longitude=lon,
        latitude=lat,
        altitude_m=altitude,
        velocity_ms=speed,
        heading=heading,
        vertical_rate=vertical,
        on_ground=state[8] is True or state[8] == 1,
        last_contact=last_contact,
        is_military=_is_military_callsign(callsign),
    )


async def _fetch_opensky(proxy: ProxyService) -> list[Aircraft]:
    """Fetch from OpenSky Network API."""
    auth = None
    if settings.opensky_user and settings.opensky_pass:
        auth = (settings.opensky_user, settings.opensky_pass)
    data = await proxy.get_json(settings.opensky_api_url, auth=auth)
    states = data.get("states", []) if isinstance(data, dict) else []
    if not isinstance(states, list):
        return []
    aircraft = [parsed for state in states if (parsed := _parse_opensky_state(state)) is not None]
    logger.info("opensky_fetched", count=len(aircraft))
    return aircraft


def _parse_fr24_row(val: object) -> Aircraft | None:
    if not isinstance(val, list) or len(val) < 15:
        return None
    lat = _finite_degrees(val[1], limit=90)
    lon = _finite_degrees(val[2], limit=180)
    if lat is None or lon is None or val[0] is None:
        return None
    callsign_raw = val[16] if len(val) > 16 else val[13]
    callsign = _optional_callsign(callsign_raw)
    on_ground = _is_ground(val[4])
    if on_ground:
        altitude_m: float | None = 0.0
    else:
        altitude_feet = _measurement(val[4])
        altitude_m = None if altitude_feet is None else altitude_feet * 0.3048
    speed_knots = _measurement(val[5])
    heading = _measurement(val[3])
    aircraft_type = val[8] if len(val) > 8 and isinstance(val[8], str) and val[8] else None
    return Aircraft(
        icao24=str(val[0]),
        callsign=callsign,
        latitude=lat,
        longitude=lon,
        altitude_m=altitude_m,
        velocity_ms=None if speed_knots is None else speed_knots * 0.5144,
        heading=heading,
        vertical_rate=None,
        on_ground=on_ground,
        is_military=_is_military_callsign(callsign),
        aircraft_type=aircraft_type,
    )


async def _fetch_fr24(proxy: ProxyService) -> list[Aircraft]:
    """Fetch from the FR24 public feed. Transport errors propagate."""
    resp = await proxy.client.get(
        _FR24_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return []
    aircraft = [parsed for val in data.values() if (parsed := _parse_fr24_row(val)) is not None]
    logger.info("fr24_fetched", count=len(aircraft))
    return aircraft
