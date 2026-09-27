"""Satellite TLE data service - fetches from CelesTrak."""

import math
import re

import structlog
from pydantic import ValidationError

from app.models.satellite import Satellite
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

# Name prefix → ISO 3166-1 alpha-2 country code (no trailing spaces!)
_COUNTRY_PREFIXES: dict[str, str] = {
    "USA": "US", "NROL": "US", "NOSS": "US", "GPS": "US", "NAVSTAR": "US",
    "DSP": "US", "SBIRS": "US", "WGS": "US", "GOES": "US", "NOAA": "US",
    "MILSTAR": "US", "AEHF": "US", "MUOS": "US", "TDRS": "US",
    "COSMOS": "RU", "GLONASS": "RU", "MOLNIYA": "RU",
    "YAOGAN": "CN", "CZ-": "CN", "BEIDOU": "CN", "FENGYUN": "CN", "TIANGONG": "CN",
    "GALILEO": "EU", "METEOSAT": "EU",
    "HIMAWARI": "JP", "QZS": "JP",
    "ASTRA": "LU",
    "INTELSAT": "INT", "IRIDIUM": "US", "STARLINK": "US", "ONEWEB": "GB",
}


_COUNTRY_PREFIX_ITEMS = tuple(
    sorted(_COUNTRY_PREFIXES.items(), key=lambda item: len(item[0]), reverse=True)
)
_MILITARY_PREFIXES = (
    "MILSTAR",
    "YAOGAN",
    "COSMOS",
    "SBIRS",
    "NROL",
    "NOSS",
    "USA",
    "DSP",
    "WGS",
)
_RECON_PREFIXES = ("YAOGAN", "COSMOS", "NROL", "NOSS", "USA")


def _has_prefix_token(name: str, prefix: str) -> bool:
    """True when ``prefix`` starts the name and the next character is not a letter."""
    upper = name.upper()
    token = prefix.upper()
    if not upper.startswith(token):
        return False
    rest = upper[len(token) :]
    return not rest or not rest[0].isalpha()


def _has_word(name: str, word: str) -> bool:
    return word.upper() in re.split(r"[^A-Z0-9]+", name.upper())


def _detect_country(name: str) -> str | None:
    """Detect operator country from a name prefix or a whole token.

    ``ISS`` matches the station. ``SWISSCUBE`` and ``MISSION`` do not.
    """
    for prefix, country in _COUNTRY_PREFIX_ITEMS:
        if _has_prefix_token(name, prefix):
            return country
    if _has_word(name, "ISS"):
        return "INT"
    return None


def _detect_type(name: str, category: str) -> str:
    """Detect satellite type from name + existing category."""
    upper = name.upper()
    if category == "military":
        if any(_has_prefix_token(name, prefix) for prefix in _RECON_PREFIXES):
            return "recon"
        if any(token in upper for token in ("MILSTAR", "AEHF", "MUOS", "WGS", "DSCS")):
            return "comms"
        return "recon"
    if category == "gps":
        return "gps"
    if category == "weather":
        return "weather"
    if category == "station":
        return "station"
    if any(
        k in upper
        for k in ("INTELSAT", "ASTRA", "SES", "VIASAT", "STARLINK", "ONEWEB", "IRIDIUM", "TDRS")
    ):
        return "comms"
    return "unknown"


CACHE_KEY = "satellites:tle"
CACHE_TTL = 7200  # 2 hours — CelesTrak updates every 2h

# Targeted groups first. ``active`` is always merged afterwards and deduped by
# NORAD id; a failure on that large group does not discard the targeted sets.
_CELESTRAK_GROUPS = [
    "stations", "military", "weather", "science",
    "gps-ops", "galileo", "beidou", "glonass-operational",
    "starlink", "oneweb", "iridium-NEXT",
    "geo", "intelsat", "ses",
    "active",
]

_CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"


def _satellites_from_cache(cached: object) -> list[Satellite] | None:
    if not isinstance(cached, list) or not cached:
        return None
    satellites: list[Satellite] = []
    for item in cached:
        if not isinstance(item, dict):
            continue
        try:
            satellites.append(Satellite.model_validate(item))
        except ValidationError:
            continue
    return satellites or None


async def get_satellites(
    proxy: ProxyService,
    cache: CacheService,
) -> list[Satellite]:
    """Fetch satellite TLE data, cached for 2 hours."""
    fresh = _satellites_from_cache(await cache.get(CACHE_KEY))
    if fresh is not None:
        return fresh

    satellites = await _fetch_celestrak_groups(proxy)
    if satellites:
        await cache.set(
            CACHE_KEY, [s.model_dump(mode="json") for s in satellites], CACHE_TTL
        )

    return satellites


def _celestrak_text_unusable(text: str) -> bool:
    """Skip error pages. A real TLE set is kept even if a name contains ``error``."""
    if "not updated" in text.lower():
        return True
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("1 ") or stripped.startswith("2 "):
            return False
    lowered = text.lower()
    return "error" in lowered or "invalid" in lowered or not text.strip()


async def _fetch_celestrak_groups(proxy: ProxyService) -> list[Satellite]:
    """Fetch TLE data from multiple CelesTrak groups for broad coverage."""
    all_sats: dict[int, Satellite] = {}  # dedup by NORAD ID
    failures = 0
    last_error: Exception | None = None

    for group in _CELESTRAK_GROUPS:
        url = f"{_CELESTRAK_BASE}?GROUP={group}&FORMAT=tle"
        try:
            text = await proxy.get_text(url)
        except Exception as exc:
            failures += 1
            last_error = exc
            logger.debug("celestrak_group_failed", group=group)
            continue

        if _celestrak_text_unusable(text):
            logger.debug("celestrak_group_unavailable", group=group)
            continue

        parsed = _parse_tle_text(text)
        for sat in parsed:
            if sat.norad_id not in all_sats:
                all_sats[sat.norad_id] = sat
        logger.info("celestrak_group_fetched", group=group, count=len(parsed))

    if not all_sats and failures == len(_CELESTRAK_GROUPS) and last_error is not None:
        raise last_error

    satellites = list(all_sats.values())
    logger.info("celestrak_total", count=len(satellites), groups_tried=len(_CELESTRAK_GROUPS))
    return satellites


def _parse_tle_text(text: str) -> list[Satellite]:
    """Parse TLE text into Satellite objects."""
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
        if norad_match is None:
            i += 3
            continue
        norad_id = int(norad_match.group(1))
        if norad_id <= 0:
            i += 3
            continue

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

    return satellites


def _categorize(name: str, inclination: float) -> str:
    """Categorize satellite based on name and orbit parameters."""
    if any(_has_prefix_token(name, prefix) for prefix in _MILITARY_PREFIXES):
        return "military"
    name_upper = name.upper()
    if any(token in name_upper for token in ("NOAA", "METEO", "GOES", "HIMAWARI", "FENGYUN")):
        return "weather"
    if any(token in name_upper for token in ("GPS", "NAVSTAR", "GLONASS", "GALILEO", "BEIDOU")):
        return "gps"
    if any(_has_word(name, word) for word in ("ISS", "TIANGONG", "CSS")):
        return "station"
    if math.isclose(inclination, 0.0, abs_tol=5.0):
        return "geo"
    return "active"
