"""Submarine cable data service — hybrid fetch with fallback."""

import asyncio
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

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
        try:
            return CableDataset.model_validate(cached)
        except (ValidationError, TypeError):
            logger.warning("cables_cache_snapshot_invalid")
            await cache.delete(CACHE_KEY)

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


def _parse_cables(geojson: dict[str, Any]) -> list[SubmarineCable]:
    """Parse TeleGeography cable GeoJSON into model list."""
    features = _geojson_features(geojson)
    cables: list[SubmarineCable] = []
    invalid_count = 0
    for feature in features:
        try:
            if not isinstance(feature, Mapping):
                raise ValueError("feature must be an object")
            props = feature.get("properties")
            geom = feature.get("geometry")
            if not isinstance(props, Mapping) or not isinstance(geom, Mapping):
                raise ValueError("feature properties and geometry must be objects")
            geom_type = geom.get("type")
            coords = geom.get("coordinates")

            if not coords:
                continue

            if geom_type == "LineString":
                coords = [coords]
            elif geom_type != "MultiLineString":
                continue

            valid_lines = [line for line in coords if _valid_line(line)]
            if not valid_lines:
                raise ValueError("feature contains no valid cable segments")

            cable_id = props.get("id")
            name = props.get("name")
            if (
                not isinstance(cable_id, (str, int))
                or not isinstance(name, str)
                or not name.strip()
            ):
                raise ValueError("cable identity is invalid")
            landing_ids = props.get("landing_points", [])
            if not isinstance(landing_ids, list):
                landing_ids = []
            owners = props.get("owners")
            if isinstance(owners, list):
                owner_values = [
                    owner.strip()
                    for owner in owners
                    if isinstance(owner, str) and owner.strip()
                ]
                owners = ", ".join(owner_values) or None
            elif not isinstance(owners, str):
                owners = None
            raw_rfs = props.get("rfs")
            rfs = raw_rfs.strip() or None if isinstance(raw_rfs, str) else (
                str(raw_rfs) if isinstance(raw_rfs, int) and not isinstance(raw_rfs, bool) else None
            )

            cables.append(
                SubmarineCable(
                    id=str(cable_id),
                    name=name.strip(),
                    color=_parse_color(props.get("color")),
                    is_planned=_parse_bool(props.get("is_planned")),
                    owners=owners.strip() or None if isinstance(owners, str) else None,
                    capacity_tbps=_parse_capacity(props.get("capacity")),
                    length_km=_parse_length(props.get("length")),
                    rfs=rfs,
                    url=props.get("url") if isinstance(props.get("url"), str) else None,
                    landing_point_ids=[str(lp) for lp in landing_ids if isinstance(lp, (str, int))],
                    coordinates=valid_lines,
                )
            )
        except (ValueError, TypeError, OverflowError, ValidationError, KeyError):
            invalid_count += 1
            logger.debug(
                "cable_feature_skipped",
                feature_id=_safe_feature_id(feature),
            )
            continue
    if features and not cables:
        raise ValueError("cable GeoJSON contains no valid features")
    if invalid_count:
        logger.warning("cable_features_invalid", invalid_count=invalid_count)
    return cables


def _parse_landing_points(geojson: dict[str, Any]) -> list[LandingPoint]:
    """Parse TeleGeography landing point GeoJSON into model list."""
    features = _geojson_features(geojson)
    points: list[LandingPoint] = []
    invalid_count = 0
    for feature in features:
        try:
            if not isinstance(feature, Mapping):
                raise ValueError("feature must be an object")
            props = feature.get("properties")
            geom = feature.get("geometry")
            if not isinstance(props, Mapping) or not isinstance(geom, Mapping):
                raise ValueError("feature properties and geometry must be objects")
            coords = geom.get("coordinates")

            if (
                not isinstance(coords, (list, tuple))
                or len(coords) < 2
                or geom.get("type") != "Point"
            ):
                continue

            lp_id = props.get("id")
            name = props.get("name")
            if not isinstance(lp_id, (str, int)) or not isinstance(name, str) or not name.strip():
                raise ValueError("landing point identity is invalid")
            country = props.get("country")
            points.append(
                LandingPoint(
                    id=str(lp_id),
                    name=name.strip(),
                    country=country if isinstance(country, str) else None,
                    latitude=float(coords[1]),
                    longitude=float(coords[0]),
                )
            )
        except (ValueError, TypeError, OverflowError, ValidationError, KeyError):
            invalid_count += 1
            continue
    if features and not points:
        raise ValueError("landing point GeoJSON contains no valid features")
    if invalid_count:
        logger.warning("landing_point_features_invalid", invalid_count=invalid_count)
    return points


def _parse_length(raw: object) -> float | None:
    """Parse a recognized length into km; bare numbers retain the legacy km unit."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    numeric = str(raw).replace(",", "")
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z]*)\s*",
        numeric,
    )
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2).lower()
    if unit not in ("", "km", "kms", "kilometer", "kilometers", "nmi", "nm"):
        return None
    value *= 1.852 if unit in ("nmi", "nm") else 1.0
    return value if math.isfinite(value) and value >= 0 else None


def _parse_capacity(raw: object) -> float | None:
    """Parse recognized capacity units into Tbps; bare numbers retain the legacy unit."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    numeric = str(raw).replace(",", "")
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z/]*)\s*",
        numeric,
    )
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2).lower()
    if unit not in ("", "tbps", "tb/s", "gbps", "gb/s"):
        return None
    value *= 0.001 if unit in ("gbps", "gb/s") else 1.0
    return value if math.isfinite(value) and value >= 0 else None


def _geojson_features(geojson: object) -> list[Any]:
    if not isinstance(geojson, Mapping):
        raise ValueError("GeoJSON root must be an object")
    features = geojson.get("features")
    if not isinstance(features, list):
        raise ValueError("GeoJSON features must be a list")
    return features


def _valid_line(line: object) -> bool:
    if not isinstance(line, list) or len(line) < 2:
        return False
    for point in line:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return False
        try:
            components = [float(component) for component in point]
        except (TypeError, ValueError, OverflowError):
            return False
        if any(not math.isfinite(component) for component in components):
            return False
        lon, lat = components[:2]
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            return False
    return True


def _parse_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no", ""):
            return False
    if raw is not None:
        logger.warning("cable_planned_value_invalid")
    return False


def _safe_feature_id(feature: object) -> str | None:
    if not isinstance(feature, Mapping):
        return None
    props = feature.get("properties")
    if not isinstance(props, Mapping):
        return None
    value = props.get("id")
    return str(value)[:100] if isinstance(value, (str, int)) else None


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _parse_color(raw: object) -> str:
    """Validate hex color, return default on invalid."""
    if raw and isinstance(raw, str) and _HEX_RE.match(raw):
        return raw
    return "#00bcd4"
