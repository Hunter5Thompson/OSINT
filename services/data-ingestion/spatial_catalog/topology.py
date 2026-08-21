"""Pure longitude topology, extents, and containment helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from spatial_catalog.normalize import BoundaryGeometry, LinearRing, Position

_EPSILON = 1e-12


@dataclass(frozen=True, slots=True, order=True)
class LongitudeSpan:
    west: float
    east: float

    def __post_init__(self) -> None:
        if not -180 <= self.west <= self.east <= 180:
            raise ValueError("longitude span must be non-wrapping within [-180, 180]")


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
        if self.south is None or self.north is None or not 1 <= len(self.longitude) <= 2:
            raise ValueError("segment extent requires latitude and one/two longitude spans")
        if not -90 <= self.south <= self.north <= 90:
            raise ValueError("invalid latitude extent")


def calculate_extent(
    geometry: BoundaryGeometry | None,
    *,
    world: bool = False,
) -> GeoExtent:
    """Calculate minimal circular longitude coverage via the largest gap."""

    if world:
        return GeoExtent(kind="world")
    if geometry is None or not geometry.polygons:
        raise ValueError("non-world extent requires geometry")

    positions = tuple(
        position
        for polygon in geometry.polygons
        for ring in polygon
        for position in ring[:-1]
    )
    south = min(latitude for _, latitude in positions)
    north = max(latitude for _, latitude in positions)
    if geometry.full_longitude:
        longitude = (LongitudeSpan(-180.0, 180.0),)
    else:
        longitude = _minimal_longitude_spans(tuple(value[0] for value in positions))
    return GeoExtent(kind="segments", south=south, north=north, longitude=longitude)


def unwrap_query_and_ring(
    query_longitude: float,
    ring: LinearRing,
) -> tuple[float, LinearRing]:
    """Move a query and ring onto one continuous longitude axis."""

    if not math.isfinite(query_longitude) or not -180 <= query_longitude <= 180:
        raise ValueError("query coordinate is outside longitude range")
    if not ring:
        raise ValueError("ring must not be empty")

    unwrapped: list[Position] = [ring[0]]
    for longitude, latitude in ring[1:]:
        candidate = longitude
        while candidate - unwrapped[-1][0] > 180:
            candidate -= 360
        while candidate - unwrapped[-1][0] < -180:
            candidate += 360
        unwrapped.append((candidate, latitude))

    mean = sum(longitude for longitude, _ in unwrapped[:-1]) / (len(unwrapped) - 1)
    query = query_longitude + round((mean - query_longitude) / 360) * 360
    return query, tuple(unwrapped)


def contains_point(
    geometry: BoundaryGeometry,
    *,
    longitude: float,
    latitude: float,
) -> bool:
    """Run Outer/Hole ray casts after query/ring longitude unwrapping."""

    if (
        not math.isfinite(longitude)
        or not math.isfinite(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
    ):
        raise ValueError("query coordinate is non-finite or out of range")

    for polygon in geometry.polygons:
        outer_query, outer = unwrap_query_and_ring(longitude, polygon[0])
        if not _point_in_ring(outer_query, latitude, outer):
            continue
        if any(
            _point_in_ring(*_query_for_hole(longitude, latitude, hole))
            for hole in polygon[1:]
        ):
            continue
        return True
    return False


def _query_for_hole(
    longitude: float,
    latitude: float,
    hole: LinearRing,
) -> tuple[float, float, LinearRing]:
    query, unwrapped = unwrap_query_and_ring(longitude, hole)
    return query, latitude, unwrapped


def _point_in_ring(longitude: float, latitude: float, ring: LinearRing) -> bool:
    inside = False
    for left, right in zip(ring, ring[1:], strict=False):
        if _point_on_segment((longitude, latitude), left, right):
            return True
        crosses = (left[1] > latitude) != (right[1] > latitude)
        if crosses:
            crossing_longitude = left[0] + (latitude - left[1]) * (
                right[0] - left[0]
            ) / (right[1] - left[1])
            if longitude < crossing_longitude:
                inside = not inside
    return inside


def _point_on_segment(point: Position, left: Position, right: Position) -> bool:
    cross = (point[0] - left[0]) * (right[1] - left[1]) - (
        point[1] - left[1]
    ) * (right[0] - left[0])
    if not math.isclose(cross, 0.0, abs_tol=_EPSILON):
        return False
    return (
        min(left[0], right[0]) - _EPSILON
        <= point[0]
        <= max(left[0], right[0]) + _EPSILON
        and min(left[1], right[1]) - _EPSILON
        <= point[1]
        <= max(left[1], right[1]) + _EPSILON
    )


def _minimal_longitude_spans(longitudes: tuple[float, ...]) -> tuple[LongitudeSpan, ...]:
    angles = sorted({(longitude + 180) % 360 for longitude in longitudes})
    if len(angles) == 1:
        longitude = _clean_longitude(angles[0] - 180)
        return (LongitudeSpan(longitude, longitude),)

    gaps = [
        (
            (angles[(index + 1) % len(angles)] - angle) % 360,
            index,
        )
        for index, angle in enumerate(angles)
    ]
    _, gap_index = max(gaps, key=lambda item: (item[0], -item[1]))
    start_angle = angles[(gap_index + 1) % len(angles)]
    end_angle = angles[gap_index]
    if end_angle < start_angle or gap_index == len(angles) - 1:
        end_angle += 360

    west = _clean_longitude(start_angle - 180)
    east_unwrapped = end_angle - 180
    if east_unwrapped <= 180 + _EPSILON:
        return (LongitudeSpan(west, _clean_longitude(min(east_unwrapped, 180))),)
    eastern_end = _clean_longitude(east_unwrapped - 360)
    return (
        LongitudeSpan(-180.0, eastern_end),
        LongitudeSpan(west, 180.0),
    )


def _clean_longitude(value: float) -> float:
    if math.isclose(value, -180.0, abs_tol=_EPSILON):
        return -180.0
    if math.isclose(value, 180.0, abs_tol=_EPSILON):
        return 180.0
    return 0.0 if math.isclose(value, 0.0, abs_tol=_EPSILON) else value
