"""Catalog-backed, static spatial-filter plans for CHRONIK reads."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from app.models.spatial import (
    CatalogProblemCode,
    ContainmentDescriptor,
    GeometryDescriptor,
    Lod,
    ScopeKind,
    ScopeNode,
    SpatialCatalogProblem,
    SpatialScopeTokenV1,
)
from app.models.timeline import BBox
from app.services.spatial_catalog import ResolvedSpatialScope, SpatialCatalogLoader

_EPSILON = 1e-12
_GLOBAL_BBOX_PARAMETERS: dict[str, bool | float] = {
    "bbox_off": True,
    "west": -180.0,
    "east": 180.0,
    "south": -90.0,
    "north": 90.0,
}


class TimelineSpatialQueryId(StrEnum):
    """Allowlisted query shapes; catalog data can never supply query text."""

    GLOBAL = "timeline_global_v1"
    BBOX_SINGLE = "timeline_bbox_single_v1"
    BBOX_DATELINE = "timeline_bbox_dateline_v1"


class EventSpatialRelation(StrEnum):
    """Closed event relations supported by CHRONIK spatial templates."""

    OCCURS_IN = "occurs-in"
    INTERSECTS = "intersects"


class UnsupportedExactSpatialQueryError(ValueError):
    """The requested kind/relation pair has no reviewed static exact template."""


@dataclass(frozen=True, slots=True)
class ExactEventQueryTemplates:
    """Complete, immutable Cypher statements for one exact event query shape."""

    samples: str
    count: str


_EVENTS_COUNTRY_SCOPE_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT $limit
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
"""

_EVENTS_COUNTRY_SCOPE_COUNT_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
RETURN count(DISTINCT ev) AS included_count
"""

_EVENTS_ADMIN1_SCOPE_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin1_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT $limit
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
"""

_EVENTS_ADMIN1_SCOPE_COUNT_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin1_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
RETURN count(DISTINCT ev) AS included_count
"""

_EVENTS_ADMIN2_SCOPE_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin2_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT $limit
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
"""

_EVENTS_ADMIN2_SCOPE_COUNT_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin2_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
RETURN count(DISTINCT ev) AS included_count
"""

_EXACT_EVENT_QUERY_REGISTRY: Final[
    Mapping[tuple[ScopeKind, EventSpatialRelation], ExactEventQueryTemplates]
] = MappingProxyType(
    {
        (ScopeKind.COUNTRY, EventSpatialRelation.OCCURS_IN): ExactEventQueryTemplates(
            samples=_EVENTS_COUNTRY_SCOPE_QUERY,
            count=_EVENTS_COUNTRY_SCOPE_COUNT_QUERY,
        ),
        (ScopeKind.ADMIN1, EventSpatialRelation.OCCURS_IN): ExactEventQueryTemplates(
            samples=_EVENTS_ADMIN1_SCOPE_QUERY,
            count=_EVENTS_ADMIN1_SCOPE_COUNT_QUERY,
        ),
        (ScopeKind.ADMIN2, EventSpatialRelation.OCCURS_IN): ExactEventQueryTemplates(
            samples=_EVENTS_ADMIN2_SCOPE_QUERY,
            count=_EVENTS_ADMIN2_SCOPE_COUNT_QUERY,
        ),
    }
)


def exact_event_query_templates(
    scope_kind: ScopeKind,
    relation: EventSpatialRelation,
) -> ExactEventQueryTemplates:
    """Return only a reviewed complete template pair for enum-selected inputs."""

    if not isinstance(scope_kind, ScopeKind) or not isinstance(
        relation,
        EventSpatialRelation,
    ):
        raise UnsupportedExactSpatialQueryError("exact spatial query is unsupported")
    try:
        return _EXACT_EVENT_QUERY_REGISTRY[(scope_kind, relation)]
    except KeyError as exc:
        raise UnsupportedExactSpatialQueryError(
            f"exact event query is unsupported for {scope_kind.value}/{relation.value}"
        ) from exc


@dataclass(frozen=True, slots=True, order=True)
class LongitudeSpan:
    west: float
    east: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.west, bool)
            or isinstance(self.east, bool)
            or not math.isfinite(self.west)
            or not math.isfinite(self.east)
            or not -180 <= self.west <= self.east <= 180
        ):
            raise ValueError("longitude span must be finite and non-wrapping")


@dataclass(frozen=True, slots=True)
class GeoExtent:
    kind: Literal["world", "segments"]
    south: float | None = None
    north: float | None = None
    longitude: tuple[LongitudeSpan, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "world":
            if self.south is not None or self.north is not None or self.longitude:
                raise ValueError("world extent does not carry segment fields")
            return
        if self.kind != "segments":
            raise ValueError("unknown extent kind")
        if (
            self.south is None
            or self.north is None
            or isinstance(self.south, bool)
            or isinstance(self.north, bool)
            or not math.isfinite(self.south)
            or not math.isfinite(self.north)
            or not -90 <= self.south <= self.north <= 90
            or not 1 <= len(self.longitude) <= 2
        ):
            raise ValueError("invalid segmented extent")


@dataclass(frozen=True, slots=True)
class ResolvedSpatialConstraint:
    token: SpatialScopeTokenV1
    extent: GeoExtent
    country_scope_key: str | None
    admin1_scope_key: str | None
    admin2_scope_key: str | None


@dataclass(frozen=True, slots=True)
class CompiledSpatialFilter:
    query_id: TimelineSpatialQueryId
    parameters: Mapping[str, bool | float]
    bbox: BBox | None
    constraint: ResolvedSpatialConstraint | None = None


type CatalogFilterResolution = CompiledSpatialFilter | SpatialCatalogProblem


def compile_extent_filter(
    extent: GeoExtent,
    *,
    constraint: ResolvedSpatialConstraint | None = None,
) -> CompiledSpatialFilter:
    """Project one reviewed extent to the existing timeline BBox convention."""

    if extent.kind == "world":
        return CompiledSpatialFilter(
            query_id=TimelineSpatialQueryId.GLOBAL,
            parameters=dict(_GLOBAL_BBOX_PARAMETERS),
            bbox=None,
            constraint=constraint,
        )

    assert extent.south is not None
    assert extent.north is not None
    spans = tuple(sorted(extent.longitude))
    if len(spans) == 1:
        span = spans[0]
        bbox = BBox(
            west=span.west,
            south=extent.south,
            east=span.east,
            north=extent.north,
        )
        return CompiledSpatialFilter(
            query_id=TimelineSpatialQueryId.BBOX_SINGLE,
            parameters=_bbox_parameters(bbox),
            bbox=bbox,
            constraint=constraint,
        )

    western, eastern = spans
    if (
        not math.isclose(western.west, -180.0, abs_tol=_EPSILON)
        or not math.isclose(eastern.east, 180.0, abs_tol=_EPSILON)
        or western.east >= eastern.west
    ):
        raise ValueError("two-span extent must be a canonical dateline extent")
    bbox = BBox(
        west=eastern.west,
        south=extent.south,
        east=western.east,
        north=extent.north,
    )
    return CompiledSpatialFilter(
        query_id=TimelineSpatialQueryId.BBOX_DATELINE,
        parameters=_bbox_parameters(bbox),
        bbox=bbox,
        constraint=constraint,
    )


def compile_legacy_bbox_filter(bbox: BBox | None) -> CompiledSpatialFilter:
    """Keep the explicit viewport/AOI BBox as a separate, tokenless request mode."""

    if bbox is None:
        return compile_extent_filter(GeoExtent(kind="world"))
    longitude = (
        (LongitudeSpan(bbox.west, bbox.east),)
        if bbox.west <= bbox.east
        else (
            LongitudeSpan(-180.0, bbox.east),
            LongitudeSpan(bbox.west, 180.0),
        )
    )
    return compile_extent_filter(
        GeoExtent(
            kind="segments",
            south=bbox.south,
            north=bbox.north,
            longitude=longitude,
        )
    )


def extent_from_boundary_geometry(payload: bytes | object) -> GeoExtent:
    """Validate a BoundaryGeometryV1 value and derive its circular extent."""

    value = _decode_json(payload)
    geometry = _mapping(value, "boundary geometry")
    if set(geometry) != {"schema_version", "geometry_type", "polygons"}:
        raise ValueError("boundary geometry has unknown or missing fields")
    if geometry.get("schema_version") != 1 or geometry.get("geometry_type") != "MultiPolygon":
        raise ValueError("boundary geometry schema is unsupported")

    polygons = _sequence(geometry.get("polygons"), "polygons")
    if not polygons:
        raise ValueError("boundary geometry has no polygons")
    longitudes: list[float] = []
    latitudes: list[float] = []
    full_longitude = False
    for polygon_index, polygon_value in enumerate(polygons):
        polygon = _sequence(polygon_value, f"polygon[{polygon_index}]")
        if not polygon:
            raise ValueError("polygon has no rings")
        for ring_index, ring_value in enumerate(polygon):
            ring = _sequence(ring_value, f"ring[{ring_index}]")
            if len(ring) < 4:
                raise ValueError("boundary ring is too short")
            positions = tuple(
                _position(position, f"position[{position_index}]")
                for position_index, position in enumerate(ring)
            )
            if positions[0] != positions[-1]:
                raise ValueError("boundary ring is not closed")
            full_longitude = full_longitude or any(
                math.isclose(abs(right[0] - left[0]), 360.0, abs_tol=_EPSILON)
                for left, right in zip(positions, positions[1:], strict=False)
            )
            for position_longitude, latitude in positions[:-1]:
                longitudes.append(position_longitude)
                latitudes.append(latitude)

    if not longitudes or not latitudes:
        raise ValueError("boundary geometry has no positions")
    longitude_spans = (
        (LongitudeSpan(-180.0, 180.0),)
        if full_longitude
        else _minimal_longitude_spans(tuple(longitudes))
    )
    return GeoExtent(
        kind="segments",
        south=min(latitudes),
        north=max(latitudes),
        longitude=longitude_spans,
    )


async def resolve_catalog_filter(
    loader: SpatialCatalogLoader,
    scope_key: str,
    catalog_revision: str,
) -> CatalogFilterResolution:
    """Resolve exactly one catalog token and compile its boundary extent fail-closed."""

    resolved = loader.resolve_scope(scope_key, catalog_revision)
    if isinstance(resolved, SpatialCatalogProblem):
        return resolved

    record = resolved.record
    token = SpatialScopeTokenV1(
        scope_key=record.scope.key,
        kind=record.scope.kind,
        catalog_revision=resolved.catalog_revision,
        derivation_revision=record.derivation_revision,
        boundary_policy=resolved.boundary_policy,
        compatible_derivation_revisions=record.compatible_derivation_revisions,
    )
    if token.kind is ScopeKind.WORLD:
        extent = GeoExtent(kind="world")
        constraint = _constraint(token, extent, resolved.path)
        return compile_extent_filter(extent, constraint=constraint)

    try:
        extent_or_problem = await _resolve_non_global_extent(loader, resolved)
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return _filter_unavailable(scope_key, catalog_revision)
    if isinstance(extent_or_problem, SpatialCatalogProblem):
        return extent_or_problem
    constraint = _constraint(token, extent_or_problem, resolved.path)
    try:
        return compile_extent_filter(extent_or_problem, constraint=constraint)
    except ValueError:
        return _filter_unavailable(scope_key, catalog_revision)


async def _resolve_non_global_extent(
    loader: SpatialCatalogLoader,
    resolved: ResolvedSpatialScope,
) -> GeoExtent | SpatialCatalogProblem:
    record = resolved.record
    revision = resolved.catalog_revision
    presentation = record.presentation

    descriptor: GeometryDescriptor | ContainmentDescriptor | None = presentation.containment
    if descriptor is None and presentation.outline_lods:
        descriptor = _preferred_or_first_descriptor(
            presentation.outline_lods,
            presentation.preferred_lod,
        )
    if descriptor is not None:
        payload = await _read_catalog_asset(loader, revision, descriptor.asset_id)
        if isinstance(payload, SpatialCatalogProblem):
            return payload
        return extent_from_boundary_geometry(payload)

    parent_key = record.scope.parent_key
    if parent_key is None:
        raise ValueError("non-global scope has no parent geometry source")
    parent = loader.get_scope(revision, parent_key)
    if isinstance(parent, SpatialCatalogProblem):
        return parent
    parent_presentation = parent.presentation
    descriptor = _preferred_or_first_descriptor(
        parent_presentation.children_lods,
        parent_presentation.preferred_lod,
    )
    payload = await _read_catalog_asset(loader, revision, descriptor.asset_id)
    if isinstance(payload, SpatialCatalogProblem):
        return payload
    return _extent_from_boundary_pack(
        payload,
        parent_scope_key=parent_key,
        scope_key=record.scope.key,
    )


async def _read_catalog_asset(
    loader: SpatialCatalogLoader,
    revision: str,
    asset_id: str,
) -> bytes | SpatialCatalogProblem:
    asset = loader.get_asset(revision, asset_id)
    if isinstance(asset, SpatialCatalogProblem):
        return asset
    return await loader.read_asset(asset)


def _preferred_or_first_descriptor(
    descriptors: Mapping[Lod, GeometryDescriptor],
    preferred: Lod | None,
) -> GeometryDescriptor:
    if preferred is not None:
        descriptor = descriptors.get(preferred)
        if descriptor is not None:
            return descriptor
    if not descriptors:
        raise ValueError("catalog scope has no boundary descriptor")
    first_key = min(descriptors, key=str)
    return descriptors[first_key]


def _extent_from_boundary_pack(
    payload: bytes,
    *,
    parent_scope_key: str,
    scope_key: str,
) -> GeoExtent:
    pack = _mapping(_decode_json(payload), "boundary pack")
    if set(pack) != {"schema_version", "parent_scope_key", "features"}:
        raise ValueError("boundary pack has unknown or missing fields")
    if pack.get("schema_version") != 1 or pack.get("parent_scope_key") != parent_scope_key:
        raise ValueError("boundary pack identity is invalid")
    features = _sequence(pack.get("features"), "features")
    for feature_value in features:
        feature = _mapping(feature_value, "boundary feature")
        if feature.get("kind") != "scope" or feature.get("scope_key") != scope_key:
            continue
        if set(feature) != {"kind", "scope_key", "label", "geometry"}:
            raise ValueError("scope feature has unknown or missing fields")
        return extent_from_boundary_geometry(feature.get("geometry"))
    raise ValueError("scope geometry is absent from its parent boundary pack")


def _constraint(
    token: SpatialScopeTokenV1,
    extent: GeoExtent,
    path: Sequence[ScopeNode],
) -> ResolvedSpatialConstraint:
    keys_by_kind = {
        node.kind: str(node.key)
        for node in path
    }
    return ResolvedSpatialConstraint(
        token=token,
        extent=extent,
        country_scope_key=keys_by_kind.get(ScopeKind.COUNTRY),
        admin1_scope_key=keys_by_kind.get(ScopeKind.ADMIN1),
        admin2_scope_key=keys_by_kind.get(ScopeKind.ADMIN2),
    )


def _bbox_parameters(bbox: BBox) -> dict[str, bool | float]:
    return {
        "bbox_off": False,
        "west": bbox.west,
        "east": bbox.east,
        "south": bbox.south,
        "north": bbox.north,
    }


def _minimal_longitude_spans(longitudes: tuple[float, ...]) -> tuple[LongitudeSpan, ...]:
    angles = sorted({(longitude + 180) % 360 for longitude in longitudes})
    if len(angles) == 1:
        longitude = _clean_longitude(angles[0] - 180)
        return (LongitudeSpan(longitude, longitude),)
    gaps = [
        (((angles[(index + 1) % len(angles)] - angle) % 360), index)
        for index, angle in enumerate(angles)
    ]
    _, gap_index = max(gaps, key=lambda item: (item[0], -item[1]))
    start_angle = angles[(gap_index + 1) % len(angles)]
    end_angle = angles[gap_index]
    if end_angle < start_angle:
        end_angle += 360
    west = _clean_longitude(start_angle - 180)
    east_unwrapped = end_angle - 180
    if east_unwrapped <= 180 + _EPSILON:
        return (LongitudeSpan(west, _clean_longitude(min(east_unwrapped, 180))),)
    return (
        LongitudeSpan(-180.0, _clean_longitude(east_unwrapped - 360)),
        LongitudeSpan(west, 180.0),
    )


def _position(value: object, context: str) -> tuple[float, float]:
    position = _sequence(value, context)
    if len(position) != 2:
        raise ValueError(f"{context} must have two coordinates")
    longitude = _finite_number(position[0], f"{context}.longitude")
    latitude = _finite_number(position[1], f"{context}.latitude")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"{context} is outside WGS84 ranges")
    return longitude, latitude


def _finite_number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{context} must be finite")
    return converted


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return value


def _sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{context} must be an array")
    return value


def _decode_json(payload: bytes | object) -> object:
    if isinstance(payload, bytes):
        return json.loads(payload)
    return payload


def _clean_longitude(value: float) -> float:
    value = round(value, 12)
    if math.isclose(value, -180.0, abs_tol=_EPSILON):
        return -180.0
    if math.isclose(value, 180.0, abs_tol=_EPSILON):
        return 180.0
    return 0.0 if math.isclose(value, 0.0, abs_tol=_EPSILON) else value


def _filter_unavailable(scope_key: str, revision: str) -> SpatialCatalogProblem:
    return SpatialCatalogProblem(
        code=CatalogProblemCode.SPATIAL_FILTER_UNAVAILABLE,
        message="Spatial timeline filter is unavailable",
        target=scope_key,
        recoverable=True,
        active_catalog_revision=revision,
    )
