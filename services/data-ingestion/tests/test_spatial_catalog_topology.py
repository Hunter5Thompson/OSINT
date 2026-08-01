from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from spatial_catalog.lod import (
    LOD_POLICIES,
    BoundaryFeature,
    ContainmentBudgetError,
    LodBudgetError,
    PinnedTopologyTool,
    assert_shared_borders_preserved,
    build_containment,
    collect_protected_positions,
    dissolve_complete_children,
    load_topology_output,
    prepare_topology_tool,
    run_topology_tool,
    validate_lod_features,
    vertex_count,
)
from spatial_catalog.normalize import normalize_geometry
from spatial_catalog.topology import (
    GeoExtent,
    LongitudeSpan,
    calculate_extent,
    contains_point,
    unwrap_query_and_ring,
)

FIXTURES = Path(__file__).parent / "fixtures" / "spatial_catalog"
MAPSHAPER_BUNDLE = (
    Path(__file__).parents[1]
    / "spatial_catalog"
    / "data"
    / "mapshaper-0.7.49-offline.tgz"
)
MAPSHAPER_BUNDLE_SHA256 = "68b39a96791d6e62b51163e8e39f1f32ba55c0d3b9fbceade58ad07db7dae8f1"


def _feature_geometry(feature_id: str):
    payload = json.loads((FIXTURES / "geometry_cases.geojson").read_text(encoding="utf-8"))
    raw = next(
        feature["geometry"]
        for feature in payload["features"]
        if feature["id"] == feature_id
    )
    return normalize_geometry(raw)


def test_extent_uses_largest_longitude_gap_for_179_minus_179() -> None:
    geometry = normalize_geometry(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [[[-180, -1], [-179, -1], [-179, 1], [-180, 1], [-180, -1]]],
                [[[179, -1], [180, -1], [180, 1], [179, 1], [179, -1]]],
            ],
        }
    )

    assert calculate_extent(geometry) == GeoExtent(
        kind="segments",
        south=-1.0,
        north=1.0,
        longitude=(LongitudeSpan(-180.0, -179.0), LongitudeSpan(179.0, 180.0)),
    )


@pytest.mark.parametrize("feature_id", ["fiji", "aleutians", "russia"])
def test_dateline_fixture_extent_has_two_non_wrapping_spans(feature_id: str) -> None:
    extent = calculate_extent(_feature_geometry(feature_id))

    assert extent.kind == "segments"
    assert len(extent.longitude) == 2
    assert all(span.west <= span.east for span in extent.longitude)


def test_non_global_polar_scope_can_use_full_longitude_span() -> None:
    extent = calculate_extent(_feature_geometry("antarctica"))

    assert extent == GeoExtent(
        kind="segments",
        south=-90.0,
        north=-80.0,
        longitude=(LongitudeSpan(-180.0, 180.0),),
    )


def test_world_extent_is_explicit_not_a_magic_bbox() -> None:
    assert calculate_extent(None, world=True) == GeoExtent(kind="world")


def test_query_and_ring_unwrap_into_same_continuous_domain() -> None:
    ring = ((179.0, -1.0), (-179.0, -1.0), (-179.0, 1.0), (179.0, 1.0), (179.0, -1.0))

    query_lon, unwrapped = unwrap_query_and_ring(-179.5, ring)

    assert query_lon == pytest.approx(180.5)
    assert (
        max(
            abs(right[0] - left[0])
            for left, right in zip(unwrapped, unwrapped[1:], strict=False)
        )
        <= 180
    )


def test_point_containment_handles_dateline_and_holes() -> None:
    geometry = _feature_geometry("dateline-hole")

    assert contains_point(geometry, longitude=179.2, latitude=1.5)
    assert contains_point(geometry, longitude=-179.2, latitude=1.5)
    assert not contains_point(geometry, longitude=179.5, latitude=0.0)
    assert not contains_point(geometry, longitude=-179.5, latitude=0.0)
    assert not contains_point(geometry, longitude=0.0, latitude=0.0)


def test_point_containment_rejects_non_finite_or_out_of_range_query() -> None:
    geometry = _feature_geometry("multipolygon")

    with pytest.raises(ValueError, match="query coordinate"):
        contains_point(geometry, longitude=181, latitude=0)


def _shared_border_features() -> tuple[BoundaryFeature, ...]:
    payload = json.loads((FIXTURES / "shared_border.geojson").read_text(encoding="utf-8"))
    return tuple(
        BoundaryFeature(
            feature_id=feature["id"],
            geometry=normalize_geometry(feature["geometry"]),
        )
        for feature in payload["features"]
    )


def test_shared_border_is_preserved_and_complete_children_dissolve_parent() -> None:
    children = _shared_border_features()

    assert_shared_borders_preserved(children, children)
    parent = dissolve_complete_children(children)

    assert len(parent.polygons) == 1
    assert vertex_count(parent) == 7
    assert contains_point(parent, longitude=0.5, latitude=0.5)
    assert contains_point(parent, longitude=1.5, latitude=0.5)

    broken = (
        children[0],
        BoundaryFeature(
            feature_id="right",
            geometry=normalize_geometry(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[1.1, 0], [2, 0], [2, 1], [1.1, 1], [1.1, 0]]
                    ],
                }
            ),
        ),
    )
    with pytest.raises(LodBudgetError, match="SHARED_BORDER_DRIFT"):
        assert_shared_borders_preserved(children, broken)


def test_junction_island_enclave_and_policy_anchors_are_protected() -> None:
    children = _shared_border_features()
    complex_feature = BoundaryFeature(
        feature_id="islands",
        geometry=normalize_geometry(
            {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [[10, 10], [14, 10], [14, 14], [10, 14], [10, 10]],
                        [[11, 11], [11, 12], [12, 12], [12, 11], [11, 11]],
                    ],
                    [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]],
                ],
            }
        ),
    )

    protected = collect_protected_positions(
        (*children, complex_feature),
        policy_marked={(14.0, 14.0)},
    )

    assert (1.0, 0.5) in protected  # shared-border junction
    assert (20.0, 20.0) in protected  # island anchor
    assert (11.0, 11.0) in protected  # enclave/hole anchor
    assert (14.0, 14.0) in protected  # reviewed policy anchor


def test_lod_validation_enforces_vertex_error_and_protected_position_budgets() -> None:
    feature = BoundaryFeature(
        feature_id="scope",
        geometry=normalize_geometry(
            {
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [0.5, 0.0001], [1, 0], [1, 1], [0, 1], [0, 0]]
                ],
            }
        ),
    )
    simplified = BoundaryFeature(
        feature_id="scope",
        geometry=normalize_geometry(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            }
        ),
    )

    metrics = validate_lod_features(
        (feature,),
        (simplified,),
        policy=LOD_POLICIES["regional"],
    )
    assert metrics.vertex_count == 5
    assert 10 < metrics.max_error_m < 12

    with pytest.raises(LodBudgetError, match="PROTECTED_POSITION_LOST"):
        validate_lod_features(
            (feature,),
            (simplified,),
            policy=LOD_POLICIES["regional"],
            protected_positions={(0.5, 0.0001)},
        )

    impossible_policy = LOD_POLICIES["regional"].with_limits(max_vertices=4)
    with pytest.raises(LodBudgetError, match="LOD_VERTEX_BUDGET"):
        validate_lod_features((feature,), (simplified,), policy=impossible_policy)

    impossible_ring_policy = LOD_POLICIES["regional"].with_limits(max_ring_vertices=4)
    with pytest.raises(LodBudgetError, match="LOD_RING_VERTEX_BUDGET"):
        validate_lod_features((feature,), (simplified,), policy=impossible_ring_policy)


def test_containment_is_independent_six_decimal_geometry_with_strict_failure() -> None:
    source = normalize_geometry(
        {
            "type": "Polygon",
            "coordinates": [
                [[0.0000004, 0], [1, 0], [1, 1], [0, 1], [0.0000004, 0]]
            ],
        },
        precision=7,
    )

    result = build_containment(source, max_vertices=10, strict=True)

    assert result is not None
    assert result.max_error_m <= 50
    assert result.boundary_uncertain_m == result.max_error_m
    assert result.geometry.polygons[0][0][0][0] == 0.0

    with pytest.raises(ContainmentBudgetError, match="STRICT_CONTAINMENT_UNAVAILABLE"):
        build_containment(source, max_vertices=4, strict=True)
    assert build_containment(source, max_vertices=4, strict=False) is None


def test_pinned_tool_adapter_is_offline_explicit_and_byte_deterministic(tmp_path: Path) -> None:
    archive = tmp_path / "mapshaper.tgz"
    archive.write_bytes(b"reviewed-mapshaper-archive")
    executable = tmp_path / "mapshaper"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, shutil, sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('0.7.49')\n"
        "    raise SystemExit(0)\n"
        "assert os.environ['npm_config_offline'] == 'true'\n"
        "assert os.environ['NO_PROXY'] == '*'\n"
        "assert '-simplify' in sys.argv and '-o' in sys.argv\n"
        "shutil.copyfile(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[-1]))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    tool = PinnedTopologyTool(
        executable=executable,
        source_archive=archive,
        expected_version="0.7.49",
        expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    source = FIXTURES / "shared_border.geojson"
    first = tmp_path / "first.geojson"
    second = tmp_path / "second.geojson"

    run_topology_tool(
        tool,
        input_path=source,
        output_path=first,
        retention_percent=100,
        precision=6,
    )
    run_topology_tool(
        tool,
        input_path=source,
        output_path=second,
        retention_percent=100,
        precision=6,
    )

    assert first.read_bytes() == second.read_bytes()
    output = load_topology_output(first, expected_feature_ids={"left", "right"})
    assert_shared_borders_preserved(_shared_border_features(), output)


def test_reviewed_offline_bundle_runs_real_mapshaper_deterministically(tmp_path: Path) -> None:
    tool = prepare_topology_tool(
        source_archive=MAPSHAPER_BUNDLE,
        expected_sha256=MAPSHAPER_BUNDLE_SHA256,
        expected_bundle_release="0.7.49+odin-offline-v1",
        expected_version="0.7.49",
        work_dir=tmp_path / "tool",
    )
    first = tmp_path / "first-real.geojson"
    second = tmp_path / "second-real.geojson"

    run_topology_tool(
        tool,
        input_path=FIXTURES / "shared_border.geojson",
        output_path=first,
        retention_percent=100,
        precision=6,
    )
    run_topology_tool(
        tool,
        input_path=FIXTURES / "shared_border.geojson",
        output_path=second,
        retention_percent=100,
        precision=6,
    )

    assert first.read_bytes() == second.read_bytes()
    output = load_topology_output(first, expected_feature_ids={"left", "right"})
    assert_shared_borders_preserved(_shared_border_features(), output)


def test_offline_bundle_rejects_archive_path_traversal(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("../escaped")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    payload = buffer.getvalue()
    archive_path = tmp_path / "malicious.tgz"
    archive_path.write_bytes(payload)

    with pytest.raises(LodBudgetError, match="UNSAFE_TOPOLOGY_BUNDLE"):
        prepare_topology_tool(
            source_archive=archive_path,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_bundle_release="0.7.49+odin-offline-v1",
            expected_version="0.7.49",
            work_dir=tmp_path / "tool",
        )
    assert not (tmp_path / "escaped").exists()


def test_pinned_tool_hash_fails_before_process_execution(tmp_path: Path) -> None:
    archive = tmp_path / "mapshaper.tgz"
    archive.write_bytes(b"tampered")
    marker = tmp_path / "executed"
    executable = tmp_path / "mapshaper"
    executable.write_text(
        f"#!/bin/sh\ntouch '{marker}'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    with pytest.raises(LodBudgetError, match="TOPOLOGY_TOOL_HASH_MISMATCH"):
        run_topology_tool(
            PinnedTopologyTool(
                executable=executable,
                source_archive=archive,
                expected_version="0.7.49",
                expected_sha256="0" * 64,
            ),
            input_path=FIXTURES / "shared_border.geojson",
            output_path=tmp_path / "out.geojson",
            retention_percent=100,
            precision=6,
        )
    assert not marker.exists()


def test_lod_policy_matches_reviewed_wire_contract() -> None:
    assert {
        name: (policy.precision, policy.max_error_m, policy.max_vertices)
        for name, policy in LOD_POLICIES.items()
    } == {
        "overview": (4, 10_000, 12_000),
        "regional": (5, 2_000, 50_000),
        "local": (6, 250, 120_000),
    }
