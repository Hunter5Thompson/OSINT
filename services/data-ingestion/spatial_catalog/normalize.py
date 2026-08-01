"""Pure strict normalization for ODIN boundary geometry.

The public seam accepts only GeoJSON Polygon or MultiPolygon geometry objects and
returns one immutable normal form.  File IO, source identity, and Pydantic contracts
stay outside this module.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from shapely import affinity
from shapely.geometry import (
    GeometryCollection,
    MultiPolygon,
    Polygon,
    box,
)
from shapely.geometry import (
    LinearRing as ShapelyLinearRing,
)
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity

type Position = tuple[float, float]
type LinearRing = tuple[Position, ...]
type PolygonCoordinates = tuple[LinearRing, ...]
type MultiPolygonCoordinates = tuple[PolygonCoordinates, ...]

_EPSILON = 1e-12


class GeometryValidationError(ValueError):
    """A source geometry cannot enter the reviewed ODIN normal form."""


@dataclass(frozen=True, slots=True)
class BoundaryGeometry:
    """Canonical in-memory representation shared by build stages."""

    polygons: MultiPolygonCoordinates
    full_longitude: bool = False

    schema_version: ClassVar[int] = 1
    geometry_type: ClassVar[str] = "MultiPolygon"

    def to_wire(self) -> dict[str, object]:
        """Return the exact BoundaryGeometryV1 value (without build metadata)."""

        return {
            "schema_version": self.schema_version,
            "geometry_type": self.geometry_type,
            "polygons": [
                [
                    [[longitude, latitude] for longitude, latitude in ring]
                    for ring in polygon
                ]
                for polygon in self.polygons
            ],
        }


def signed_ring_area(ring: Sequence[Position]) -> float:
    """Return planar signed area; positive is counter-clockwise."""

    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(ring, ring[1:], strict=False)
    )


def normalize_geometry(raw: object, *, precision: int = 6) -> BoundaryGeometry:
    """Strictly parse and canonicalize a GeoJSON Polygon or MultiPolygon.

    The function never repairs topology.  Closure, orientation, duplicate removal,
    precision quantization, and dateline cutting are deterministic representation
    steps; invalid topology raises a stable error code.
    """

    if not 0 <= precision <= 12:
        raise ValueError("precision must be between 0 and 12")
    if not isinstance(raw, Mapping) or set(raw) != {"type", "coordinates"}:
        raise _error("INVALID_GEOMETRY", "expected exact type/coordinates object")

    geometry_type = raw.get("type")
    coordinates = raw.get("coordinates")
    if geometry_type == "Polygon":
        polygon_values = _expect_sequence(coordinates, "Polygon coordinates")
    elif geometry_type == "MultiPolygon":
        polygon_values = _expect_sequence(coordinates, "MultiPolygon coordinates")
    else:
        raise _error("INVALID_GEOMETRY", "only Polygon and MultiPolygon are accepted")

    raw_polygons = (
        (polygon_values,)
        if geometry_type == "Polygon"
        else tuple(_expect_sequence(value, "polygon coordinates") for value in polygon_values)
    )
    if not raw_polygons:
        raise _error("INVALID_GEOMETRY", "geometry must contain at least one polygon")

    normalized: list[PolygonCoordinates] = []
    full_longitude = False
    for polygon_index, polygon_value in enumerate(raw_polygons):
        polygon, polygon_is_full = _normalize_polygon(
            polygon_value,
            precision=precision,
            context=f"polygon[{polygon_index}]",
        )
        full_longitude = full_longitude or polygon_is_full
        normalized.extend(
            _split_and_encode_polygon(
                polygon,
                precision=precision,
                full_longitude=polygon_is_full,
            )
        )

    if not normalized:
        raise _error("DEGENERATE_AREA", "normalization produced no polygon area")
    normalized.sort(key=_polygon_sort_key)
    return BoundaryGeometry(polygons=tuple(normalized), full_longitude=full_longitude)


def _normalize_polygon(
    raw: Sequence[object],
    *,
    precision: int,
    context: str,
) -> tuple[Polygon, bool]:
    if not raw:
        raise _error("INVALID_GEOMETRY", f"{context} has no outer ring")

    parsed_rings: list[LinearRing] = []
    full_longitude = False
    for ring_index, raw_ring in enumerate(raw):
        ring_values = _expect_sequence(raw_ring, f"{context}.ring[{ring_index}]")
        parsed = _parse_ring(ring_values, precision=precision)
        full_longitude = full_longitude or _has_full_longitude_edge(parsed)
        unwrapped = _unwrap_ring(parsed)
        if ring_index:
            unwrapped = _align_ring(unwrapped, anchor=_mean_longitude(parsed_rings[0]))
        _validate_ring(unwrapped)
        parsed_rings.append(unwrapped)

    shell, *holes = parsed_rings
    polygon = Polygon(shell, holes)
    if polygon.is_empty or polygon.area <= _EPSILON:
        raise _error("DEGENERATE_AREA", f"{context} has no area")
    if not polygon.is_valid:
        reason = explain_validity(polygon)
        if "Hole lies outside shell" in reason:
            raise _error("ORPHAN_HOLE", reason)
        if "Self-intersection" in reason or "Ring Self-intersection" in reason:
            raise _error("SELF_INTERSECTION", reason)
        raise _error("INVALID_TOPOLOGY", reason)
    return polygon, full_longitude


def _parse_ring(raw: Sequence[object], *, precision: int) -> LinearRing:
    positions = [_parse_position(value, precision=precision) for value in raw]
    deduplicated = _remove_consecutive_duplicates(positions)
    if deduplicated and deduplicated[0] != deduplicated[-1]:
        deduplicated.append(deduplicated[0])
    deduplicated = _remove_consecutive_duplicates(deduplicated)
    if len(deduplicated) < 4 or len(set(deduplicated[:-1])) < 3:
        raise _error("DEGENERATE_RING", "ring needs three distinct positions and closure")
    return tuple(deduplicated)


def _parse_position(raw: object, *, precision: int) -> Position:
    if (
        not isinstance(raw, Sequence)
        or isinstance(raw, (str, bytes, bytearray))
        or len(raw) != 2
    ):
        raise _error("INVALID_GEOMETRY", "position must contain exactly two numbers")
    longitude = _coordinate(raw[0])
    latitude = _coordinate(raw[1])
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise _error("NON_FINITE_COORDINATE", "coordinates must be finite")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise _error("COORDINATE_RANGE", "coordinate is outside longitude/latitude range")
    return (_round_coordinate(longitude, precision), _round_coordinate(latitude, precision))


def _coordinate(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _error("INVALID_GEOMETRY", "coordinate must be a JSON number")
    return float(raw)


def _round_coordinate(value: float, precision: int) -> float:
    rounded = round(value, precision)
    return 0.0 if rounded == 0 else rounded


def _expect_sequence(raw: object, context: str) -> tuple[object, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise _error("INVALID_GEOMETRY", f"{context} must be an array")
    return tuple(raw)


def _remove_consecutive_duplicates(positions: Sequence[Position]) -> list[Position]:
    result: list[Position] = []
    for position in positions:
        if not result or result[-1] != position:
            result.append(position)
    return result


def _unwrap_ring(ring: LinearRing) -> LinearRing:
    result = [ring[0]]
    previous_raw = ring[0][0]
    for longitude, latitude in ring[1:]:
        raw_delta = longitude - previous_raw
        candidate = longitude
        if not math.isclose(abs(raw_delta), 360.0, abs_tol=_EPSILON):
            while candidate - result[-1][0] > 180:
                candidate -= 360
            while candidate - result[-1][0] < -180:
                candidate += 360
        result.append((candidate, latitude))
        previous_raw = longitude
    return tuple(result)


def _align_ring(ring: LinearRing, *, anchor: float) -> LinearRing:
    mean = _mean_longitude(ring)
    shift = round((anchor - mean) / 360) * 360
    return tuple((longitude + shift, latitude) for longitude, latitude in ring)


def _mean_longitude(ring: LinearRing) -> float:
    return sum(longitude for longitude, _ in ring[:-1]) / (len(ring) - 1)


def _has_full_longitude_edge(ring: LinearRing) -> bool:
    return any(
        math.isclose(abs(right[0] - left[0]), 360.0, abs_tol=_EPSILON)
        for left, right in zip(ring, ring[1:], strict=False)
    )


def _validate_ring(ring: LinearRing) -> None:
    if _all_positions_collinear(ring[:-1]):
        raise _error("DEGENERATE_RING", "ring has zero area")
    if not ShapelyLinearRing(ring).is_simple:
        raise _error("SELF_INTERSECTION", "ring crosses itself")
    if abs(signed_ring_area(ring)) <= _EPSILON:
        raise _error("DEGENERATE_RING", "ring has zero area")


def _all_positions_collinear(positions: Sequence[Position]) -> bool:
    first, second, *remaining = positions
    return all(
        math.isclose(
            (second[0] - first[0]) * (position[1] - first[1])
            - (second[1] - first[1]) * (position[0] - first[0]),
            0.0,
            abs_tol=_EPSILON,
        )
        for position in remaining
    )


def _split_and_encode_polygon(
    polygon: Polygon,
    *,
    precision: int,
    full_longitude: bool,
) -> list[PolygonCoordinates]:
    min_x, _, max_x, _ = polygon.bounds
    if full_longitude or (min_x >= -180 and max_x <= 180):
        pieces = [polygon]
    else:
        pieces = []
        first_window = math.floor((min_x + 180) / 360)
        last_window = math.floor((max_x + 180 - _EPSILON) / 360)
        for window in range(first_window, last_window + 1):
            west = -180 + 360 * window
            east = 180 + 360 * window
            clipped = polygon.intersection(box(west, -90, east, 90))
            for piece in _polygon_members(clipped):
                if piece.area > _EPSILON:
                    pieces.append(affinity.translate(piece, xoff=-360 * window))

    encoded = [_encode_polygon(piece, precision=precision) for piece in pieces]
    return [polygon_value for polygon_value in encoded if polygon_value]


def _polygon_members(geometry: object) -> tuple[Polygon, ...]:
    if isinstance(geometry, Polygon):
        return (geometry,)
    if isinstance(geometry, MultiPolygon):
        return tuple(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return tuple(member for member in geometry.geoms if isinstance(member, Polygon))
    return ()


def _encode_polygon(polygon: Polygon, *, precision: int) -> PolygonCoordinates:
    oriented = orient(polygon, sign=1.0)
    outer = _canonical_ring(oriented.exterior.coords, precision=precision, clockwise=False)
    holes = sorted(
        (
            _canonical_ring(interior.coords, precision=precision, clockwise=True)
            for interior in oriented.interiors
        ),
        key=_ring_sort_key,
    )
    encoded = (outer, *holes)
    validation = Polygon(encoded[0], encoded[1:])
    if validation.is_empty or validation.area <= _EPSILON:
        raise _error("DEGENERATE_AREA", "quantized polygon has no area")
    if not validation.is_valid:
        raise _error("INVALID_TOPOLOGY", explain_validity(validation))
    return encoded


def _canonical_ring(
    raw: Sequence[Sequence[float]],
    *,
    precision: int,
    clockwise: bool,
) -> LinearRing:
    positions = [
        (
            _round_coordinate(_clamp_longitude(float(value[0])), precision),
            _round_coordinate(float(value[1]), precision),
        )
        for value in raw
    ]
    positions = _remove_consecutive_duplicates(positions)
    if positions[0] != positions[-1]:
        positions.append(positions[0])
    if len(positions) < 4 or abs(signed_ring_area(positions)) <= _EPSILON:
        raise _error("DEGENERATE_RING", "quantized ring is degenerate")
    is_clockwise = signed_ring_area(positions) < 0
    if is_clockwise != clockwise:
        positions = list(reversed(positions))

    body = positions[:-1]
    first_index = min(range(len(body)), key=lambda index: (body[index], index))
    body = body[first_index:] + body[:first_index]
    body.append(body[0])
    return tuple(body)


def _clamp_longitude(value: float) -> float:
    if math.isclose(value, -180.0, abs_tol=_EPSILON):
        return -180.0
    if math.isclose(value, 180.0, abs_tol=_EPSILON):
        return 180.0
    if not -180 < value < 180:
        raise _error("COORDINATE_RANGE", "dateline split produced invalid longitude")
    return value


def _ring_sort_key(ring: LinearRing) -> tuple[Position, ...]:
    return ring


def _polygon_sort_key(polygon: PolygonCoordinates) -> tuple[object, ...]:
    return (polygon[0], tuple(polygon[1:]))


def _error(code: str, detail: str) -> GeometryValidationError:
    return GeometryValidationError(f"{code}: {detail}")
