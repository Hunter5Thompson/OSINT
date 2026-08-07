"""Offline catalog verification, audit, and feasibility gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from spatial_catalog.emit import (
    BOUNDARY_MEDIA_TYPE,
    BOUNDARY_PACK_MEDIA_TYPE,
    MAX_FEATURES,
    MAX_HEAP_BYTES,
    MAX_RING_VERTICES,
    MAX_RINGS,
    MAX_WIRE_BYTES,
    ContextPackFeature,
    EmittedAsset,
    ScopePackFeature,
    WireCounts,
    emit_boundary_pack,
    emit_containment_boundary,
    emit_render_boundary,
)
from spatial_catalog.identity import parse_scope_key
from spatial_catalog.manifest import CatalogManifest, canonical_json_bytes, canonical_manifest_bytes
from spatial_catalog.models import (
    CatalogAttribution,
    ContainmentDescriptor,
    GeometryDescriptor,
    Lod,
)
from spatial_catalog.normalize import BoundaryGeometry, GeometryValidationError, normalize_geometry

MAX_SEED_CATALOG_BYTES = 25 * 1024 * 1024


class CatalogVerificationError(ValueError):
    """A catalog, asset, or feasibility record fails closed."""


@dataclass(frozen=True, slots=True)
class VerifiedAsset:
    asset_id: str
    media_type: str
    byte_length: int
    feature_count: int
    ring_count: int
    vertex_count: int
    max_ring_vertices: int
    estimated_heap_bytes: int


@dataclass(frozen=True, slots=True)
class VerifiedCatalog:
    catalog_revision: str
    asset_count: int
    total_bytes: int
    assets: tuple[VerifiedAsset, ...]


@dataclass(frozen=True, slots=True)
class ContainmentFeasibilityRecord:
    scope_key: str
    source_bytes: int
    normalized_bytes: int
    raw_ring_count: int
    raw_vertex_count: int
    asset: EmittedAsset
    max_error_m: float

    def __post_init__(self) -> None:
        parsed = parse_scope_key(self.scope_key)
        if parsed.canonical != self.scope_key:
            raise ValueError("feasibility scope key must be canonical")
        if min(
            self.source_bytes,
            self.normalized_bytes,
            self.raw_ring_count,
            self.raw_vertex_count,
        ) < 0:
            raise ValueError("feasibility counters must be non-negative")
        if not isinstance(self.asset.descriptor, ContainmentDescriptor):
            raise ValueError("containment record requires a containment descriptor")
        if self.asset.descriptor.max_error_m != self.max_error_m:
            raise ValueError("containment error must match its descriptor")


@dataclass(frozen=True, slots=True)
class WorldChildPackRecord:
    lod: Lod
    asset: EmittedAsset

    def __post_init__(self) -> None:
        descriptor = self.asset.descriptor
        if (
            not isinstance(descriptor, GeometryDescriptor)
            or descriptor.media_type != BOUNDARY_PACK_MEDIA_TYPE
            or descriptor.lod is not self.lod
        ):
            raise ValueError("world child record requires a matching pack descriptor")


@dataclass(frozen=True, slots=True)
class _DescriptorUse:
    descriptor: GeometryDescriptor | ContainmentDescriptor
    parent_scope_key: str | None
    allowed_child_scope_keys: frozenset[str]


def verify_catalog(
    catalog_dir: Path,
    *,
    max_seed_bytes: int = MAX_SEED_CATALOG_BYTES,
) -> VerifiedCatalog:
    """Verify immutable manifest, attribution, assets, hashes, and production counts."""

    manifest_path = catalog_dir / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise CatalogVerificationError(f"MANIFEST_MISSING: {manifest_path}") from exc
    try:
        manifest = CatalogManifest.model_validate_json(manifest_bytes)
    except ValidationError as exc:
        raise CatalogVerificationError(f"INVALID_MANIFEST: {exc}") from exc
    if canonical_manifest_bytes(manifest) != manifest_bytes:
        raise CatalogVerificationError("NON_CANONICAL_MANIFEST: manifest bytes are unstable")
    if catalog_dir.name != manifest.catalog_revision:
        raise CatalogVerificationError("CATALOG_DIRECTORY_REVISION_MISMATCH")

    _verify_attribution(
        catalog_dir / "attribution.json",
        manifest.catalog_revision,
        manifest.attribution_sources_sha256,
    )
    descriptor_uses = _descriptor_uses(manifest)
    if set(descriptor_uses) != set(manifest.assets):
        raise CatalogVerificationError("UNREFERENCED_MANIFEST_ASSET")

    assets_dir = catalog_dir / "assets"
    expected_names = {f"{asset_id}.json" for asset_id in manifest.assets}
    actual_names = (
        {path.name for path in assets_dir.iterdir() if path.is_file()}
        if assets_dir.is_dir()
        else set()
    )
    missing = sorted(expected_names - actual_names)
    if missing:
        raise CatalogVerificationError(f"ASSET_MISSING: {missing[0]}")
    extras = sorted(actual_names - expected_names)
    if extras:
        raise CatalogVerificationError(f"UNDECLARED_ASSET: {extras[0]}")

    total_bytes = sum(path.stat().st_size for path in catalog_dir.rglob("*") if path.is_file())
    if total_bytes > max_seed_bytes:
        raise CatalogVerificationError(
            f"SEED_CATALOG_SIZE: {total_bytes} > {max_seed_bytes} bytes"
        )

    verified_assets: list[VerifiedAsset] = []
    for asset_id in manifest.assets:
        content = (assets_dir / f"{asset_id}.json").read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != asset_id:
            raise CatalogVerificationError(
                f"ASSET_HASH_MISMATCH: expected {asset_id}, got {actual_hash}"
            )
        uses = descriptor_uses[asset_id]
        emitted = _reemit_asset(
            content,
            use=uses[0],
        )
        if emitted.content != content:
            raise CatalogVerificationError(f"NON_CANONICAL_ASSET: {asset_id}")
        for use in uses:
            _verify_descriptor(use.descriptor, emitted)
        verified_assets.append(
            VerifiedAsset(
                asset_id=asset_id,
                media_type=emitted.media_type,
                byte_length=emitted.counts.byte_length,
                feature_count=emitted.counts.feature_count,
                ring_count=emitted.counts.ring_count,
                vertex_count=emitted.counts.vertex_count,
                max_ring_vertices=emitted.counts.max_ring_vertices,
                estimated_heap_bytes=emitted.counts.estimated_heap_bytes,
            )
        )

    return VerifiedCatalog(
        catalog_revision=manifest.catalog_revision,
        asset_count=len(verified_assets),
        total_bytes=total_bytes,
        assets=tuple(verified_assets),
    )


def audit_catalog(catalog_dir: Path) -> bytes:
    """Return a deterministic machine-readable audit; no clocks enter output."""

    verified = verify_catalog(catalog_dir)
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "catalog_revision": verified.catalog_revision,
            "status": "pass",
            "asset_count": verified.asset_count,
            "total_bytes": verified.total_bytes,
            "limits": {
                "wire_bytes": MAX_WIRE_BYTES,
                "heap_bytes": MAX_HEAP_BYTES,
                "features": MAX_FEATURES,
                "rings": MAX_RINGS,
                "ring_vertices": MAX_RING_VERTICES,
                "seed_catalog_bytes": MAX_SEED_CATALOG_BYTES,
            },
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "media_type": asset.media_type,
                    "byte_length": asset.byte_length,
                    "feature_count": asset.feature_count,
                    "ring_count": asset.ring_count,
                    "vertex_count": asset.vertex_count,
                    "max_ring_vertices": asset.max_ring_vertices,
                    "estimated_heap_bytes": asset.estimated_heap_bytes,
                }
                for asset in verified.assets
            ],
        }
    )


def build_feasibility_report(
    *,
    catalog_revision: str,
    containment_records: tuple[ContainmentFeasibilityRecord, ...],
    mandatory_scope_keys: set[str],
    raw_ring_counts: Mapping[str, int] | None = None,
    world_child_packs: tuple[WorldChildPackRecord, ...],
    emitted_world_lods: set[Lod],
    preferred_world_lod: Lod,
) -> bytes:
    """Gate mandatory/top-ten containment and every emitted World child LOD."""

    records_by_scope = {record.scope_key: record for record in containment_records}
    if len(records_by_scope) != len(containment_records):
        raise CatalogVerificationError("DUPLICATE_CONTAINMENT_SCOPE")
    ring_counts = raw_ring_counts or {
        record.scope_key: record.raw_ring_count for record in containment_records
    }
    if any(count < 0 for count in ring_counts.values()):
        raise CatalogVerificationError("INVALID_RAW_RING_COUNT")
    top_ten = {
        scope_key
        for scope_key, _ in sorted(
            ring_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    }
    required = set(mandatory_scope_keys) | top_ten
    missing = sorted(required - records_by_scope.keys())
    if missing:
        raise CatalogVerificationError(f"CONTAINMENT_COVERAGE_MISSING: {missing[0]}")
    for scope_key in mandatory_scope_keys:
        if parse_scope_key(scope_key).canonical != scope_key:
            raise CatalogVerificationError(f"INVALID_MANDATORY_SCOPE: {scope_key}")

    packs_by_lod = {record.lod: record for record in world_child_packs}
    if len(packs_by_lod) != len(world_child_packs):
        raise CatalogVerificationError("DUPLICATE_WORLD_PACK_LOD")
    missing_lods = sorted(lod.value for lod in emitted_world_lods - packs_by_lod.keys())
    if preferred_world_lod not in emitted_world_lods or missing_lods:
        detail = missing_lods[0] if missing_lods else preferred_world_lod.value
        raise CatalogVerificationError(f"WORLD_PACK_LOD_MISSING: {detail}")
    extra_lods = sorted(lod.value for lod in packs_by_lod.keys() - emitted_world_lods)
    if extra_lods:
        raise CatalogVerificationError(f"UNDECLARED_WORLD_PACK_LOD: {extra_lods[0]}")

    ordered_containment = tuple(records_by_scope[key] for key in sorted(required))
    for record in ordered_containment:
        _enforce_feasibility_counts(record.asset.counts)
        if record.max_error_m > 50:
            raise CatalogVerificationError(
                f"CONTAINMENT_ERROR_BUDGET: {record.scope_key}: {record.max_error_m}"
            )
    ordered_packs = tuple(packs_by_lod[lod] for lod in sorted(packs_by_lod, key=_lod_order))
    for record in ordered_packs:
        _enforce_feasibility_counts(record.asset.counts)

    return canonical_json_bytes(
        {
            "schema_version": 1,
            "catalog_revision": catalog_revision,
            "status": "pass",
            "containment": {
                "max_error_semantics": (
                    "deviation_from_locked_source_geometry_not_source_cartographic_accuracy"
                ),
                "mandatory_scope_keys": sorted(mandatory_scope_keys),
                "top_ten_raw_ring_scope_keys": sorted(top_ten),
                "coverage_scope_keys": sorted(required),
                "features": [_containment_report_value(record) for record in ordered_containment],
            },
            "world_child_packs": [
                _world_pack_report_value(record, preferred_world_lod=preferred_world_lod)
                for record in ordered_packs
            ],
        }
    )


def _descriptor_uses(manifest: CatalogManifest) -> dict[str, tuple[_DescriptorUse, ...]]:
    children: dict[str, frozenset[str]] = {}
    for record in manifest.scopes:
        parent = record.scope.parent_key
        if parent is not None:
            children[parent] = children.get(parent, frozenset()) | {record.scope.key}

    uses: dict[str, list[_DescriptorUse]] = {}
    for record in manifest.scopes:
        for descriptor in record.presentation.outline_lods.values():
            uses.setdefault(descriptor.asset_id, []).append(
                _DescriptorUse(descriptor, None, frozenset())
            )
        for descriptor in record.presentation.children_lods.values():
            uses.setdefault(descriptor.asset_id, []).append(
                _DescriptorUse(
                    descriptor,
                    record.scope.key,
                    children.get(record.scope.key, frozenset()),
                )
            )
        if record.presentation.containment is not None:
            descriptor = record.presentation.containment
            uses.setdefault(descriptor.asset_id, []).append(
                _DescriptorUse(descriptor, None, frozenset())
            )
    return {asset_id: tuple(values) for asset_id, values in uses.items()}


def _reemit_asset(
    content: bytes,
    *,
    use: _DescriptorUse,
) -> EmittedAsset:
    try:
        payload = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogVerificationError(f"INVALID_ASSET_JSON: {exc}") from exc
    if canonical_json_bytes(payload) != content:
        raise CatalogVerificationError("NON_CANONICAL_ASSET_JSON")

    descriptor = use.descriptor
    try:
        if isinstance(descriptor, ContainmentDescriptor):
            geometry = _decode_geometry(payload)
            return emit_containment_boundary(
                geometry,
                max_error_m=descriptor.max_error_m,
                max_vertices=descriptor.vertex_count,
            )
        if descriptor.media_type == BOUNDARY_MEDIA_TYPE:
            geometry = _decode_geometry(payload)
            return emit_render_boundary(
                geometry,
                lod=descriptor.lod,
                max_vertices=descriptor.vertex_count,
            )
        if descriptor.media_type == BOUNDARY_PACK_MEDIA_TYPE:
            return _reemit_pack(
                payload,
                descriptor=descriptor,
                use=use,
            )
    except (GeometryValidationError, ValueError) as exc:
        raise CatalogVerificationError(f"INVALID_ASSET: {exc}") from exc
    raise CatalogVerificationError("UNSUPPORTED_ASSET_MEDIA_TYPE")


def _reemit_pack(
    payload: object,
    *,
    descriptor: GeometryDescriptor,
    use: _DescriptorUse,
) -> EmittedAsset:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "parent_scope_key",
        "features",
    }:
        raise CatalogVerificationError("INVALID_PACK_SCHEMA")
    if payload["schema_version"] != 1:
        raise CatalogVerificationError("INVALID_PACK_SCHEMA_VERSION")
    if payload["parent_scope_key"] != use.parent_scope_key:
        raise CatalogVerificationError("PACK_PARENT_SCOPE_MISMATCH")
    raw_features = payload["features"]
    if not isinstance(raw_features, list):
        raise CatalogVerificationError("INVALID_PACK_FEATURES")

    features: list[ScopePackFeature | ContextPackFeature] = []
    for raw in raw_features:
        if not isinstance(raw, dict):
            raise CatalogVerificationError("INVALID_PACK_FEATURE")
        if raw.get("kind") == "scope" and set(raw) == {
            "kind",
            "scope_key",
            "label",
            "geometry",
        }:
            features.append(
                ScopePackFeature(
                    scope_key=raw["scope_key"],
                    label=raw["label"],
                    geometry=_decode_geometry(raw["geometry"]),
                )
            )
        elif raw.get("kind") == "context" and set(raw) == {
            "kind",
            "feature_id",
            "label",
            "non_scope_reason",
            "geometry",
        }:
            features.append(
                ContextPackFeature(
                    feature_id=raw["feature_id"],
                    label=raw["label"],
                    non_scope_reason=raw["non_scope_reason"],
                    geometry=_decode_geometry(raw["geometry"]),
                )
            )
        else:
            raise CatalogVerificationError("INVALID_PACK_FEATURE_SCHEMA")
    return emit_boundary_pack(
        parent_scope_key=use.parent_scope_key or "",
        lod=descriptor.lod,
        allowed_child_scope_keys=use.allowed_child_scope_keys,
        features=tuple(features),
        max_vertices=descriptor.vertex_count,
    )


def _decode_geometry(payload: object) -> BoundaryGeometry:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "geometry_type",
        "polygons",
    }:
        raise CatalogVerificationError("INVALID_BOUNDARY_GEOMETRY_SCHEMA")
    if payload["schema_version"] != 1 or payload["geometry_type"] != "MultiPolygon":
        raise CatalogVerificationError("INVALID_BOUNDARY_GEOMETRY_VERSION")
    return normalize_geometry(
        {"type": "MultiPolygon", "coordinates": payload["polygons"]},
        precision=6,
    )


def _verify_descriptor(
    expected: GeometryDescriptor | ContainmentDescriptor,
    emitted: EmittedAsset,
) -> None:
    actual = emitted.descriptor
    expected_counts = (
        expected.byte_length,
        expected.vertex_count,
        getattr(expected, "feature_count", None),
    )
    actual_counts = (
        actual.byte_length,
        actual.vertex_count,
        getattr(actual, "feature_count", None),
    )
    if (
        expected_counts != actual_counts
        or expected.asset_id != emitted.asset_id
        or expected.media_type != emitted.media_type
    ):
        raise CatalogVerificationError(f"DESCRIPTOR_COUNT_MISMATCH: {expected.asset_id}")


def _verify_attribution(
    path: Path,
    catalog_revision: str,
    attribution_sources_sha256: str,
) -> None:
    try:
        content = path.read_bytes()
        attribution = CatalogAttribution.model_validate_json(content)
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CatalogVerificationError("ATTRIBUTION_MISSING_OR_INVALID") from exc
    if canonical_json_bytes(attribution) != content:
        raise CatalogVerificationError("NON_CANONICAL_ATTRIBUTION")
    if attribution.catalog_revision != catalog_revision:
        raise CatalogVerificationError("INVALID_ATTRIBUTION_SCHEMA")
    actual_sources_sha256 = hashlib.sha256(
        canonical_json_bytes(attribution.sources)
    ).hexdigest()
    if actual_sources_sha256 != attribution_sources_sha256:
        raise CatalogVerificationError("ATTRIBUTION_SOURCES_HASH_MISMATCH")


def _enforce_feasibility_counts(counts: WireCounts) -> None:
    violations = (
        ("wire", counts.byte_length, MAX_WIRE_BYTES),
        ("heap", counts.estimated_heap_bytes, MAX_HEAP_BYTES),
        ("features", counts.feature_count, MAX_FEATURES),
        ("rings", counts.ring_count, MAX_RINGS),
        ("ring_vertices", counts.max_ring_vertices, MAX_RING_VERTICES),
    )
    for name, actual, maximum in violations:
        if actual > maximum:
            raise CatalogVerificationError(
                f"FEASIBILITY_{name.upper()}_BUDGET: {actual} > {maximum}"
            )


def _containment_report_value(record: ContainmentFeasibilityRecord) -> dict[str, object]:
    counts = record.asset.counts
    return {
        "scope_key": record.scope_key,
        "asset_id": record.asset.asset_id,
        "source_bytes": record.source_bytes,
        "normalized_bytes": record.normalized_bytes,
        "raw_ring_count": record.raw_ring_count,
        "raw_vertex_count": record.raw_vertex_count,
        "ring_count": counts.ring_count,
        "vertex_count": counts.vertex_count,
        "max_ring_vertices": counts.max_ring_vertices,
        "canonical_wire_bytes": counts.byte_length,
        "estimated_heap_bytes": counts.estimated_heap_bytes,
        "max_error_m": record.max_error_m,
        "status": "pass",
    }


def _world_pack_report_value(
    record: WorldChildPackRecord,
    *,
    preferred_world_lod: Lod,
) -> dict[str, object]:
    descriptor = record.asset.descriptor
    if not isinstance(descriptor, GeometryDescriptor):
        raise CatalogVerificationError("INVALID_WORLD_PACK_DESCRIPTOR")
    counts = record.asset.counts
    return {
        "lod": record.lod.value,
        "preferred": record.lod is preferred_world_lod,
        "asset_id": record.asset.asset_id,
        "feature_count": counts.feature_count,
        "canonical_wire_bytes": counts.byte_length,
        "estimated_heap_bytes": counts.estimated_heap_bytes,
        "ring_count": counts.ring_count,
        "max_ring_vertices": counts.max_ring_vertices,
        "serialized_vertex_occurrences": counts.vertex_count,
        "descriptor_vertex_count": descriptor.vertex_count,
        "status": "pass",
    }


def _lod_order(lod: Lod) -> int:
    return {Lod.OVERVIEW: 0, Lod.REGIONAL: 1, Lod.LOCAL: 2}[lod]
