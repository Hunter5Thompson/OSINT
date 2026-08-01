from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from spatial_catalog.normalize import (
    GeometryValidationError,
    normalize_geometry,
    signed_ring_area,
)

FIXTURES = Path(__file__).parent / "fixtures" / "spatial_catalog"


def _feature_geometry(feature_id: str) -> object:
    payload = json.loads((FIXTURES / "geometry_cases.geojson").read_text(encoding="utf-8"))
    return next(
        feature["geometry"]
        for feature in payload["features"]
        if feature["id"] == feature_id
    )


def test_open_reversed_duplicate_ring_is_canonicalized_at_six_decimals() -> None:
    raw = {
        "type": "Polygon",
        "coordinates": [[
            [0.00000049, 0.00000049],
            [0.00000049, 2.00000049],
            [2.00000049, 2.00000049],
            [2.00000049, 2.00000049],
            [2.00000049, 0.00000049],
        ]],
    }

    geometry = normalize_geometry(raw, precision=6)

    ring = geometry.polygons[0][0]
    assert ring[0] == ring[-1]
    assert len(ring) == 5
    assert ring[0] == (0.0, 0.0)
    assert signed_ring_area(ring) > 0
    assert all(round(lon, 6) == lon and round(lat, 6) == lat for lon, lat in ring)


def test_holes_are_clockwise_and_must_be_inside_their_outer_ring() -> None:
    geometry = normalize_geometry(
        {
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]],
                [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]],
            ],
        }
    )

    outer, hole = geometry.polygons[0]
    assert signed_ring_area(outer) > 0
    assert signed_ring_area(hole) < 0

    with pytest.raises(GeometryValidationError, match="ORPHAN_HOLE"):
        normalize_geometry(
            {
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
                    [[3, 3], [3, 4], [4, 4], [4, 3], [3, 3]],
                ],
            }
        )


@pytest.mark.parametrize(
    ("coordinates", "error_code"),
    [
        ([[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]], "SELF_INTERSECTION"),
        ([[0, 0], [1, 0], [2, 0], [0, 0]], "DEGENERATE_RING"),
        ([[181, 0], [182, 0], [182, 1], [181, 0]], "COORDINATE_RANGE"),
        ([[0, 91], [1, 89], [0, 89], [0, 91]], "COORDINATE_RANGE"),
        ([[0, 0], [math.inf, 0], [0, 1], [0, 0]], "NON_FINITE_COORDINATE"),
    ],
)
def test_invalid_geometry_fails_without_undocumented_repair(
    coordinates: list[list[float]],
    error_code: str,
) -> None:
    with pytest.raises(GeometryValidationError, match=error_code):
        normalize_geometry({"type": "Polygon", "coordinates": [coordinates]})


@pytest.mark.parametrize("feature_id", ["fiji", "aleutians", "russia", "antarctica"])
def test_mandatory_dateline_and_polar_fixtures_normalize(feature_id: str) -> None:
    geometry = normalize_geometry(_feature_geometry(feature_id))

    assert geometry.polygons
    assert all(
        -180 <= lon <= 180 and -90 <= lat <= 90
        for polygon in geometry.polygons
        for ring in polygon
        for lon, lat in ring
    )
    assert all(ring[0] == ring[-1] for polygon in geometry.polygons for ring in polygon)


def test_dateline_polygon_is_split_without_losing_its_hole() -> None:
    geometry = normalize_geometry(_feature_geometry("dateline-hole"))

    assert len(geometry.polygons) == 2
    assert sum(len(polygon) - 1 for polygon in geometry.polygons) == 2
    assert all(
        max(lon for lon, _ in ring) - min(lon for lon, _ in ring) <= 2
        for polygon in geometry.polygons
        for ring in polygon
    )


def test_polygon_and_multipolygon_share_one_multi_polygon_normal_form() -> None:
    polygon = normalize_geometry(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
    )
    multipolygon = normalize_geometry(_feature_geometry("multipolygon"))

    assert len(polygon.polygons) == 1
    assert len(multipolygon.polygons) == 2


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        {"type": "Polygon", "coordinates": "not-an-array"},
        {"type": "Polygon", "coordinates": [[[0, 0, 5], [1, 0], [0, 1], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[True, 0], [1, 0], [0, 1], [True, 0]]]},
    ],
)
def test_parser_accepts_only_strict_polygon_wire_shapes(raw: object) -> None:
    with pytest.raises(GeometryValidationError, match="INVALID_GEOMETRY"):
        normalize_geometry(raw)
