"""Canonical boundary assets and atomic immutable catalog publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from spatial_catalog.identity import parse_scope_key
from spatial_catalog.lod import LOD_POLICIES
from spatial_catalog.manifest import (
    CatalogManifest,
    CatalogPointer,
    canonical_json_bytes,
    canonical_manifest_bytes,
)
from spatial_catalog.models import (
    AttributionSource,
    CatalogAttribution,
    CatalogRevision,
    ContainmentDescriptor,
    GeometryDescriptor,
    Lod,
)
from spatial_catalog.normalize import BoundaryGeometry

BOUNDARY_MEDIA_TYPE = "application/vnd.odin.boundary+json;v=1"
BOUNDARY_PACK_MEDIA_TYPE = "application/vnd.odin.boundary-pack+json;v=1"

MAX_WIRE_BYTES = 4 * 1024 * 1024
MAX_HEAP_BYTES = 16 * 1024 * 1024
MAX_FEATURES = 256
MAX_RINGS = 2_048
MAX_RING_VERTICES = 16_384

_CONTEXT_REASONS = frozenset({"disputed-territory-context"})
_CATALOG_REVISION_ADAPTER = TypeAdapter(CatalogRevision)


class AssetBudgetError(ValueError):
    """Canonical wire bytes or production counters exceed a reviewed gate."""


class PublicationError(ValueError):
    """An immutable catalog revision cannot be safely published."""


@dataclass(frozen=True, slots=True)
class ScopePackFeature:
    scope_key: str
    label: str
    geometry: BoundaryGeometry

    kind: Literal["scope"] = "scope"

    def __post_init__(self) -> None:
        parsed = parse_scope_key(self.scope_key)
        if parsed.canonical != self.scope_key:
            raise ValueError("scope_key must already be canonical")
        _validate_label(self.label)


@dataclass(frozen=True, slots=True)
class ContextPackFeature:
    feature_id: str
    label: str
    non_scope_reason: str
    geometry: BoundaryGeometry

    kind: Literal["context"] = "context"

    def __post_init__(self) -> None:
        if not self.feature_id or len(self.feature_id.encode("utf-8")) > 128:
            raise ValueError("feature_id must contain 1-128 UTF-8 bytes")
        _validate_label(self.label)
        if self.non_scope_reason not in _CONTEXT_REASONS:
            raise ValueError("invalid non_scope_reason")


type PackFeature = ScopePackFeature | ContextPackFeature


@dataclass(frozen=True, slots=True)
class WireCounts:
    byte_length: int
    feature_count: int
    polygon_count: int
    ring_count: int
    vertex_count: int
    max_ring_vertices: int
    estimated_heap_bytes: int


@dataclass(slots=True)
class _Counter:
    feature_count: int = 0
    polygon_count: int = 0
    ring_count: int = 0
    vertex_count: int = 0
    max_ring_vertices: int = 0

    def freeze(self, *, byte_length: int) -> WireCounts:
        # Conservative decoded-object estimate used identically by descriptors,
        # feasibility reports, and gates.  It deliberately counts repeated borders.
        estimated_heap = (
            1_024
            + self.feature_count * 256
            + self.polygon_count * 128
            + self.ring_count * 64
            + self.vertex_count * 64
        )
        return WireCounts(
            byte_length=byte_length,
            feature_count=self.feature_count,
            polygon_count=self.polygon_count,
            ring_count=self.ring_count,
            vertex_count=self.vertex_count,
            max_ring_vertices=self.max_ring_vertices,
            estimated_heap_bytes=estimated_heap,
        )


@dataclass(frozen=True, slots=True)
class EmittedAsset:
    asset_id: str
    media_type: str
    content: bytes
    counts: WireCounts
    descriptor: GeometryDescriptor | ContainmentDescriptor


@dataclass(frozen=True, slots=True, order=True)
class AttributionRecord:
    source_id: str
    release: str
    license_id: str
    attribution: str

    def __post_init__(self) -> None:
        AttributionSource(
            source_id=self.source_id,
            release=self.release,
            license_id=self.license_id,
            attribution=self.attribution,
        )


def canonical_attribution_sources_bytes(
    records: Sequence[AttributionRecord],
) -> bytes:
    """Canonical revision-owned source metadata, independent of revision ID."""

    ordered = tuple(sorted(records))
    sources = tuple(
        AttributionSource(
            source_id=record.source_id,
            release=record.release,
            license_id=record.license_id,
            attribution=record.attribution,
        )
        for record in ordered
    )
    source_ids = tuple(source.source_id for source in sources)
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate attribution source_id")
    return canonical_json_bytes(sources)


def attribution_sources_sha256(records: Sequence[AttributionRecord]) -> str:
    return hashlib.sha256(canonical_attribution_sources_bytes(records)).hexdigest()


def emit_render_boundary(
    geometry: BoundaryGeometry,
    *,
    lod: Lod,
    max_vertices: int | None = None,
) -> EmittedAsset:
    """Emit one content-addressed BoundaryGeometryV1 render asset."""

    counter = _Counter()
    wire = _geometry_wire(geometry, counter=counter)
    content, counts, asset_id = _finalize_wire(
        wire,
        counter=counter,
        max_vertices=max_vertices or LOD_POLICIES[lod.value].max_vertices,
    )
    descriptor = GeometryDescriptor(
        asset_id=asset_id,
        media_type=BOUNDARY_MEDIA_TYPE,
        byte_length=counts.byte_length,
        vertex_count=counts.vertex_count,
        role="render",
        lod=lod,
    )
    return EmittedAsset(
        asset_id=asset_id,
        media_type=BOUNDARY_MEDIA_TYPE,
        content=content,
        counts=counts,
        descriptor=descriptor,
    )


def emit_containment_boundary(
    geometry: BoundaryGeometry,
    *,
    max_error_m: float,
    max_vertices: int,
) -> EmittedAsset:
    """Emit one content-addressed containment geometry with its measured error."""

    counter = _Counter()
    wire = _geometry_wire(geometry, counter=counter)
    content, counts, asset_id = _finalize_wire(
        wire,
        counter=counter,
        max_vertices=max_vertices,
    )
    descriptor = ContainmentDescriptor(
        asset_id=asset_id,
        media_type=BOUNDARY_MEDIA_TYPE,
        byte_length=counts.byte_length,
        vertex_count=counts.vertex_count,
        role="containment",
        max_error_m=max_error_m,
    )
    return EmittedAsset(
        asset_id=asset_id,
        media_type=BOUNDARY_MEDIA_TYPE,
        content=content,
        counts=counts,
        descriptor=descriptor,
    )


def emit_boundary_pack(
    *,
    parent_scope_key: str,
    lod: Lod,
    allowed_child_scope_keys: Iterable[str],
    features: Sequence[PackFeature],
    max_vertices: int | None = None,
) -> EmittedAsset:
    """Emit a stable pack whose pickable features are direct manifest children."""

    parent = parse_scope_key(parent_scope_key)
    if parent.canonical != parent_scope_key:
        raise ValueError("parent_scope_key must already be canonical")
    allowed = frozenset(allowed_child_scope_keys)
    if any(parse_scope_key(scope_key).canonical != scope_key for scope_key in allowed):
        raise ValueError("allowed child scope keys must be canonical")
    if not features:
        raise AssetBudgetError("EMPTY_BOUNDARY_PACK: a pack requires at least one feature")

    ordered = tuple(sorted(features, key=_pack_feature_sort_key))
    identities = [_pack_feature_identity(feature) for feature in ordered]
    if len(identities) != len(set(identities)):
        raise AssetBudgetError("DUPLICATE_PACK_FEATURE: feature identities must be unique")
    for feature in ordered:
        if isinstance(feature, ScopePackFeature) and feature.scope_key not in allowed:
            raise AssetBudgetError(
                f"DIRECT_MANIFEST_CHILD_REQUIRED: {feature.scope_key} is not an allowed child"
            )

    counter = _Counter(feature_count=len(ordered))
    wire_features: list[dict[str, object]] = []
    for feature in ordered:
        geometry_wire = _geometry_wire(feature.geometry, counter=counter)
        if isinstance(feature, ScopePackFeature):
            wire_features.append(
                {
                    "kind": "scope",
                    "scope_key": feature.scope_key,
                    "label": feature.label,
                    "geometry": geometry_wire,
                }
            )
        else:
            wire_features.append(
                {
                    "kind": "context",
                    "feature_id": feature.feature_id,
                    "label": feature.label,
                    "non_scope_reason": feature.non_scope_reason,
                    "geometry": geometry_wire,
                }
            )
    wire = {
        "schema_version": 1,
        "parent_scope_key": parent_scope_key,
        "features": wire_features,
    }
    content, counts, asset_id = _finalize_wire(
        wire,
        counter=counter,
        max_vertices=max_vertices or LOD_POLICIES[lod.value].max_vertices,
    )
    descriptor = GeometryDescriptor(
        asset_id=asset_id,
        media_type=BOUNDARY_PACK_MEDIA_TYPE,
        byte_length=counts.byte_length,
        vertex_count=counts.vertex_count,
        feature_count=counts.feature_count,
        role="render",
        lod=lod,
    )
    return EmittedAsset(
        asset_id=asset_id,
        media_type=BOUNDARY_PACK_MEDIA_TYPE,
        content=content,
        counts=counts,
        descriptor=descriptor,
    )


def emit_attribution(
    catalog_revision: str,
    records: Sequence[AttributionRecord],
) -> bytes:
    """Emit URL-free, stable source attribution owned by one catalog revision."""

    _CATALOG_REVISION_ADAPTER.validate_python(catalog_revision)
    sources = tuple(
        AttributionSource.model_validate(source)
        for source in json.loads(canonical_attribution_sources_bytes(records))
    )
    return canonical_json_bytes(
        CatalogAttribution(
            schema_version=1,
            catalog_revision=catalog_revision,
            sources=sources,
        )
    )


def publish_revision(
    output_root: Path,
    *,
    manifest: CatalogManifest,
    assets: Sequence[EmittedAsset],
    attribution: bytes,
    reports: Mapping[str, bytes] | None = None,
) -> Path:
    """Stage a complete revision, then atomically publish it without overwrite."""

    canonical_assets = tuple(sorted(assets, key=lambda asset: asset.asset_id))
    asset_ids = tuple(asset.asset_id for asset in canonical_assets)
    if len(asset_ids) != len(set(asset_ids)):
        raise PublicationError("DUPLICATE_ASSET_ID: publication assets must be unique")
    if asset_ids != manifest.assets:
        raise PublicationError("MANIFEST_ASSET_MISMATCH: emitted assets differ from manifest")
    for asset in canonical_assets:
        if hashlib.sha256(asset.content).hexdigest() != asset.asset_id:
            raise PublicationError(f"ASSET_HASH_MISMATCH: {asset.asset_id}")
        if asset.descriptor.asset_id != asset.asset_id:
            raise PublicationError(f"DESCRIPTOR_ASSET_MISMATCH: {asset.asset_id}")

    try:
        attribution_value = CatalogAttribution.model_validate_json(attribution)
    except ValidationError as exc:
        raise PublicationError("INVALID_ATTRIBUTION: expected strict JSON") from exc
    if (
        attribution_value.catalog_revision != manifest.catalog_revision
        or canonical_json_bytes(attribution_value) != attribution
        or hashlib.sha256(canonical_json_bytes(attribution_value.sources)).hexdigest()
        != manifest.attribution_sources_sha256
    ):
        raise PublicationError("INVALID_ATTRIBUTION: revision or canonical bytes mismatch")

    report_values = dict(reports or {})
    for name in report_values:
        if PurePath(name).name != name or not name.endswith(".json"):
            raise PublicationError(f"INVALID_REPORT_NAME: {name}")

    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / manifest.catalog_revision
    staging = Path(
        tempfile.mkdtemp(prefix=f".{manifest.catalog_revision}-", dir=output_root)
    )
    try:
        assets_dir = staging / "assets"
        assets_dir.mkdir()
        for asset in canonical_assets:
            (assets_dir / f"{asset.asset_id}.json").write_bytes(asset.content)
        (staging / "manifest.json").write_bytes(canonical_manifest_bytes(manifest))
        (staging / "attribution.json").write_bytes(attribution)
        for name, content in sorted(report_values.items()):
            (staging / name).write_bytes(content)
        _set_publication_modes(staging)

        if destination.exists():
            if _tree_bytes(destination) != _tree_bytes(staging):
                raise PublicationError(
                    f"IMMUTABLE_REVISION_CONFLICT: {manifest.catalog_revision} already differs"
                )
            _set_publication_modes(destination)
            return destination
        os.replace(staging, destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def activate_revision(catalogs_root: Path, catalog_revision: str) -> Path:
    """Atomically select a verified revision and retain the previous active one."""

    revision = _CATALOG_REVISION_ADAPTER.validate_python(catalog_revision)
    selected = catalogs_root / revision
    if selected.is_symlink() or not selected.is_dir():
        raise PublicationError("ACTIVE_REVISION_MISSING: revision is not installed")
    manifest_path = selected / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PublicationError("ACTIVE_MANIFEST_MISSING: revision has no manifest")

    pointer_path = catalogs_root.parent / "catalog-pointer.json"
    existing: CatalogPointer | None = None
    if pointer_path.exists():
        if pointer_path.is_symlink() or not pointer_path.is_file():
            raise PublicationError("INVALID_CATALOG_POINTER: pointer is not a file")
        try:
            existing_bytes = pointer_path.read_bytes()
            existing = CatalogPointer.model_validate_json(existing_bytes)
        except (OSError, ValidationError) as exc:
            raise PublicationError("INVALID_CATALOG_POINTER: cannot preserve rollout") from exc
        canonical_existing = canonical_json_bytes(existing)
        if existing_bytes not in {canonical_existing, canonical_existing + b"\n"}:
            raise PublicationError("INVALID_CATALOG_POINTER: non-canonical JSON")
    if existing is None:
        served = (revision,)
    elif existing.active_catalog_revision == revision:
        served = existing.served_catalog_revisions
    else:
        served = (revision, existing.active_catalog_revision)

    for served_revision in served[1:]:
        served_path = catalogs_root / served_revision
        served_manifest = served_path / "manifest.json"
        if served_path.is_symlink() or not served_path.is_dir():
            raise PublicationError("PREVIOUS_REVISION_MISSING: rollout cannot be preserved")
        if served_manifest.is_symlink() or not served_manifest.is_file():
            raise PublicationError("PREVIOUS_MANIFEST_MISSING: rollout cannot be preserved")
    pointer = CatalogPointer(
        schema_version=1,
        active_catalog_revision=revision,
        served_catalog_revisions=served,
    )
    content = canonical_json_bytes(pointer)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".catalog-pointer.",
        dir=pointer_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, pointer_path)
        pointer_path.chmod(0o644)
        return pointer_path
    finally:
        if temporary.exists():
            temporary.unlink()


def _set_publication_modes(root: Path) -> None:
    """Make immutable catalog content traversable across service UIDs."""

    root.chmod(0o755)
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)


def _geometry_wire(geometry: BoundaryGeometry, *, counter: _Counter) -> dict[str, object]:
    polygons: list[list[list[list[float]]]] = []
    for polygon in geometry.polygons:
        counter.polygon_count += 1
        wire_polygon: list[list[list[float]]] = []
        for ring in polygon:
            counter.ring_count += 1
            ring_vertices = len(ring)
            counter.vertex_count += ring_vertices
            counter.max_ring_vertices = max(counter.max_ring_vertices, ring_vertices)
            wire_polygon.append([[longitude, latitude] for longitude, latitude in ring])
        polygons.append(wire_polygon)
    return {
        "schema_version": 1,
        "geometry_type": "MultiPolygon",
        "polygons": polygons,
    }


def _finalize_wire(
    wire: object,
    *,
    counter: _Counter,
    max_vertices: int,
) -> tuple[bytes, WireCounts, str]:
    content = canonical_json_bytes(wire)
    counts = counter.freeze(byte_length=len(content))
    _enforce_asset_budget(counts, max_vertices=max_vertices)
    asset_id = hashlib.sha256(content).hexdigest()
    return content, counts, asset_id


def _enforce_asset_budget(counts: WireCounts, *, max_vertices: int) -> None:
    if counts.feature_count > MAX_FEATURES:
        raise AssetBudgetError(
            f"ASSET_FEATURE_BUDGET: {counts.feature_count} > {MAX_FEATURES}"
        )
    if counts.byte_length > MAX_WIRE_BYTES:
        raise AssetBudgetError(
            f"ASSET_WIRE_BUDGET: {counts.byte_length} > {MAX_WIRE_BYTES}"
        )
    if counts.estimated_heap_bytes > MAX_HEAP_BYTES:
        raise AssetBudgetError(
            f"ASSET_HEAP_BUDGET: {counts.estimated_heap_bytes} > {MAX_HEAP_BYTES}"
        )
    if counts.ring_count > MAX_RINGS:
        raise AssetBudgetError(f"ASSET_RING_BUDGET: {counts.ring_count} > {MAX_RINGS}")
    if counts.max_ring_vertices > MAX_RING_VERTICES:
        raise AssetBudgetError(
            f"ASSET_MAX_RING_BUDGET: {counts.max_ring_vertices} > {MAX_RING_VERTICES}"
        )
    if counts.vertex_count > max_vertices:
        raise AssetBudgetError(
            f"ASSET_VERTEX_BUDGET: {counts.vertex_count} > {max_vertices}"
        )


def _pack_feature_sort_key(feature: PackFeature) -> tuple[int, str]:
    if isinstance(feature, ContextPackFeature):
        return (0, feature.feature_id)
    return (1, feature.scope_key)


def _pack_feature_identity(feature: PackFeature) -> tuple[str, str]:
    if isinstance(feature, ContextPackFeature):
        return (feature.kind, feature.feature_id)
    return (feature.kind, feature.scope_key)


def _validate_label(label: str) -> None:
    if not isinstance(label, str) or not 1 <= len(label) <= 120:
        raise ValueError("label must contain 1-120 Unicode codepoints")


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
