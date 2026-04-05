"""Satellite TLE data service - fetches from CelesTrak."""

import math
import re

import structlog

from app.config import settings
from app.models.satellite import Satellite
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

# Name prefix → ISO 3166-1 alpha-2 country code
_COUNTRY_PREFIXES: dict[str, str] = {
    "USA ": "US", "NROL": "US", "NOSS": "US", "GPS ": "US", "NAVSTAR": "US",
    "DSP ": "US", "SBIRS": "US", "WGS ": "US", "GOES": "US", "NOAA": "US",
    "MILSTAR": "US", "AEHF": "US", "MUOS": "US", "TDRS": "US",
    "COSMOS": "RU", "GLONASS": "RU", "MOLNIYA": "RU",
    "YAOGAN": "CN", "CZ-": "CN", "BEIDOU": "CN", "FENGYUN": "CN", "TIANGONG": "CN",
    "GALILEO": "EU", "METEOSAT": "EU",
    "HIMAWARI": "JP", "QZS": "JP",
    "ASTRA": "LU",
    "INTELSAT": "INT", "IRIDIUM": "US", "STARLINK": "US", "ONEWEB": "GB",
}


def _detect_country(name: str) -> str | None:
    """Detect operator country from satellite name prefix."""
    upper = name.upper()
    for prefix, country in _COUNTRY_PREFIXES.items():
        if upper.startswith(prefix) or f" {prefix}" in upper:
            return country
    if "ISS" in upper:
        return "INT"
    return None


def _detect_type(name: str, category: str) -> str:
    """Detect satellite type from name + existing category."""
    upper = name.upper()
    if category == "military":
        # Sub-classify military — recon or comms (no generic "military" value)
        if any(k in upper for k in ("NROL", "USA ", "NOSS", "YAOGAN", "COSMOS 25")):
            return "recon"
        if any(k in upper for k in ("MILSTAR", "AEHF", "MUOS", "WGS", "DSCS")):
            return "comms"
        return "recon"  # conservative: unclassified mil → recon
    if category == "gps":
        return "gps"
    if category == "weather":
        return "weather"
    if category == "station":
        return "station"
    if any(k in upper for k in ("INTELSAT", "ASTRA", "SES", "VIASAT", "STARLINK", "ONEWEB", "IRIDIUM", "TDRS")):
        return "comms"
    return "unknown"


CACHE_KEY = "satellites:tle"
CACHE_TTL = 3600  # 1 hour


async def get_satellites(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Satellite]:
    """Fetch satellite TLE data, cached for 1 hour."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return [Satellite(**s) for s in cached]

    satellites = await _fetch_celestrak(proxy)
    if satellites:
        await cache.set(
            CACHE_KEY, [s.model_dump(mode="json") for s in satellites], CACHE_TTL
        )

    return satellites


async def _fetch_celestrak(proxy: ProxyService) -> list[Satellite]:
    """Fetch TLE data from CelesTrak."""
    try:
        text = await proxy.get_text(settings.celestrak_api_url)
        lines = text.strip().split("\n")
        satellites: list[Satellite] = []

        i = 0
        while i + 2 < len(lines):
            name = lines[i].strip()
            line1 = lines[i + 1].strip()
            line2 = lines[i + 2].strip()

            if not line1.startswith("1 ") or not line2.startswith("2 "):
                i += 1
                continue

            norad_match = re.match(r"2\s+(\d+)", line2)
            norad_id = int(norad_match.group(1)) if norad_match else 0

            incl_match = re.search(r"^\d\s+\d+\s+([\d.]+)", line2)
            inclination = float(incl_match.group(1)) if incl_match else 0.0

            mean_motion_match = re.search(r"([\d.]+)\s*\d*$", line2)
            mean_motion = float(mean_motion_match.group(1)) if mean_motion_match else 0.0
            period = (1440.0 / mean_motion) if mean_motion > 0 else 0.0

            category = _categorize(name, inclination)
            operator_country = _detect_country(name)
            sat_type = _detect_type(name, category)

            satellites.append(
                Satellite(
                    norad_id=norad_id,
                    name=name,
                    tle_line1=line1,
                    tle_line2=line2,
                    category=category,
                    inclination_deg=round(inclination, 2),
                    period_min=round(period, 2),
                    operator_country=operator_country,
                    satellite_type=sat_type,
                )
            )
            i += 3

        logger.info("celestrak_fetched", count=len(satellites))
        return satellites
    except Exception:
        logger.warning("celestrak_fetch_failed")
        return []


def _categorize(name: str, inclination: float) -> str:
    """Categorize satellite based on name and orbit parameters."""
    name_upper = name.upper()
    if any(k in name_upper for k in ("USA ", "NROL", "NOSS", "MILSTAR", "DSP", "SBIRS", "WGS", "YAOGAN", "COSMOS 2")):
        return "military"
    if any(k in name_upper for k in ("NOAA", "METEO", "GOES", "HIMAWARI", "FENGYUN")):
        return "weather"
    if any(k in name_upper for k in ("GPS", "NAVSTAR", "GLONASS", "GALILEO", "BEIDOU")):
        return "gps"
    if any(k in name_upper for k in ("ISS", "TIANGONG", "CSS")):
        return "station"
    if math.isclose(inclination, 0.0, abs_tol=5.0):
        return "geo"
    return "active"
