"""Pure stages for the reviewed, deterministic Spatial Scope seed compiler."""

from __future__ import annotations

import copy
import io
import json
import re
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from spatial_catalog.audit import (
    ContainmentFeasibilityRecord,
    WorldChildPackRecord,
    build_feasibility_report,
    verify_catalog,
)
from spatial_catalog.emit import (
    AttributionRecord,
    ContextPackFeature,
    EmittedAsset,
    ScopePackFeature,
    emit_attribution,
    emit_boundary_pack,
    emit_containment_boundary,
    emit_render_boundary,
    publish_revision,
)
from spatial_catalog.identity import (
    CountryCrosswalk,
    CountryCrosswalkRecord,
    resolve_country,
    validate_natural_earth_coverage,
)
from spatial_catalog.lod import (
    LOD_POLICIES,
    BoundaryFeature,
    LodMetrics,
    PinnedTopologyTool,
    build_bounded_lod,
    build_containment,
    dissolve_complete_children,
    prepare_topology_tool,
    vertex_count,
)
from spatial_catalog.manifest import (
    DerivationInputs,
    ManifestDraft,
    ManifestScopeInput,
    build_manifest,
    canonical_json_bytes,
)
from spatial_catalog.models import (
    CatalogProvenance,
    ContainmentDescriptor,
    GeometryDescriptor,
    Lod,
    ScopeKind,
    ScopeNode,
    ScopePresentation,
)
from spatial_catalog.normalize import (
    BoundaryGeometry,
    GeometryValidationError,
    normalize_geometry,
)
from spatial_catalog.source_lock import (
    CATALOG_PLAN_PATH,
    CatalogPlan,
    CatalogPlanEntry,
    LockedSource,
    SourceLock,
    load_catalog_plan,
    verify_source_bytes,
)

NORMALIZATION_DROP_POLICY_PATH = (
    Path(__file__).resolve().parent / "data" / "normalization-drop-policy.json"
)
_ADMIN1_ISO = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
_MAX_ADMIN1_ARCHIVE_FILES = 100
_MAX_ADMIN1_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
_CONTAINMENT_MAX_VERTICES = 120_000


@dataclass(frozen=True, slots=True)
class _DropRule:
    source_code: str
    source_label: str
    error_code: str
    polygon_index: int
    ring_index: int
    position_index: int
    expected_position: tuple[float, float]
    review_note: str


@dataclass(frozen=True, slots=True)
class _DropPolicy:
    source_id: str
    source_release: str
    rules: tuple[_DropRule, ...]


@dataclass(frozen=True, slots=True)
class _DropAudit:
    source_code: str
    source_label: str
    error_code: str
    polygon_index: int
    ring_index: int
    position_index: int
    dropped_position: tuple[float, float]
    review_note: str


@dataclass(frozen=True, slots=True)
class _Admin0Feature:
    source_code: str
    label: str
    record: CountryCrosswalkRecord
    geometry: BoundaryGeometry
    source_bytes: int
    normalized_bytes: int
    raw_ring_count: int
    raw_vertex_count: int


@dataclass(frozen=True, slots=True)
class _Admin1Feature:
    scope_key: str
    label: str
    geometry: BoundaryGeometry
    source_bytes: int
    raw_ring_count: int
    raw_vertex_count: int


@dataclass(frozen=True, slots=True)
class _Admin1Build:
    plan_entry: CatalogPlanEntry
    source: LockedSource
    full_features: tuple[_Admin1Feature, ...]
    full_parent: BoundaryGeometry
    parent_render: EmittedAsset
    child_pack: EmittedAsset
    child_containment: Mapping[str, EmittedAsset]
    metrics: LodMetrics
    containment_metrics: LodMetrics


def compile_catalog(
    *,
    source_lock: SourceLock,
    cache_dir: Path,
    output_root: Path,
    policy: str,
    catalog_plan_path: Path = CATALOG_PLAN_PATH,
    normalization_drop_policy_path: Path = NORMALIZATION_DROP_POLICY_PATH,
) -> Path:
    """Compile, publish, and verify one immutable catalog from locked cached bytes."""

    if policy != "odin-reference-v1":
        raise ValueError(f"UNSUPPORTED_BOUNDARY_POLICY: {policy}")

    cached = _read_all_cached_sources(source_lock, cache_dir=cache_dir)
    crosswalk_source = source_lock.source("odin-country-crosswalk")
    crosswalk = CountryCrosswalk.model_validate_json(cached[crosswalk_source.source_id])
    catalog_plan = load_catalog_plan(
        catalog_plan_path,
        crosswalk=crosswalk,
        source_lock=source_lock,
    )
    if catalog_plan.boundary_policy != policy:
        raise ValueError("CATALOG_PLAN_POLICY_MISMATCH")

    natural_earth_source = source_lock.source("natural-earth-admin0")
    drop_policy = _load_drop_policy(normalization_drop_policy_path)
    admin0, drop_audits = _parse_admin0(
        cached[natural_earth_source.source_id],
        source=natural_earth_source,
        crosswalk=crosswalk,
        drop_policy=drop_policy,
    )
    active_plan = {
        entry.scope_key: entry
        for entry in catalog_plan.scopes
        if entry.activation == "active"
    }
    admin0_by_scope = {
        feature.record.scope_key: feature
        for feature in admin0
        if feature.record.scope_key is not None
    }
    missing_active = sorted(active_plan.keys() - admin0_by_scope.keys())
    if missing_active:
        raise ValueError(f"ACTIVE_SCOPE_GEOMETRY_MISSING: {missing_active[0]}")

    mapshaper_source = source_lock.source("mapshaper")
    if "+odin-offline-v1" not in mapshaper_source.release:
        raise ValueError("TOPOLOGY_TOOL_RELEASE_NOT_OFFLINE_BUNDLE")
    mapshaper_version = mapshaper_source.release.split("+", 1)[0]

    with tempfile.TemporaryDirectory(prefix="odin-spatial-build-") as temporary_name:
        work_root = Path(temporary_name)
        tool = prepare_topology_tool(
            source_archive=_cached_source_path(cache_dir, mapshaper_source),
            expected_sha256=mapshaper_source.sha256,
            expected_bundle_release=mapshaper_source.release,
            expected_version=mapshaper_version,
            work_dir=work_root / "topology-tool",
        )
        world_source_features = tuple(
            BoundaryFeature(_admin0_feature_id(feature), feature.geometry)
            for feature in admin0
            if feature.record.scope_key in active_plan
            or feature.record.disposition == "non_scope_feature"
        )
        world_work = work_root / "world-overview"
        world_work.mkdir()
        world_lod, world_metrics = build_bounded_lod(
            world_source_features,
            policy=LOD_POLICIES["overview"],
            tool=tool,
            work_dir=world_work,
        )
        world_output = {feature.feature_id: feature.geometry for feature in world_lod}
        world_pack = _emit_world_pack(
            admin0,
            active_plan=active_plan,
            output=world_output,
        )

        admin1_builds: dict[str, _Admin1Build] = {}
        for entry in sorted(active_plan.values(), key=lambda item: item.scope_key):
            if not entry.children_available:
                continue
            if entry.children_source_id is None:
                raise ValueError(f"CHILD_SOURCE_MISSING: {entry.scope_key}")
            child_source = source_lock.source(entry.children_source_id)
            admin1_builds[entry.scope_key] = _build_admin1(
                entry,
                source=child_source,
                source_bytes=cached[child_source.source_id],
                tool=tool,
                work_dir=work_root / f"admin1-{entry.scope_key.replace(':', '-')}",
            )

        assets: dict[str, EmittedAsset] = {}
        _add_asset(assets, world_pack)
        for built in admin1_builds.values():
            _add_asset(assets, built.parent_render)
            _add_asset(assets, built.child_pack)
            for asset in built.child_containment.values():
                _add_asset(assets, asset)

        containment_assets, feasibility_records, raw_ring_counts = _build_required_containment(
            admin0,
            active_plan=active_plan,
        )
        for asset in containment_assets.values():
            _add_asset(assets, asset)

        manifest = _build_catalog_manifest(
            source_lock=source_lock,
            crosswalk_source=crosswalk_source,
            catalog_plan=catalog_plan,
            active_plan=active_plan,
            admin0=admin0,
            world_pack=world_pack,
            containment_assets=containment_assets,
            admin1_builds=admin1_builds,
            asset_ids=tuple(assets),
        )
        feasibility = build_feasibility_report(
            catalog_revision=manifest.catalog_revision,
            containment_records=feasibility_records,
            mandatory_scope_keys={
                entry.scope_key
                for entry in active_plan.values()
                if entry.client_strict_containment_required
            },
            raw_ring_counts=raw_ring_counts,
            world_child_packs=(WorldChildPackRecord(Lod.OVERVIEW, world_pack),),
            emitted_world_lods={Lod.OVERVIEW},
            preferred_world_lod=Lod.OVERVIEW,
        )
        attribution = emit_attribution(
            manifest.catalog_revision,
            tuple(
                AttributionRecord(source.source_id, source.license_id, source.attribution)
                for source in source_lock.sources
            ),
        )
        reports = {
            "build-provenance.json": _build_provenance_bytes(
                manifest.catalog_revision,
                tool=tool,
                mapshaper_source=mapshaper_source,
            ),
            "containment-feasibility.json": feasibility,
            "lod-audit.json": _lod_audit_bytes(
                manifest.catalog_revision,
                mapshaper_source=mapshaper_source,
                world_pack=world_pack,
                world_metrics=world_metrics,
                admin1_builds=admin1_builds,
                world_original_vertices=sum(
                    vertex_count(feature.geometry) for feature in world_source_features
                ),
            ),
            "normalization-audit.json": _normalization_audit_bytes(
                manifest.catalog_revision,
                source=natural_earth_source,
                drops=drop_audits,
            ),
        }
        destination = publish_revision(
            output_root,
            manifest=manifest,
            assets=tuple(assets.values()),
            attribution=attribution,
            reports=reports,
        )
    verify_catalog(destination)
    return destination


def _read_all_cached_sources(
    source_lock: SourceLock,
    *,
    cache_dir: Path,
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for source in sorted(source_lock.sources, key=lambda item: item.source_id):
        payload = _cached_source_path(cache_dir, source).read_bytes()
        verify_source_bytes(source, payload)
        payloads[source.source_id] = payload
    return payloads


def _cached_source_path(cache_dir: Path, source: LockedSource) -> Path:
    return cache_dir / f"{source.source_id}.source"


def _parse_admin0(
    payload: bytes,
    *,
    source: LockedSource,
    crosswalk: CountryCrosswalk,
    drop_policy: _DropPolicy,
) -> tuple[tuple[_Admin0Feature, ...], tuple[_DropAudit, ...]]:
    raw = _json_object(payload, context="natural-earth-admin0")
    if raw.get("type") != "FeatureCollection" or not isinstance(raw.get("features"), list):
        raise ValueError("INVALID_ADMIN0_SOURCE: expected FeatureCollection")

    reviewed_codes = {record.source_code for record in crosswalk.records}
    classified: list[tuple[str, str, CountryCrosswalkRecord, Mapping[str, object]]] = []
    for index, feature in enumerate(raw["features"]):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise ValueError(f"INVALID_ADMIN0_FEATURE: {index}")
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, Mapping) or not isinstance(geometry, Mapping):
            raise ValueError(f"INVALID_ADMIN0_FEATURE: {index}")
        label = properties.get("NAME")
        if not isinstance(label, str) or not 1 <= len(label) <= 120:
            raise ValueError(f"INVALID_ADMIN0_LABEL: {index}")
        source_code = _admin0_source_code(properties, reviewed_codes=reviewed_codes)
        record = resolve_country(
            crosswalk,
            source_system="natural-earth-admin0",
            source_code=source_code,
        )
        classified.append((source_code, label, record, geometry))

    validate_natural_earth_coverage(
        crosswalk,
        [(source_code, label) for source_code, label, _, _ in classified],
    )
    if len(classified) != len(crosswalk.records):
        raise ValueError("ADMIN0_CROSSWALK_CARDINALITY_MISMATCH")

    rules = {rule.source_code: rule for rule in drop_policy.rules}
    used_rules: set[str] = set()
    normalized: list[_Admin0Feature] = []
    audits: list[_DropAudit] = []
    for source_code, label, record, raw_geometry in classified:
        geometry_value: object = raw_geometry
        try:
            geometry = normalize_geometry(geometry_value, precision=6)
        except GeometryValidationError as exc:
            error_code = str(exc).split(":", 1)[0]
            rule = rules.get(source_code)
            if (
                source.release != drop_policy.source_release
                or source.source_id != drop_policy.source_id
                or rule is None
                or rule.source_label != label
                or rule.error_code != error_code
            ):
                raise GeometryValidationError(
                    f"UNREVIEWED_NORMALIZATION_FAILURE: {source_code}: {exc}"
                ) from exc
            geometry_value = _apply_drop_rule(raw_geometry, rule)
            geometry = normalize_geometry(geometry_value, precision=6)
            used_rules.add(source_code)
            audits.append(
                _DropAudit(
                    source_code=source_code,
                    source_label=label,
                    error_code=error_code,
                    polygon_index=rule.polygon_index,
                    ring_index=rule.ring_index,
                    position_index=rule.position_index,
                    dropped_position=rule.expected_position,
                    review_note=rule.review_note,
                )
            )
        raw_rings, raw_vertices = _raw_geometry_counts(raw_geometry)
        normalized.append(
            _Admin0Feature(
                source_code=source_code,
                label=label,
                record=record,
                geometry=geometry,
                source_bytes=len(canonical_json_bytes(raw_geometry)),
                normalized_bytes=len(canonical_json_bytes(geometry.to_wire())),
                raw_ring_count=raw_rings,
                raw_vertex_count=raw_vertices,
            )
        )

    if source.release == drop_policy.source_release:
        unused = sorted(rules.keys() - used_rules)
        if unused:
            raise ValueError(f"UNUSED_NORMALIZATION_DROP_RULE: {unused[0]}")
    return tuple(sorted(normalized, key=_admin0_sort_key)), tuple(
        sorted(audits, key=lambda audit: audit.source_code)
    )


def _admin0_source_code(
    properties: Mapping[str, object],
    *,
    reviewed_codes: set[str],
) -> str:
    candidates: list[str] = []
    for key in ("UN_A3", "ISO_N3", "ISO_N3_EH"):
        value = properties.get(key)
        candidate = (
            str(value)
            if isinstance(value, (str, int)) and not isinstance(value, bool)
            else ""
        )
        if re.fullmatch(r"[0-9]{3}", candidate):
            candidates.append(candidate)
    name = properties.get("NAME")
    if isinstance(name, str) and name in reviewed_codes:
        candidates.append(name)
    matched = [candidate for candidate in candidates if candidate in reviewed_codes]
    if not matched:
        raise ValueError(f"UNRESOLVED_ADMIN0_SOURCE_CODE: {name!r}")
    return matched[0]


def _admin0_feature_id(feature: _Admin0Feature) -> str:
    return feature.record.scope_key or feature.record.record_id


def _admin0_sort_key(feature: _Admin0Feature) -> tuple[int, str]:
    if feature.record.scope_key is not None:
        return (0, feature.record.scope_key)
    return (1, feature.record.record_id)


def _emit_world_pack(
    admin0: Sequence[_Admin0Feature],
    *,
    active_plan: Mapping[str, CatalogPlanEntry],
    output: Mapping[str, BoundaryGeometry],
) -> EmittedAsset:
    features: list[ScopePackFeature | ContextPackFeature] = []
    for feature in admin0:
        feature_id = _admin0_feature_id(feature)
        geometry = output.get(feature_id)
        if geometry is None:
            if (
                feature.record.scope_key in active_plan
                or feature.record.disposition == "non_scope_feature"
            ):
                raise ValueError(f"WORLD_LOD_FEATURE_MISSING: {feature_id}")
            continue
        if feature.record.scope_key is not None:
            if feature.record.scope_key not in active_plan:
                continue
            features.append(
                ScopePackFeature(feature.record.scope_key, feature.label, geometry)
            )
        else:
            if feature.record.non_scope_reason is None:
                raise ValueError(f"NON_SCOPE_REASON_MISSING: {feature.source_code}")
            features.append(
                ContextPackFeature(
                    feature.record.record_id,
                    feature.label,
                    feature.record.non_scope_reason,
                    geometry,
                )
            )
    return emit_boundary_pack(
        parent_scope_key="world",
        lod=Lod.OVERVIEW,
        allowed_child_scope_keys=set(active_plan),
        features=tuple(features),
    )


def _build_admin1(
    entry: CatalogPlanEntry,
    *,
    source: LockedSource,
    source_bytes: bytes,
    tool: PinnedTopologyTool,
    work_dir: Path,
) -> _Admin1Build:
    if entry.scope_key != "country:UKR" or source.source_id != "geoboundaries-gbopen-ukr-admin1":
        raise ValueError(f"UNSUPPORTED_ADMIN1_BUILD: {entry.scope_key}")
    features = _parse_admin1_zip(source_bytes)
    work_dir.mkdir()
    regional_work = work_dir / "regional"
    regional_work.mkdir()
    lod_features, metrics = build_bounded_lod(
        tuple(BoundaryFeature(feature.scope_key, feature.geometry) for feature in features),
        policy=LOD_POLICIES["regional"],
        tool=tool,
        work_dir=regional_work,
    )
    output = {feature.feature_id: feature.geometry for feature in lod_features}
    simplified = tuple(
        BoundaryFeature(feature.scope_key, output[feature.scope_key]) for feature in features
    )
    parent_render = emit_render_boundary(
        dissolve_complete_children(simplified),
        lod=Lod.REGIONAL,
    )
    child_pack = emit_boundary_pack(
        parent_scope_key=entry.scope_key,
        lod=Lod.REGIONAL,
        allowed_child_scope_keys={feature.scope_key for feature in features},
        features=tuple(
            ScopePackFeature(feature.scope_key, feature.label, output[feature.scope_key])
            for feature in features
        ),
    )
    containment_policy = LOD_POLICIES["local"].with_limits(
        max_error_m=50,
        max_vertices=1_000_000,
    )
    containment_work = work_dir / "containment-children"
    containment_work.mkdir()
    containment_features, containment_metrics = build_bounded_lod(
        tuple(BoundaryFeature(feature.scope_key, feature.geometry) for feature in features),
        policy=containment_policy,
        tool=tool,
        work_dir=containment_work,
    )
    containment_output = {
        feature.feature_id: feature.geometry for feature in containment_features
    }
    child_containment: dict[str, EmittedAsset] = {}
    for feature in features:
        result = build_containment(
            feature.geometry,
            max_vertices=_CONTAINMENT_MAX_VERTICES,
            strict=True,
            candidate=containment_output[feature.scope_key],
        )
        if result is None:  # pragma: no cover - strict=True cannot return None
            raise ValueError(f"ADMIN1_CONTAINMENT_MISSING: {feature.scope_key}")
        child_containment[feature.scope_key] = emit_containment_boundary(
            result.geometry,
            max_error_m=result.max_error_m,
            max_vertices=_CONTAINMENT_MAX_VERTICES,
        )
    full_parent = dissolve_complete_children(
        tuple(BoundaryFeature(feature.scope_key, feature.geometry) for feature in features)
    )
    return _Admin1Build(
        plan_entry=entry,
        source=source,
        full_features=features,
        full_parent=full_parent,
        parent_render=parent_render,
        child_pack=child_pack,
        child_containment=child_containment,
        metrics=metrics,
        containment_metrics=containment_metrics,
    )


def _parse_admin1_zip(payload: bytes) -> tuple[_Admin1Feature, ...]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"INVALID_ADMIN1_ARCHIVE: {exc}") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_ADMIN1_ARCHIVE_FILES:
            raise ValueError("ADMIN1_ARCHIVE_FILE_LIMIT")
        if sum(info.file_size for info in infos) > _MAX_ADMIN1_UNCOMPRESSED_BYTES:
            raise ValueError("ADMIN1_ARCHIVE_SIZE_LIMIT")
        for info in infos:
            path = Path(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"UNSAFE_ADMIN1_ARCHIVE: {info.filename}")
        filename = "geoBoundaries-UKR-ADM1.geojson"
        if [info.filename for info in infos].count(filename) != 1:
            raise ValueError("ADMIN1_GEOJSON_MISSING_OR_DUPLICATE")
        raw = _json_object(archive.read(filename), context="geoBoundaries Admin1")

    if raw.get("type") != "FeatureCollection" or not isinstance(raw.get("features"), list):
        raise ValueError("INVALID_ADMIN1_SOURCE: expected FeatureCollection")
    features: list[_Admin1Feature] = []
    for index, feature in enumerate(raw["features"]):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise ValueError(f"INVALID_ADMIN1_FEATURE: {index}")
        properties = feature.get("properties")
        raw_geometry = feature.get("geometry")
        if not isinstance(properties, Mapping) or not isinstance(raw_geometry, Mapping):
            raise ValueError(f"INVALID_ADMIN1_FEATURE: {index}")
        shape_id = properties.get("shapeID")
        shape_iso = properties.get("shapeISO")
        label = properties.get("shapeName")
        if (
            properties.get("shapeGroup") != "UKR"
            or properties.get("shapeType") != "ADM1"
            or not isinstance(shape_id, str)
            or not isinstance(label, str)
        ):
            raise ValueError(f"INVALID_ADMIN1_PROPERTIES: {index}")
        scope_key = (
            f"admin1:iso3166-2:{shape_iso}"
            if isinstance(shape_iso, str) and _ADMIN1_ISO.fullmatch(shape_iso)
            else f"admin1:gbopen:{shape_id}"
        )
        raw_rings, raw_vertices = _raw_geometry_counts(raw_geometry)
        features.append(
            _Admin1Feature(
                scope_key=scope_key,
                label=label,
                geometry=normalize_geometry(raw_geometry, precision=6),
                source_bytes=len(canonical_json_bytes(raw_geometry)),
                raw_ring_count=raw_rings,
                raw_vertex_count=raw_vertices,
            )
        )
    ordered = tuple(sorted(features, key=lambda feature: feature.scope_key))
    if len({feature.scope_key for feature in ordered}) != len(ordered):
        raise ValueError("DUPLICATE_ADMIN1_SCOPE_KEY")
    return ordered


def _build_required_containment(
    admin0: Sequence[_Admin0Feature],
    *,
    active_plan: Mapping[str, CatalogPlanEntry],
) -> tuple[
    dict[str, EmittedAsset],
    tuple[ContainmentFeasibilityRecord, ...],
    dict[str, int],
]:
    scoped = {
        feature.record.scope_key: feature
        for feature in admin0
        if feature.record.scope_key in active_plan
    }
    raw_ring_counts = {
        scope_key: feature.raw_ring_count for scope_key, feature in scoped.items()
    }
    top_ten = {
        scope_key
        for scope_key, _ in sorted(
            raw_ring_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    }
    mandatory = {
        entry.scope_key
        for entry in active_plan.values()
        if entry.client_strict_containment_required
    }
    required = top_ten | mandatory
    assets: dict[str, EmittedAsset] = {}
    records: list[ContainmentFeasibilityRecord] = []
    for scope_key in sorted(required):
        feature = scoped[scope_key]
        geometry = feature.geometry
        containment_candidate = geometry
        source_bytes = feature.source_bytes
        normalized_bytes = feature.normalized_bytes
        raw_ring_count = feature.raw_ring_count
        raw_vertex_count = feature.raw_vertex_count
        result = build_containment(
            geometry,
            max_vertices=_CONTAINMENT_MAX_VERTICES,
            strict=True,
            candidate=containment_candidate,
        )
        if result is None:  # pragma: no cover - strict=True cannot return None
            raise ValueError(f"CONTAINMENT_MISSING: {scope_key}")
        asset = emit_containment_boundary(
            result.geometry,
            max_error_m=result.max_error_m,
            max_vertices=_CONTAINMENT_MAX_VERTICES,
        )
        assets[scope_key] = asset
        records.append(
            ContainmentFeasibilityRecord(
                scope_key=scope_key,
                source_bytes=source_bytes,
                normalized_bytes=normalized_bytes,
                raw_ring_count=raw_ring_count,
                raw_vertex_count=raw_vertex_count,
                asset=asset,
                max_error_m=result.max_error_m,
            )
        )
    return assets, tuple(records), raw_ring_counts


def _build_catalog_manifest(
    *,
    source_lock: SourceLock,
    crosswalk_source: LockedSource,
    catalog_plan: CatalogPlan,
    active_plan: Mapping[str, CatalogPlanEntry],
    admin0: Sequence[_Admin0Feature],
    world_pack: EmittedAsset,
    containment_assets: Mapping[str, EmittedAsset],
    admin1_builds: Mapping[str, _Admin1Build],
    asset_ids: tuple[str, ...],
):
    natural = source_lock.source("natural-earth-admin0")
    world_scope = ScopeNode(
        key="world",
        kind=ScopeKind.WORLD,
        label="World",
        short_label="World",
        parent_key=None,
        children_available=True,
        presentation="boundary",
    )
    records: list[ManifestScopeInput] = [
        ManifestScopeInput(
            scope=world_scope,
            path=("world",),
            provenance=_provenance(
                source=natural,
                representation_id="natural-earth-110m-admin0",
                dispute_status="none",
                boundary_policy=catalog_plan.boundary_policy,
            ),
            presentation=ScopePresentation(
                preferred_lod=Lod.OVERVIEW,
                children_lods={Lod.OVERVIEW: _geometry_descriptor(world_pack)},
            ),
            provenance_ref=natural.source_id,
            derivation_inputs=DerivationInputs(
                crosswalk_sha256=crosswalk_source.sha256,
                scope_path=("world",),
            ),
        )
    ]
    admin0_by_scope = {
        feature.record.scope_key: feature
        for feature in admin0
        if feature.record.scope_key is not None
    }
    for scope_key, entry in sorted(active_plan.items()):
        feature = admin0_by_scope[scope_key]
        containment = containment_assets.get(scope_key)
        built = admin1_builds.get(scope_key)
        outline_lods = (
            {Lod.REGIONAL: _geometry_descriptor(built.parent_render)}
            if built is not None
            else {}
        )
        children_lods = (
            {Lod.REGIONAL: _geometry_descriptor(built.child_pack)}
            if built is not None
            else {}
        )
        records.append(
            ManifestScopeInput(
                scope=ScopeNode(
                    key=scope_key,
                    kind=ScopeKind.COUNTRY,
                    label=feature.label,
                    short_label=feature.label,
                    parent_key="world",
                    children_available=built is not None,
                    presentation="boundary",
                ),
                path=("world", scope_key),
                provenance=_provenance(
                    source=natural,
                    representation_id=entry.representation_id,
                    dispute_status=feature.record.dispute_status,
                    boundary_policy=catalog_plan.boundary_policy,
                ),
                presentation=ScopePresentation(
                    preferred_lod=Lod.REGIONAL if built is not None else None,
                    outline_lods=outline_lods,
                    children_lods=children_lods,
                    containment=(
                        _containment_descriptor(containment) if containment is not None else None
                    ),
                ),
                provenance_ref=(
                    f"{natural.source_id}+{built.source.source_id}"
                    if built is not None
                    else natural.source_id
                ),
                derivation_inputs=DerivationInputs(
                    crosswalk_sha256=crosswalk_source.sha256,
                    scope_path=("world", scope_key),
                    assignment_asset_ids=(
                        (containment.asset_id,) if containment is not None else ()
                    ),
                ),
            )
        )
        if built is None:
            continue
        for child in built.full_features:
            child_containment = built.child_containment[child.scope_key]
            records.append(
                ManifestScopeInput(
                    scope=ScopeNode(
                        key=child.scope_key,
                        kind=ScopeKind.ADMIN1,
                        label=child.label,
                        short_label=child.label,
                        parent_key=scope_key,
                        children_available=False,
                        presentation="boundary",
                    ),
                    path=("world", scope_key, child.scope_key),
                    provenance=_provenance(
                        source=built.source,
                        representation_id="geoboundaries-gbopen-ukr-admin1",
                        dispute_status="none",
                        boundary_policy=catalog_plan.boundary_policy,
                    ),
                    presentation=ScopePresentation(
                        containment=_containment_descriptor(child_containment)
                    ),
                    provenance_ref=built.source.source_id,
                    derivation_inputs=DerivationInputs(
                        crosswalk_sha256=crosswalk_source.sha256,
                        scope_path=("world", scope_key, child.scope_key),
                        assignment_asset_ids=(child_containment.asset_id,),
                    ),
                )
            )
    return build_manifest(
        ManifestDraft(
            schema_version=1,
            boundary_policy=catalog_plan.boundary_policy,
            root_scope_key="world",
            scopes=tuple(records),
            assets=asset_ids,
        )
    )


def _provenance(
    *,
    source: LockedSource,
    representation_id: str,
    dispute_status: str,
    boundary_policy: str,
) -> CatalogProvenance:
    return CatalogProvenance(
        boundary_policy=boundary_policy,
        representation_id=representation_id,
        dispute_status=dispute_status,
        source_id=source.source_id,
        source_release=source.release,
        license_id=source.license_id,
        attribution=source.attribution,
    )


def _geometry_descriptor(asset: EmittedAsset) -> GeometryDescriptor:
    if not isinstance(asset.descriptor, GeometryDescriptor):
        raise TypeError("render asset requires GeometryDescriptor")
    return asset.descriptor


def _containment_descriptor(asset: EmittedAsset) -> ContainmentDescriptor:
    if not isinstance(asset.descriptor, ContainmentDescriptor):
        raise TypeError("containment asset requires ContainmentDescriptor")
    return asset.descriptor


def _add_asset(assets: dict[str, EmittedAsset], asset: EmittedAsset) -> None:
    existing = assets.get(asset.asset_id)
    if existing is not None and existing.content != asset.content:
        raise ValueError(f"ASSET_HASH_COLLISION: {asset.asset_id}")
    if existing is None:
        assets[asset.asset_id] = asset


def _raw_geometry_counts(raw: Mapping[str, object]) -> tuple[int, int]:
    geometry_type = raw.get("type")
    coordinates = raw.get("coordinates")
    if not isinstance(coordinates, list):
        raise ValueError("INVALID_RAW_GEOMETRY_COORDINATES")
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("INVALID_RAW_GEOMETRY_TYPE")
    ring_count = 0
    vertex_count_value = 0
    for polygon in polygons:
        if not isinstance(polygon, list):
            raise ValueError("INVALID_RAW_POLYGON")
        for ring in polygon:
            if not isinstance(ring, list):
                raise ValueError("INVALID_RAW_RING")
            ring_count += 1
            vertex_count_value += len(ring)
    return ring_count, vertex_count_value


def _load_drop_policy(path: Path) -> _DropPolicy:
    raw = _json_object(path.read_bytes(), context="normalization-drop-policy")
    if set(raw) != {"schema_version", "source_id", "source_release", "drops"}:
        raise ValueError("INVALID_NORMALIZATION_DROP_POLICY")
    if raw["schema_version"] != 1 or not isinstance(raw["drops"], list):
        raise ValueError("INVALID_NORMALIZATION_DROP_POLICY")
    rules: list[_DropRule] = []
    expected_keys = {
        "source_code",
        "source_label",
        "error_code",
        "action",
        "polygon_index",
        "ring_index",
        "position_index",
        "expected_position",
        "review_note",
    }
    for value in raw["drops"]:
        if not isinstance(value, Mapping) or set(value) != expected_keys:
            raise ValueError("INVALID_NORMALIZATION_DROP_RULE")
        position = value["expected_position"]
        if (
            value["action"] != "drop_position"
            or not isinstance(position, list)
            or len(position) != 2
            or any(
                isinstance(item, bool) or not isinstance(item, (int, float))
                for item in position
            )
        ):
            raise ValueError("INVALID_NORMALIZATION_DROP_RULE")
        try:
            rules.append(
                _DropRule(
                    source_code=str(value["source_code"]),
                    source_label=str(value["source_label"]),
                    error_code=str(value["error_code"]),
                    polygon_index=int(value["polygon_index"]),
                    ring_index=int(value["ring_index"]),
                    position_index=int(value["position_index"]),
                    expected_position=(float(position[0]), float(position[1])),
                    review_note=str(value["review_note"]),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("INVALID_NORMALIZATION_DROP_RULE") from exc
    if len({rule.source_code for rule in rules}) != len(rules):
        raise ValueError("DUPLICATE_NORMALIZATION_DROP_RULE")
    return _DropPolicy(
        source_id=str(raw["source_id"]),
        source_release=str(raw["source_release"]),
        rules=tuple(rules),
    )


def _apply_drop_rule(raw: Mapping[str, object], rule: _DropRule) -> object:
    corrected = copy.deepcopy(raw)
    coordinates = corrected.get("coordinates")
    geometry_type = corrected.get("type")
    try:
        polygons = [coordinates] if geometry_type == "Polygon" else coordinates
        ring = polygons[rule.polygon_index][rule.ring_index]  # type: ignore[index]
        position = ring[rule.position_index]
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError(f"NORMALIZATION_DROP_TARGET_MISMATCH: {rule.source_code}") from exc
    actual = tuple(float(value) for value in position)
    if actual != rule.expected_position:
        raise ValueError(f"NORMALIZATION_DROP_POSITION_MISMATCH: {rule.source_code}")
    del ring[rule.position_index]
    return corrected


def _json_object(payload: bytes, *, context: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"INVALID_JSON: {context}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"INVALID_JSON_OBJECT: {context}")
    return value


def _normalization_audit_bytes(
    catalog_revision: str,
    *,
    source: LockedSource,
    drops: Sequence[_DropAudit],
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "catalog_revision": catalog_revision,
            "status": "pass",
            "source_id": source.source_id,
            "source_release": source.release,
            "drops": [
                {
                    "source_code": drop.source_code,
                    "source_label": drop.source_label,
                    "error_code": drop.error_code,
                    "action": "drop_position",
                    "polygon_index": drop.polygon_index,
                    "ring_index": drop.ring_index,
                    "position_index": drop.position_index,
                    "dropped_position": drop.dropped_position,
                    "review_note": drop.review_note,
                }
                for drop in drops
            ],
        }
    )


def _lod_audit_bytes(
    catalog_revision: str,
    *,
    mapshaper_source: LockedSource,
    world_pack: EmittedAsset,
    world_metrics: LodMetrics,
    admin1_builds: Mapping[str, _Admin1Build],
    world_original_vertices: int,
) -> bytes:
    records = [
        {
            "asset_id": world_pack.asset_id,
            "scope_key": "world",
            "representation": "children-pack",
            "lod": world_metrics.lod,
            "original_vertices": world_original_vertices,
            "output_vertices": world_metrics.vertex_count,
            "max_error_m": world_metrics.max_error_m,
            "protected_feature_count": world_metrics.protected_feature_count,
            "removed_degenerate_ring_count": world_metrics.removed_degenerate_ring_count,
        }
    ]
    for scope_key, built in sorted(admin1_builds.items()):
        original_vertices = sum(
            vertex_count(feature.geometry) for feature in built.full_features
        )
        records.extend(
            (
                {
                    "asset_id": built.child_pack.asset_id,
                    "scope_key": scope_key,
                    "representation": "children-pack",
                    "lod": built.metrics.lod,
                    "original_vertices": original_vertices,
                    "output_vertices": built.metrics.vertex_count,
                    "max_error_m": built.metrics.max_error_m,
                    "protected_feature_count": built.metrics.protected_feature_count,
                    "removed_degenerate_ring_count": (
                        built.metrics.removed_degenerate_ring_count
                    ),
                },
                {
                    "asset_id": built.parent_render.asset_id,
                    "scope_key": scope_key,
                    "representation": "parent-dissolve",
                    "lod": built.metrics.lod,
                    "original_vertices": vertex_count(built.full_parent),
                    "output_vertices": built.parent_render.counts.vertex_count,
                    "max_error_m": built.metrics.max_error_m,
                    "protected_feature_count": built.metrics.protected_feature_count,
                    "removed_degenerate_ring_count": (
                        built.metrics.removed_degenerate_ring_count
                    ),
                },
            )
        )
        for feature in built.full_features:
            asset = built.child_containment[feature.scope_key]
            descriptor = _containment_descriptor(asset)
            records.append(
                {
                    "asset_id": asset.asset_id,
                    "scope_key": feature.scope_key,
                    "representation": "containment",
                    "lod": "containment",
                    "original_vertices": vertex_count(feature.geometry),
                    "output_vertices": asset.counts.vertex_count,
                    "max_error_m": descriptor.max_error_m,
                    "protected_feature_count": sum(
                        len(polygon) for polygon in feature.geometry.polygons
                    ),
                    "removed_degenerate_ring_count": 0,
                }
            )
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "catalog_revision": catalog_revision,
            "status": "pass",
            "topology_tool": {
                "source_id": mapshaper_source.source_id,
                "release": mapshaper_source.release,
                "sha256": mapshaper_source.sha256,
            },
            "records": records,
        }
    )


def _build_provenance_bytes(
    catalog_revision: str,
    *,
    tool: PinnedTopologyTool,
    mapshaper_source: LockedSource,
) -> bytes:
    """Record host toolchain evidence without feeding it into revision identity."""

    return canonical_json_bytes(
        {
            "schema_version": 1,
            "catalog_revision": catalog_revision,
            "revision_forming": False,
            "toolchain": {
                "node": {
                    "engine": tool.runtime_engine,
                    "version": tool.runtime_version,
                },
                "mapshaper": {
                    "release": mapshaper_source.release,
                    "sha256": mapshaper_source.sha256,
                    "version": tool.expected_version,
                },
            },
        }
    )
