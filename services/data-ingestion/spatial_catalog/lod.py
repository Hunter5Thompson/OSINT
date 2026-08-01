"""Topology-tool adapter and ODIN-owned LOD/containment gates."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import subprocess
import tarfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal

from shapely import STRtree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping
from shapely.ops import unary_union

from spatial_catalog.manifest import canonical_json_bytes
from spatial_catalog.normalize import (
    BoundaryGeometry,
    GeometryValidationError,
    Position,
    normalize_geometry,
)

type LodName = Literal["overview", "regional", "local"]

_EARTH_RADIUS_M = 6_371_008.8
_TOOL_TIMEOUT_SECONDS = 120
_MAX_TOOL_BUNDLE_FILES = 5_000
_MAX_TOOL_BUNDLE_BYTES = 64 * 1024 * 1024
_RETENTION_SCHEDULE = (100, 95, 90, 80, 70, 60, 50, 40, 30, 20, 10, 5, 2, 1)


class LodBudgetError(ValueError):
    """A render LOD or topology-tool result violates a reviewed gate."""


class ContainmentBudgetError(ValueError):
    """Strict containment cannot meet its independent reviewed gate."""


@dataclass(frozen=True, slots=True)
class BoundaryFeature:
    feature_id: str
    geometry: BoundaryGeometry

    def __post_init__(self) -> None:
        if not self.feature_id or len(self.feature_id.encode("utf-8")) > 128:
            raise ValueError("feature_id must contain 1-128 UTF-8 bytes")


@dataclass(frozen=True, slots=True)
class LodPolicy:
    lod: LodName
    precision: int
    max_error_m: float
    max_vertices: int
    max_ring_vertices: int = 16_384

    def with_limits(
        self,
        *,
        max_error_m: float | None = None,
        max_vertices: int | None = None,
        max_ring_vertices: int | None = None,
    ) -> LodPolicy:
        return replace(
            self,
            max_error_m=self.max_error_m if max_error_m is None else max_error_m,
            max_vertices=self.max_vertices if max_vertices is None else max_vertices,
            max_ring_vertices=(
                self.max_ring_vertices
                if max_ring_vertices is None
                else max_ring_vertices
            ),
        )


LOD_POLICIES: Mapping[str, LodPolicy] = MappingProxyType(
    {
        "overview": LodPolicy("overview", precision=4, max_error_m=10_000, max_vertices=12_000),
        "regional": LodPolicy("regional", precision=5, max_error_m=2_000, max_vertices=50_000),
        "local": LodPolicy("local", precision=6, max_error_m=250, max_vertices=120_000),
    }
)


@dataclass(frozen=True, slots=True)
class LodMetrics:
    lod: LodName
    vertex_count: int
    max_error_m: float
    protected_feature_count: int
    removed_degenerate_ring_count: int


@dataclass(frozen=True, slots=True)
class ContainmentResult:
    geometry: BoundaryGeometry
    vertex_count: int
    max_error_m: float
    boundary_uncertain_m: float


@dataclass(frozen=True, slots=True)
class PinnedTopologyTool:
    """Executable plus the reviewed archive proving its exact source version."""

    executable: Path
    source_archive: Path
    expected_version: str
    expected_sha256: str


def prepare_topology_tool(
    *,
    source_archive: Path,
    expected_sha256: str,
    expected_bundle_release: str,
    expected_version: str,
    work_dir: Path,
) -> PinnedTopologyTool:
    """Verify and safely materialize the committed offline Mapshaper closure."""

    payload = source_archive.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_sha256:
        raise LodBudgetError(
            "TOPOLOGY_TOOL_HASH_MISMATCH: "
            f"expected {expected_sha256}, got {actual_hash}"
        )

    try:
        archive = tarfile.open(  # noqa: SIM115 - normalized error precedes managed use
            fileobj=io.BytesIO(payload),
            mode="r:gz",
        )
    except tarfile.TarError as exc:
        raise LodBudgetError(f"INVALID_TOPOLOGY_BUNDLE: {exc}") from exc

    with archive:
        members = archive.getmembers()
        if len(members) > _MAX_TOOL_BUNDLE_FILES:
            raise LodBudgetError("TOPOLOGY_BUNDLE_FILE_LIMIT")
        total_size = sum(member.size for member in members if member.isfile())
        if total_size > _MAX_TOOL_BUNDLE_BYTES:
            raise LodBudgetError("TOPOLOGY_BUNDLE_SIZE_LIMIT")

        safe_members: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        seen_names: set[str] = set()
        for member in members:
            normalized_name = member.name.removeprefix("./")
            if normalized_name in {"", "."} and member.isdir():
                continue
            relative = PurePosixPath(normalized_name)
            if (
                not normalized_name
                or relative.is_absolute()
                or ".." in relative.parts
                or not (member.isdir() or member.isfile())
            ):
                raise LodBudgetError(
                    f"UNSAFE_TOPOLOGY_BUNDLE: {member.name}"
                )
            canonical_name = relative.as_posix()
            if canonical_name in seen_names:
                raise LodBudgetError(
                    f"UNSAFE_TOPOLOGY_BUNDLE: duplicate {canonical_name}"
                )
            seen_names.add(canonical_name)
            safe_members.append((member, relative))

        manifest_member = next(
            (
                member
                for member, relative in safe_members
                if relative.as_posix() == "bundle-manifest.json"
            ),
            None,
        )
        if manifest_member is None or not manifest_member.isfile():
            raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: missing manifest")
        manifest_file = archive.extractfile(manifest_member)
        if manifest_file is None:
            raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: unreadable manifest")
        try:
            manifest = json.load(manifest_file)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LodBudgetError(f"INVALID_TOPOLOGY_BUNDLE_MANIFEST: {exc}") from exc
        entrypoint = _validate_tool_bundle_manifest(
            manifest,
            expected_bundle_release=expected_bundle_release,
            expected_version=expected_version,
        )
        if entrypoint.as_posix() not in seen_names:
            raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: missing entrypoint")

        if work_dir.exists() and any(work_dir.iterdir()):
            raise LodBudgetError("TOPOLOGY_TOOL_WORK_DIR_NOT_EMPTY")
        work_dir.mkdir(parents=True, exist_ok=True)
        resolved_root = work_dir.resolve()
        for member, relative in sorted(
            safe_members,
            key=lambda item: (not item[0].isdir(), item[1].as_posix()),
        ):
            destination = (work_dir / Path(*relative.parts)).resolve()
            try:
                destination.relative_to(resolved_root)
            except ValueError as exc:
                raise LodBudgetError(
                    f"UNSAFE_TOPOLOGY_BUNDLE: {member.name}"
                ) from exc
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                destination.chmod(0o755)
                continue
            source_file = archive.extractfile(member)
            if source_file is None:
                raise LodBudgetError(f"INVALID_TOPOLOGY_BUNDLE: {member.name}")
            content = source_file.read(_MAX_TOOL_BUNDLE_BYTES + 1)
            if len(content) != member.size:
                raise LodBudgetError(f"INVALID_TOPOLOGY_BUNDLE: {member.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(0o644)

    executable = work_dir / Path(*entrypoint.parts)
    executable.chmod(0o755)
    return PinnedTopologyTool(
        executable=executable,
        source_archive=source_archive,
        expected_version=expected_version,
        expected_sha256=expected_sha256,
    )


def vertex_count(geometry: BoundaryGeometry) -> int:
    """Count serialized position occurrences, including every ring closure."""

    return sum(
        len(ring) for polygon in geometry.polygons for ring in polygon
    )


def collect_protected_positions(
    features: Sequence[BoundaryFeature],
    *,
    policy_marked: Iterable[Position] = (),
) -> frozenset[Position]:
    """Collect shared junctions plus one stable island/enclave anchor per ring."""

    appearances: Counter[Position] = Counter()
    for feature in features:
        appearances.update(
            {
                position
                for polygon in feature.geometry.polygons
                for ring in polygon
                for position in ring[:-1]
            }
        )

    protected = {position for position, count in appearances.items() if count > 1}
    for feature in features:
        for polygon in feature.geometry.polygons:
            protected.add(min(polygon[0][:-1]))
            protected.update(min(hole[:-1]) for hole in polygon[1:])
    protected.update(policy_marked)
    return frozenset(protected)


def dissolve_complete_children(features: Sequence[BoundaryFeature]) -> BoundaryGeometry:
    """Derive a parent outline from the policy-complete child topology."""

    if not features:
        raise ValueError("complete child set must not be empty")
    dissolved = unary_union(
        [polygon for feature in features for polygon in _shapely_polygons(feature.geometry)]
    )
    if not isinstance(dissolved, (Polygon, MultiPolygon)) or dissolved.is_empty:
        raise LodBudgetError("PARENT_DISSOLVE_FAILED: child union is not polygonal")
    return normalize_geometry(mapping(dissolved), precision=6)


def assert_shared_borders_preserved(
    original: Sequence[BoundaryFeature],
    simplified: Sequence[BoundaryFeature],
    *,
    tolerance_degrees: float = 1e-8,
) -> None:
    """Require topology output to retain exactly the original adjacency graph."""

    source = _feature_map(original)
    output = _feature_map(simplified)
    if source.keys() != output.keys():
        raise LodBudgetError("FEATURE_SET_MISMATCH: topology output changed feature IDs")

    ids = sorted(source)
    for left_index, left_id in enumerate(ids):
        source_left = _shapely_geometry(source[left_id].geometry)
        output_left = _shapely_geometry(output[left_id].geometry)
        for right_id in ids[left_index + 1 :]:
            source_shared = source_left.boundary.intersection(
                _shapely_geometry(source[right_id].geometry).boundary
            )
            output_shared = output_left.boundary.intersection(
                _shapely_geometry(output[right_id].geometry).boundary
            )
            if source_shared.length > tolerance_degrees and output_shared.length <= 0:
                raise LodBudgetError(
                    f"SHARED_BORDER_DRIFT: {left_id} and {right_id} no longer share one edge"
                )
            if source_shared.length <= tolerance_degrees and output_shared.length > 0:
                raise LodBudgetError(
                    f"NEW_SHARED_BORDER: {left_id} and {right_id} became adjacent"
                )


def geodesic_max_deviation_m(
    original: BoundaryGeometry,
    simplified: BoundaryGeometry,
) -> float:
    """Measure maximum original-vertex to simplified-segment deviation in metres."""

    segments = tuple(_segments(simplified))
    if not segments:
        raise LodBudgetError("INVALID_LOD_GEOMETRY: simplified geometry has no segments")
    segment_index = STRtree([LineString((left, right)) for left, right in segments])
    return max(
        _point_segment_distance_m(point, *segments[int(segment_index.nearest(Point(point)))])
        for point in _positions(original)
    )


def validate_lod_features(
    original: Sequence[BoundaryFeature],
    simplified: Sequence[BoundaryFeature],
    *,
    policy: LodPolicy,
    protected_positions: Set[Position] = frozenset(),
) -> LodMetrics:
    """Apply ODIN's production vertex, error, feature, and topology gates."""

    source = _feature_map(original)
    output = _feature_map(simplified)
    if source.keys() != output.keys():
        raise LodBudgetError("FEATURE_SET_MISMATCH: topology output changed feature IDs")
    assert_shared_borders_preserved(original, simplified)
    removed_degenerate_rings = 0
    for feature_id in source:
        source_shape, removed = _quantized_shape_signature(
            source[feature_id].geometry,
            precision=policy.precision,
        )
        removed_degenerate_rings += removed
        output_shape = tuple(len(polygon) for polygon in output[feature_id].geometry.polygons)
        if source_shape != output_shape:
            raise LodBudgetError(
                f"PROTECTED_SHAPE_LOST: {feature_id} changed polygon/ring membership"
            )

    count = sum(vertex_count(feature.geometry) for feature in simplified)
    if count > policy.max_vertices:
        raise LodBudgetError(
            f"LOD_VERTEX_BUDGET: {policy.lod} has {count} > {policy.max_vertices} vertices"
        )
    largest_ring = max(
        len(ring)
        for feature in simplified
        for polygon in feature.geometry.polygons
        for ring in polygon
    )
    if largest_ring > policy.max_ring_vertices:
        raise LodBudgetError(
            f"LOD_RING_VERTEX_BUDGET: {policy.lod} has {largest_ring} > "
            f"{policy.max_ring_vertices} vertices"
        )

    emitted_positions = {
        position
        for feature in simplified
        for position in _positions(feature.geometry)
    }
    missing = sorted(set(protected_positions) - emitted_positions)
    if missing:
        raise LodBudgetError(f"PROTECTED_POSITION_LOST: {missing[0]}")

    max_error = max(
        geodesic_max_deviation_m(source[feature_id].geometry, output[feature_id].geometry)
        for feature_id in sorted(source)
    )
    if max_error > policy.max_error_m:
        raise LodBudgetError(
            f"LOD_ERROR_BUDGET: {policy.lod} has {max_error:.3f} m > "
            f"{policy.max_error_m:.3f} m"
        )
    return LodMetrics(
        lod=policy.lod,
        vertex_count=count,
        max_error_m=max_error,
        protected_feature_count=len(protected_positions),
        removed_degenerate_ring_count=removed_degenerate_rings,
    )


def build_containment(
    source: BoundaryGeometry,
    *,
    max_vertices: int,
    strict: bool,
    candidate: BoundaryGeometry | None = None,
    max_error_m: float = 50.0,
    max_ring_vertices: int = 16_384,
) -> ContainmentResult | None:
    """Build the six-decimal representation independently of render LODs."""

    selected = candidate or source
    containment = normalize_geometry(_to_geojson(selected), precision=6)
    count = vertex_count(containment)
    largest_ring = max(
        len(ring) for polygon in containment.polygons for ring in polygon
    )
    error = geodesic_max_deviation_m(source, containment)
    if (
        count > max_vertices
        or largest_ring > max_ring_vertices
        or error > max_error_m
    ):
        if strict:
            raise ContainmentBudgetError(
                "STRICT_CONTAINMENT_UNAVAILABLE: "
                f"vertices={count}/{max_vertices}, "
                f"ring_vertices={largest_ring}/{max_ring_vertices}, "
                f"error_m={error:.3f}/{max_error_m:.3f}"
            )
        return None
    return ContainmentResult(
        geometry=containment,
        vertex_count=count,
        max_error_m=error,
        boundary_uncertain_m=error,
    )


def run_topology_tool(
    tool: PinnedTopologyTool,
    *,
    input_path: Path,
    output_path: Path,
    retention_percent: int,
    precision: int,
) -> bytes:
    """Run the one external topology adapter with explicit offline arguments."""

    if not 1 <= retention_percent <= 100:
        raise ValueError("retention_percent must be between 1 and 100")
    if not 0 <= precision <= 12:
        raise ValueError("precision must be between 0 and 12")

    archive_bytes = tool.source_archive.read_bytes()
    actual_hash = hashlib.sha256(archive_bytes).hexdigest()
    if actual_hash != tool.expected_sha256:
        raise LodBudgetError(
            "TOPOLOGY_TOOL_HASH_MISMATCH: "
            f"expected {tool.expected_sha256}, got {actual_hash}"
        )

    source = input_path.resolve(strict=True)
    destination = output_path.resolve(strict=False)
    if source == destination:
        raise ValueError("topology input and output paths must differ")
    if not destination.parent.is_dir():
        raise ValueError("topology output parent must already exist")
    executable = tool.executable.resolve(strict=True)
    environment = _offline_environment()

    version = _run_tool_command(
        [str(executable), "--version"],
        environment=environment,
    ).stdout.strip()
    if re.search(rf"(?<![0-9.]){re.escape(tool.expected_version)}(?![0-9.])", version) is None:
        raise LodBudgetError(
            f"TOPOLOGY_TOOL_VERSION_MISMATCH: expected {tool.expected_version}, got {version!r}"
        )

    precision_value = format(10**-precision, f".{precision}f") if precision else "1"
    command = [
        str(executable),
        str(source),
        "-simplify",
        "weighted",
        f"{retention_percent}%",
        "keep-shapes",
        "-o",
        "format=geojson",
        f"precision={precision_value}",
        str(destination),
    ]
    _run_tool_command(command, environment=environment)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise LodBudgetError("TOPOLOGY_TOOL_OUTPUT_MISSING: tool emitted no GeoJSON")
    load_topology_output(destination)
    return destination.read_bytes()


def load_topology_output(
    path: Path,
    *,
    expected_feature_ids: Set[str] | None = None,
    precision: int = 6,
) -> tuple[BoundaryFeature, ...]:
    """Strictly validate the untrusted external-tool intermediate."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LodBudgetError(f"INVALID_TOPOLOGY_OUTPUT: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise LodBudgetError("INVALID_TOPOLOGY_OUTPUT: expected FeatureCollection")
    raw_features = payload.get("features")
    if not isinstance(raw_features, list):
        raise LodBudgetError("INVALID_TOPOLOGY_OUTPUT: features must be an array")

    features: list[BoundaryFeature] = []
    for raw in raw_features:
        if not isinstance(raw, dict) or raw.get("type") != "Feature":
            raise LodBudgetError("INVALID_TOPOLOGY_OUTPUT: malformed feature")
        properties = raw.get("properties")
        raw_id = raw.get("id")
        if raw_id is None and isinstance(properties, dict):
            raw_id = properties.get("__odin_feature_id")
        if not isinstance(raw_id, str):
            raise LodBudgetError("INVALID_TOPOLOGY_OUTPUT: feature ID is required")
        try:
            geometry = normalize_geometry(raw.get("geometry"), precision=precision)
        except GeometryValidationError as exc:
            raise LodBudgetError(f"INVALID_TOPOLOGY_OUTPUT: {raw_id}: {exc}") from exc
        features.append(BoundaryFeature(feature_id=raw_id, geometry=geometry))

    normalized = tuple(sorted(features, key=lambda feature: feature.feature_id))
    actual_ids = {feature.feature_id for feature in normalized}
    if len(actual_ids) != len(normalized):
        raise LodBudgetError("INVALID_TOPOLOGY_OUTPUT: duplicate feature ID")
    if expected_feature_ids is not None and actual_ids != set(expected_feature_ids):
        raise LodBudgetError("FEATURE_SET_MISMATCH: topology output changed feature IDs")
    return normalized


def build_bounded_lod(
    features: Sequence[BoundaryFeature],
    *,
    policy: LodPolicy,
    tool: PinnedTopologyTool,
    work_dir: Path,
    policy_marked_positions: Iterable[Position] = (),
) -> tuple[tuple[BoundaryFeature, ...], LodMetrics]:
    """Select the highest-detail topology output satisfying both hard gates."""

    if not work_dir.is_dir():
        raise ValueError("LOD work_dir must already exist")
    canonical_features = tuple(sorted(features, key=lambda feature: feature.feature_id))
    policy_marked = tuple(policy_marked_positions)
    protected = collect_protected_positions(
        canonical_features,
        policy_marked=policy_marked,
    )
    input_path = work_dir / f"{policy.lod}-input.geojson"
    input_path.write_bytes(_feature_collection_bytes(canonical_features))

    failures: list[str] = []
    for retention in _RETENTION_SCHEDULE:
        output_path = work_dir / f"{policy.lod}-{retention:03d}.geojson"
        try:
            run_topology_tool(
                tool,
                input_path=input_path,
                output_path=output_path,
                retention_percent=retention,
                precision=policy.precision,
            )
            output = load_topology_output(
                output_path,
                expected_feature_ids={feature.feature_id for feature in canonical_features},
                precision=policy.precision,
            )
            metrics = validate_lod_features(
                canonical_features,
                output,
                policy=policy,
                protected_positions={
                    (round(longitude, policy.precision), round(latitude, policy.precision))
                    for longitude, latitude in policy_marked
                },
            )
        except (LodBudgetError, GeometryValidationError) as exc:
            failures.append(f"{retention}%={exc}")
            continue
        return output, replace(metrics, protected_feature_count=len(protected))
    raise LodBudgetError(
        f"NO_FEASIBLE_LOD: {policy.lod}: " + "; ".join(failures)
    )


def _run_tool_command(
    command: list[str],
    *,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=_TOOL_TIMEOUT_SECONDS,
            env=dict(environment),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise LodBudgetError(f"TOPOLOGY_TOOL_FAILED: {detail}") from exc


def _validate_tool_bundle_manifest(
    payload: object,
    *,
    expected_bundle_release: str,
    expected_version: str,
) -> PurePosixPath:
    expected_keys = {
        "schema_version",
        "bundle_release",
        "entrypoint",
        "node_engine",
        "purpose",
        "packages",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: schema")
    if payload["schema_version"] != 1:
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: schema version")
    if payload["bundle_release"] != expected_bundle_release:
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: release")
    if payload["node_engine"] != ">=20.11.0":
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: Node engine")
    raw_entrypoint = payload["entrypoint"]
    if not isinstance(raw_entrypoint, str):
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: entrypoint")
    entrypoint = PurePosixPath(raw_entrypoint)
    if entrypoint.is_absolute() or ".." in entrypoint.parts:
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: entrypoint")
    packages = payload["packages"]
    if not isinstance(packages, list):
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: packages")
    mapshaper_versions = [
        package.get("version")
        for package in packages
        if isinstance(package, dict) and package.get("name") == "mapshaper"
    ]
    if mapshaper_versions != [expected_version]:
        raise LodBudgetError("INVALID_TOPOLOGY_BUNDLE_MANIFEST: Mapshaper version")
    return entrypoint


def _offline_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "NO_PROXY": "*",
            "no_proxy": "*",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "npm_config_offline": "true",
        }
    )
    return environment


def _feature_collection_bytes(features: Sequence[BoundaryFeature]) -> bytes:
    return canonical_json_bytes(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": feature.feature_id,
                    "properties": {"__odin_feature_id": feature.feature_id},
                    "geometry": _to_geojson(feature.geometry),
                }
                for feature in features
            ],
        }
    )


def _feature_map(features: Sequence[BoundaryFeature]) -> dict[str, BoundaryFeature]:
    result = {feature.feature_id: feature for feature in features}
    if len(result) != len(features):
        raise LodBudgetError("DUPLICATE_FEATURE_ID: feature IDs must be unique")
    return result


def _to_geojson(geometry: BoundaryGeometry) -> dict[str, object]:
    return {"type": "MultiPolygon", "coordinates": geometry.polygons}


def _shapely_polygons(geometry: BoundaryGeometry) -> tuple[Polygon, ...]:
    return tuple(Polygon(polygon[0], polygon[1:]) for polygon in geometry.polygons)


def _shapely_geometry(geometry: BoundaryGeometry) -> Polygon | MultiPolygon:
    polygons = _shapely_polygons(geometry)
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


def _positions(geometry: BoundaryGeometry) -> Iterable[Position]:
    for polygon in geometry.polygons:
        for ring in polygon:
            yield from ring


def _quantized_shape_signature(
    geometry: BoundaryGeometry,
    *,
    precision: int,
) -> tuple[tuple[int, ...], int]:
    signature: list[int] = []
    removed = 0
    for polygon in geometry.polygons:
        surviving_count = 0
        for ring_index, ring in enumerate(polygon):
            rounded = tuple(
                (round(longitude, precision), round(latitude, precision))
                for longitude, latitude in ring
            )
            unique = set(rounded[:-1])
            area = abs(
                0.5
                * sum(
                    left[0] * right[1] - right[0] * left[1]
                    for left, right in zip(rounded, rounded[1:], strict=False)
                )
            )
            if len(unique) < 3 or area <= 1e-12:
                if ring_index == 0:
                    removed += len(polygon)
                    surviving_count = 0
                    break
                removed += 1
                continue
            surviving_count += 1
        if surviving_count:
            signature.append(surviving_count)
    return tuple(signature), removed


def _segments(geometry: BoundaryGeometry) -> Iterable[tuple[Position, Position]]:
    for polygon in geometry.polygons:
        for ring in polygon:
            yield from zip(ring, ring[1:], strict=False)


def _point_segment_distance_m(point: Position, left: Position, right: Position) -> float:
    latitude_radians = math.radians(point[1])

    def project(candidate: Position) -> tuple[float, float]:
        delta_longitude = (candidate[0] - point[0] + 180) % 360 - 180
        return (
            math.radians(delta_longitude) * math.cos(latitude_radians) * _EARTH_RADIUS_M,
            math.radians(candidate[1] - point[1]) * _EARTH_RADIUS_M,
        )

    left_x, left_y = project(left)
    right_x, right_y = project(right)
    delta_x = right_x - left_x
    delta_y = right_y - left_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return math.hypot(left_x, left_y)
    fraction = max(
        0.0,
        min(1.0, -(left_x * delta_x + left_y * delta_y) / length_squared),
    )
    nearest_x = left_x + fraction * delta_x
    nearest_y = left_y + fraction * delta_y
    return math.hypot(nearest_x, nearest_y)
