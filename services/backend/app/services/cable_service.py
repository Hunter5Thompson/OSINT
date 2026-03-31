"""Submarine cable data service — hybrid fetch with fallback."""

import asyncio
import json
import re
from pathlib import Path

import structlog

from app.config import settings
from app.models.cable import CableDataset, LandingPoint, SubmarineCable
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()

CACHE_KEY = "submarine:dataset:v1"
FALLBACK_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "submarine-fallback.json"


async def get_cable_dataset(
    proxy: ProxyService,
    cache: CacheService,
) -> CableDataset:
    """Return cable dataset from cache, live fetch, or bundled fallback."""
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return CableDataset(**cached)

    dataset = await _fetch_live(proxy)
    if dataset is None:
        dataset = _load_fallback()

    await cache.set(CACHE_KEY, dataset.model_dump(mode="json"), settings.cable_cache_ttl_s)
    return dataset


async def _fetch_live(proxy: ProxyService) -> CableDataset | None:
    """Fetch both GeoJSON files from TeleGeography (concurrent, 15s timeout)."""
    try:
        cable_geojson, lp_geojson = await asyncio.wait_for(
            asyncio.gather(
                proxy.get_json(settings.cable_geo_url),
                proxy.get_json(settings.landing_point_geo_url),
            ),
            timeout=15.0,
        )

        cables = _parse_cables(cable_geojson)
        landing_points = _parse_landing_points(lp_geojson)

        logger.info("cables_fetched_live", cable_count=len(cables), lp_count=len(landing_points))
        return CableDataset(cables=cables, landing_points=landing_points, source="live")
    except Exception as exc:
        logger.warning("cables_live_fetch_failed", error=str(exc))
        return None


def _load_fallback() -> CableDataset:
    """Load bundled fallback JSON (raw GeoJSON format, same as live)."""
    try:
        raw = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
        cables = _parse_cables(raw.get("cables_geojson", {}))
        landing_points = _parse_landing_points(raw.get("landing_points_geojson", {}))
        logger.info("cables_loaded_fallback", cable_count=len(cables), lp_count=len(landing_points))
        return CableDataset(cables=cables, landing_points=landing_points, source="fallback")
    except Exception:
        logger.error("cables_fallback_load_failed")
        return CableDataset(cables=[], landing_points=[], source="fallback")


def _parse_cables(geojson: dict) -> list[SubmarineCable]:
    """Parse TeleGeography cable GeoJSON into model list."""
    cables: list[SubmarineCable] = []
    for feature in geojson.get("features", []):
        try:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            geom_type = geom.get("type")
            coords = geom.get("coordinates")

            if not coords:
                continue

            # Normalize LineString to MultiLineString
            if geom_type == "LineString":
                coords = [coords]
            elif geom_type != "MultiLineString":
                continue

            cables.append(
                SubmarineCable(
                    id=str(props.get("id", "")),
                    name=props.get("name", "Unknown"),
                    color=_parse_color(props.get("color")),
                    is_planned=bool(props.get("is_planned", False)),
                    owners=props.get("owners"),
                    capacity_tbps=_parse_capacity(props.get("capacity")),
                    length_km=_parse_length(props.get("length")),
                    rfs=str(props.get("rfs")) if props.get("rfs") else None,
                    url=props.get("url"),
                    landing_point_ids=[str(lp) for lp in props.get("landing_points", [])],
                    coordinates=coords,
                )
            )
        except Exception:
            logger.debug("cable_feature_skipped", feature_id=feature.get("properties", {}).get("id"))
            continue
    return cables


def _parse_landing_points(geojson: dict) -> list[LandingPoint]:
    """Parse TeleGeography landing point GeoJSON into model list."""
    points: list[LandingPoint] = []
    for feature in geojson.get("features", []):
        try:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates")

            if not coords or geom.get("type") != "Point" or len(coords) < 2:
                continue

            points.append(
                LandingPoint(
                    id=str(props.get("id", "")),
                    name=props.get("name", "Unknown"),
                    country=props.get("country"),
                    latitude=float(coords[1]),
                    longitude=float(coords[0]),
                )
            )
        except Exception:
            continue
    return points


def _parse_length(raw: object) -> float | None:
    """Parse length string like '1,234 km' or '1234' to float km."""
    if raw is None:
        return None
    text = str(raw).lower().replace(",", "").replace("km", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_capacity(raw: object) -> float | None:
    """Parse capacity to float Tbps. Best-effort."""
    if raw is None:
        return None
    text = str(raw).lower().replace(",", "").replace("tbps", "").replace("tb/s", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _parse_color(raw: object) -> str:
    """Validate hex color, return default on invalid."""
    if raw and isinstance(raw, str) and _HEX_RE.match(raw):
        return raw
    return "#00bcd4"
