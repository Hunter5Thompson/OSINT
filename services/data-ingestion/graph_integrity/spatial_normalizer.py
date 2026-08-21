"""Pure deterministic normalization of source location identities.

The normalizer consumes only an immutable, reviewed index.  File-system loading is
kept in :func:`load_normalization_index`; normalization itself performs no I/O and
never produces Cypher.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    model_validator,
)

from spatial_catalog.identity import (
    CountryCrosswalk,
    load_country_crosswalk,
    parse_scope_key,
)
from spatial_catalog.manifest import (
    CatalogManifest,
    CatalogPointer,
    canonical_json_bytes,
    canonical_manifest_bytes,
)
from spatial_catalog.models import ScopeKind
from spatial_catalog.normalize import BoundaryGeometry, normalize_geometry
from spatial_catalog.topology import contains_point

type SourceCode = Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
type SourceName = Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]

_BOUNDARY_EPSILON_M = 0.1
_EARTH_RADIUS_M = 6_371_008.8


class CountryCodeSystem(StrEnum):
    ISO2 = "iso2"
    ISO3 = "iso3"
    UN_M49 = "un-m49"
    GDELT_GEC = "gdelt-gec"
    NATURAL_EARTH_M49 = "natural-earth-m49"
    ODIN_SCOPE_KEY = "odin-scope-key"


class AdministrativeCodeSystem(StrEnum):
    ISO_3166_2 = "iso-3166-2"
    GEOBOUNDARIES = "geoboundaries"
    GDELT_ADM1 = "gdelt-adm1"
    ODIN_SCOPE_KEY = "odin-scope-key"


class SpatialBasis(StrEnum):
    SOURCE = "source"
    CROSSWALK = "crosswalk"
    COORDINATE = "coordinate"
    MANUAL = "manual"


class SpatialPrecision(StrEnum):
    COUNTRY = "country"
    ADMIN1 = "admin1"
    ADMIN2 = "admin2"
    POINT = "point"


class RawLocationIdentity(BaseModel):
    """Strict source identity.  Optional values must be supplied in pairs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    country_code: SourceCode | None = None
    country_code_system: CountryCodeSystem | None = None
    source_country_name: SourceName | None = None
    admin1_code: SourceCode | None = None
    admin1_code_system: AdministrativeCodeSystem | None = None
    admin2_code: SourceCode | None = None
    admin2_code_system: AdministrativeCodeSystem | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_pairs(self) -> RawLocationIdentity:
        _require_pair(
            self.country_code,
            self.country_code_system,
            "country code and system",
        )
        _require_pair(self.admin1_code, self.admin1_code_system, "admin1 code and system")
        _require_pair(self.admin2_code, self.admin2_code_system, "admin2 code and system")
        _require_pair(self.latitude, self.longitude, "latitude and longitude")
        return self


class SpatialNormalizationResult(BaseModel):
    """Materializable fields plus explicit normalization accounting."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    raw: RawLocationIdentity
    status: Literal["resolved", "unresolved", "conflict"]
    source_country_code: str | None
    source_country_code_system: CountryCodeSystem | None
    country_iso3: str | None
    admin1_code: str | None
    admin2_code: str | None
    country_scope_key: str | None
    admin1_scope_key: str | None
    admin2_scope_key: str | None
    latitude: float | None
    longitude: float | None
    spatial_basis: SpatialBasis | None
    spatial_precision: SpatialPrecision | None
    spatial_catalog_revision: str
    spatial_derivation_revision: str | None
    spatial_conflict: bool
    spatial_conflict_scope_keys: tuple[str, ...] = ()
    unresolved_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _ScopeRecord:
    key: str
    kind: ScopeKind
    parent_key: str | None
    derivation_revision: str
    compatible_derivation_revisions: tuple[str, ...]
    containment: BoundaryGeometry | None


@dataclass(frozen=True, slots=True)
class _ResolvedCode:
    scope_key: str
    basis: SpatialBasis


@dataclass(frozen=True, slots=True)
class _CoordinateResolution:
    scope_key: str | None
    conflict_scope_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpatialNormalizationIndex:
    """Immutable code and containment indexes used by the pure normalizer."""

    catalog_revision: str
    scopes: Mapping[str, _ScopeRecord]
    country_iso3_by_scope: Mapping[str, str | None]
    country_code_indexes: Mapping[CountryCodeSystem, Mapping[str, str]]
    admin1_code_indexes: Mapping[AdministrativeCodeSystem, Mapping[str, str]]
    admin2_code_indexes: Mapping[AdministrativeCodeSystem, Mapping[str, str]]

    def lineage(self, scope_key: str) -> tuple[str, ...]:
        lineage: list[str] = []
        current: str | None = scope_key
        visited: set[str] = set()
        while current is not None:
            if current in visited:
                raise ValueError(f"scope lineage cycle: {current}")
            visited.add(current)
            record = self.scopes.get(current)
            if record is None:
                raise ValueError(f"unknown scope in lineage: {current}")
            lineage.append(current)
            current = record.parent_key
        lineage.reverse()
        return tuple(lineage)

    def country_scope(self, scope_key: str) -> str | None:
        return next(
            (key for key in self.lineage(scope_key) if self.scopes[key].kind is ScopeKind.COUNTRY),
            None,
        )

    def is_compatible_derivation(self, scope_key: str, revision: str) -> bool:
        record = self.scopes.get(scope_key)
        return (
            record is not None
            and revision in record.compatible_derivation_revisions
        )


def _require_pair(left: object, right: object, label: str) -> None:
    if (left is None) != (right is None):
        raise ValueError(f"{label} must be provided together")


def build_normalization_index(
    *,
    catalog_revision: str,
    country_crosswalk: CountryCrosswalk,
    scope_parents: Mapping[str, str | None],
    scope_derivation_revisions: Mapping[str, str],
    scope_compatible_derivation_revisions: Mapping[str, tuple[str, ...]] | None = None,
    containment: Mapping[str, BoundaryGeometry],
) -> SpatialNormalizationIndex:
    """Build immutable allowlisted indexes from reviewed catalog inputs."""

    if set(scope_parents) != set(scope_derivation_revisions):
        raise ValueError("scope parents and derivation revisions must cover the same scopes")
    if not set(containment).issubset(scope_parents):
        raise ValueError("containment references an unknown scope")
    compatible_by_scope = scope_compatible_derivation_revisions or {
        scope_key: (revision,)
        for scope_key, revision in scope_derivation_revisions.items()
    }
    if set(compatible_by_scope) != set(scope_parents):
        raise ValueError("compatible revisions must cover the same scopes")

    records: dict[str, _ScopeRecord] = {}
    for scope_key, parent_key in scope_parents.items():
        parsed = parse_scope_key(scope_key)
        if parent_key is not None and parent_key not in scope_parents:
            raise ValueError(f"unknown parent scope: {parent_key}")
        compatible_revisions = compatible_by_scope[scope_key]
        if (
            not compatible_revisions
            or len(set(compatible_revisions)) != len(compatible_revisions)
            or scope_derivation_revisions[scope_key] not in compatible_revisions
        ):
            raise ValueError(f"invalid compatible revisions for scope: {scope_key}")
        records[scope_key] = _ScopeRecord(
            key=scope_key,
            kind=parsed.kind,
            parent_key=parent_key,
            derivation_revision=scope_derivation_revisions[scope_key],
            compatible_derivation_revisions=compatible_revisions,
            containment=containment.get(scope_key),
        )

    country_iso3_by_scope: dict[str, str | None] = {}
    country_indexes: dict[CountryCodeSystem, dict[str, str]] = {
        system: {} for system in CountryCodeSystem
    }
    for record in country_crosswalk.records:
        if record.scope_key is None or record.scope_key not in records:
            continue
        country_iso3_by_scope[record.scope_key] = record.canonical_iso3
        country_indexes[CountryCodeSystem.ODIN_SCOPE_KEY][record.scope_key] = record.scope_key
        if record.canonical_iso3 is not None:
            country_indexes[CountryCodeSystem.ISO3][record.canonical_iso3] = record.scope_key
        if record.canonical_m49 is not None:
            country_indexes[CountryCodeSystem.UN_M49][record.canonical_m49] = record.scope_key
        country_indexes[CountryCodeSystem.NATURAL_EARTH_M49][record.source_code] = record.scope_key
        for alias in record.aliases:
            if alias.source_system == "gdelt-fips" and alias.code_system == "fips-10-4":
                country_indexes[CountryCodeSystem.GDELT_GEC][alias.code] = record.scope_key

    # ISO-2 is a code-system adapter only.  Its target still has to exist in the
    # reviewed country crosswalk before a scope can be produced.
    for iso2, iso3 in _ISO2_TO_ISO3.items():
        scope_key = country_indexes[CountryCodeSystem.ISO3].get(iso3)
        if scope_key is not None:
            country_indexes[CountryCodeSystem.ISO2][iso2] = scope_key

    admin1_indexes: dict[AdministrativeCodeSystem, dict[str, str]] = {
        system: {} for system in AdministrativeCodeSystem
    }
    admin2_indexes: dict[AdministrativeCodeSystem, dict[str, str]] = {
        system: {} for system in AdministrativeCodeSystem
    }
    for scope_key, record in records.items():
        parsed = parse_scope_key(scope_key)
        if record.kind is ScopeKind.ADMIN1:
            admin1_indexes[AdministrativeCodeSystem.ODIN_SCOPE_KEY][scope_key] = scope_key
            if parsed.namespace == "iso3166-2" and parsed.canonical_code is not None:
                admin1_indexes[AdministrativeCodeSystem.ISO_3166_2][parsed.canonical_code] = (
                    scope_key
                )
            if parsed.namespace == "gbopen" and parsed.canonical_code is not None:
                admin1_indexes[AdministrativeCodeSystem.GEOBOUNDARIES][parsed.canonical_code] = (
                    scope_key
                )
        elif record.kind is ScopeKind.ADMIN2:
            admin2_indexes[AdministrativeCodeSystem.ODIN_SCOPE_KEY][scope_key] = scope_key
            if parsed.canonical_code is not None:
                admin2_indexes[AdministrativeCodeSystem.GEOBOUNDARIES][parsed.canonical_code] = (
                    scope_key
                )

    index = SpatialNormalizationIndex(
        catalog_revision=catalog_revision,
        scopes=MappingProxyType(records),
        country_iso3_by_scope=MappingProxyType(country_iso3_by_scope),
        country_code_indexes=_freeze_nested(country_indexes),
        admin1_code_indexes=_freeze_nested(admin1_indexes),
        admin2_code_indexes=_freeze_nested(admin2_indexes),
    )
    for scope_key in records:
        index.lineage(scope_key)
    return index


def load_normalization_index(
    catalog_directory: Path,
    *,
    crosswalk_path: Path,
) -> SpatialNormalizationIndex:
    """Load and verify one immutable published catalog revision."""

    if catalog_directory.is_symlink() or not catalog_directory.is_dir():
        raise ValueError("catalog directory must be a regular directory")
    manifest_path = catalog_directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("catalog manifest must be a regular file")
    manifest_bytes = manifest_path.read_bytes()
    manifest = CatalogManifest.model_validate_json(manifest_bytes)
    if canonical_manifest_bytes(manifest) != manifest_bytes:
        raise ValueError("catalog manifest is not canonical JSON")
    if manifest.catalog_revision != catalog_directory.name:
        raise ValueError("catalog directory and manifest revision differ")

    crosswalk_bytes = crosswalk_path.read_bytes()
    crosswalk_hash = hashlib.sha256(crosswalk_bytes).hexdigest()
    declared_hashes = {scope.derivation_inputs.crosswalk_sha256 for scope in manifest.scopes}
    if declared_hashes != {crosswalk_hash}:
        raise ValueError("catalog and country crosswalk hashes differ")
    country_crosswalk = load_country_crosswalk(crosswalk_path)

    assets_directory = catalog_directory / "assets"
    containment: dict[str, BoundaryGeometry] = {}
    for scope in manifest.scopes:
        descriptor = scope.presentation.containment
        if descriptor is None:
            continue
        if descriptor.max_error_m != 0:
            raise ValueError("assignment containment must have zero representation error")
        asset_path = assets_directory / f"{descriptor.asset_id}.json"
        if asset_path.is_symlink() or not asset_path.is_file():
            raise ValueError("containment asset must be a regular file")
        asset_bytes = asset_path.read_bytes()
        if len(asset_bytes) != descriptor.byte_length:
            raise ValueError("containment asset byte length differs from descriptor")
        if hashlib.sha256(asset_bytes).hexdigest() != descriptor.asset_id:
            raise ValueError("containment asset hash differs from descriptor")
        payload = json.loads(asset_bytes)
        if set(payload) != {"schema_version", "geometry_type", "polygons"}:
            raise ValueError("containment asset has an invalid wire shape")
        if payload["schema_version"] != 1 or payload["geometry_type"] != "MultiPolygon":
            raise ValueError("containment asset has an unsupported schema")
        geometry = normalize_geometry({"type": "MultiPolygon", "coordinates": payload["polygons"]})
        if geometry.to_wire() != payload:
            raise ValueError("containment asset is not in canonical normal form")
        containment[scope.scope.key] = geometry

    return build_normalization_index(
        catalog_revision=manifest.catalog_revision,
        country_crosswalk=country_crosswalk,
        scope_parents={scope.scope.key: scope.scope.parent_key for scope in manifest.scopes},
        scope_derivation_revisions={
            scope.scope.key: scope.derivation_revision for scope in manifest.scopes
        },
        scope_compatible_derivation_revisions={
            scope.scope.key: scope.compatible_derivation_revisions
            for scope in manifest.scopes
        },
        containment=containment,
    )


@lru_cache(maxsize=4)
def load_active_normalization_index(
    catalog_root: Path,
    *,
    crosswalk_path: Path,
) -> SpatialNormalizationIndex:
    """Resolve exactly the deployment-owned active immutable catalog."""

    if (catalog_root / "manifest.json").is_file():
        return load_normalization_index(
            catalog_root,
            crosswalk_path=crosswalk_path,
        )
    catalogs_root = catalog_root / "catalogs"
    if catalogs_root.is_symlink() or not catalogs_root.is_dir():
        raise FileNotFoundError("spatial catalog root is missing")
    pointer_path = catalog_root / "catalog-pointer.json"
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise FileNotFoundError("spatial catalog pointer is missing")
    pointer_bytes = pointer_path.read_bytes()
    pointer = CatalogPointer.model_validate_json(pointer_bytes)
    canonical_pointer = canonical_json_bytes(pointer)
    if pointer_bytes not in {canonical_pointer, canonical_pointer + b"\n"}:
        raise ValueError("spatial catalog pointer is not canonical JSON")
    served: list[Path] = []
    for revision in pointer.served_catalog_revisions:
        directory = catalogs_root / revision
        manifest_path = directory / "manifest.json"
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
        ):
            raise FileNotFoundError("served spatial catalog revision is missing")
        served.append(directory)
    active = served[0]
    return load_normalization_index(active, crosswalk_path=crosswalk_path)


def normalize_location(
    raw: RawLocationIdentity,
    index: SpatialNormalizationIndex,
) -> SpatialNormalizationResult:
    """Normalize one source identity without I/O, mutation, or query generation."""

    resolved_codes: list[_ResolvedCode] = []
    unresolved_codes: list[str] = []
    _resolve_country_code(
        raw.country_code,
        raw.country_code_system,
        index,
        resolved_codes,
        unresolved_codes,
    )
    _resolve_admin1_code(
        raw.admin1_code,
        raw.admin1_code_system,
        index,
        resolved_codes,
        unresolved_codes,
    )
    _resolve_admin2_code(
        raw.admin2_code,
        raw.admin2_code_system,
        index,
        resolved_codes,
        unresolved_codes,
    )

    has_point = raw.latitude is not None and raw.longitude is not None
    if unresolved_codes:
        return _result(
            raw,
            index,
            scope_key=None,
            basis=SpatialBasis.COORDINATE if has_point else None,
            conflict_scope_keys=(),
            unresolved_codes=tuple(unresolved_codes),
        )

    explicit_scope, explicit_basis, source_conflicts = _choose_explicit_scope(
        resolved_codes,
        index,
    )
    coordinate = (
        _resolve_coordinate(raw.longitude, raw.latitude, index)
        if has_point
        else _CoordinateResolution(None, ())
    )

    selected_scope = explicit_scope
    selected_basis = explicit_basis
    conflicts = set(source_conflicts)
    conflicts.update(coordinate.conflict_scope_keys)

    if coordinate.scope_key is not None:
        if selected_scope is None:
            selected_scope = coordinate.scope_key
            selected_basis = SpatialBasis.COORDINATE
        elif _scopes_compatible(selected_scope, coordinate.scope_key, index):
            if len(index.lineage(coordinate.scope_key)) > len(index.lineage(selected_scope)):
                selected_scope = coordinate.scope_key
                selected_basis = SpatialBasis.COORDINATE
        else:
            conflicts.update((selected_scope, coordinate.scope_key))

    return _result(
        raw,
        index,
        scope_key=selected_scope,
        basis=selected_basis,
        conflict_scope_keys=tuple(sorted(conflicts)),
        unresolved_codes=(),
    )


def spatial_property_parameters(
    result: SpatialNormalizationResult,
) -> dict[str, object]:
    """Project one result onto the fixed additive ``:Location`` property set."""

    return {
        "source_country_code": result.source_country_code,
        "source_country_code_system": (
            result.source_country_code_system.value
            if result.source_country_code_system is not None
            else None
        ),
        "country_iso3": result.country_iso3,
        "admin1_code": result.admin1_code,
        "admin2_code": result.admin2_code,
        "country_scope_key": result.country_scope_key,
        "admin1_scope_key": result.admin1_scope_key,
        "admin2_scope_key": result.admin2_scope_key,
        "spatial_basis": (
            result.spatial_basis.value if result.spatial_basis is not None else None
        ),
        "spatial_precision": (
            result.spatial_precision.value
            if result.spatial_precision is not None
            else None
        ),
        "spatial_catalog_revision": result.spatial_catalog_revision,
        "spatial_derivation_revision": result.spatial_derivation_revision,
        "spatial_conflict": result.spatial_conflict,
        "spatial_conflict_scope_keys": list(result.spatial_conflict_scope_keys),
    }


def _resolve_country_code(
    code: str | None,
    system: CountryCodeSystem | None,
    index: SpatialNormalizationIndex,
    resolved: list[_ResolvedCode],
    unresolved: list[str],
) -> None:
    if code is None or system is None:
        return
    if system is CountryCodeSystem.ISO2:
        mapping = index.country_code_indexes[CountryCodeSystem.ISO2]
        basis = SpatialBasis.CROSSWALK
    elif system is CountryCodeSystem.ISO3:
        mapping = index.country_code_indexes[CountryCodeSystem.ISO3]
        basis = SpatialBasis.SOURCE
    elif system is CountryCodeSystem.UN_M49:
        mapping = index.country_code_indexes[CountryCodeSystem.UN_M49]
        basis = SpatialBasis.CROSSWALK
    elif system is CountryCodeSystem.GDELT_GEC:
        mapping = index.country_code_indexes[CountryCodeSystem.GDELT_GEC]
        basis = SpatialBasis.CROSSWALK
    elif system is CountryCodeSystem.NATURAL_EARTH_M49:
        mapping = index.country_code_indexes[CountryCodeSystem.NATURAL_EARTH_M49]
        basis = SpatialBasis.CROSSWALK
    elif system is CountryCodeSystem.ODIN_SCOPE_KEY:
        mapping = index.country_code_indexes[CountryCodeSystem.ODIN_SCOPE_KEY]
        basis = SpatialBasis.SOURCE
    else:  # pragma: no cover - closed StrEnum plus strict Pydantic model
        raise ValueError(f"unsupported country code system: {system}")
    _append_code_resolution(code, system, mapping, basis, resolved, unresolved)


def _resolve_admin1_code(
    code: str | None,
    system: AdministrativeCodeSystem | None,
    index: SpatialNormalizationIndex,
    resolved: list[_ResolvedCode],
    unresolved: list[str],
) -> None:
    if code is None or system is None:
        return
    if system is AdministrativeCodeSystem.ISO_3166_2:
        mapping = index.admin1_code_indexes[AdministrativeCodeSystem.ISO_3166_2]
        basis = SpatialBasis.SOURCE
    elif system is AdministrativeCodeSystem.GEOBOUNDARIES:
        mapping = index.admin1_code_indexes[AdministrativeCodeSystem.GEOBOUNDARIES]
        basis = SpatialBasis.CROSSWALK
    elif system is AdministrativeCodeSystem.GDELT_ADM1:
        mapping = index.admin1_code_indexes[AdministrativeCodeSystem.GDELT_ADM1]
        basis = SpatialBasis.CROSSWALK
    elif system is AdministrativeCodeSystem.ODIN_SCOPE_KEY:
        mapping = index.admin1_code_indexes[AdministrativeCodeSystem.ODIN_SCOPE_KEY]
        basis = SpatialBasis.SOURCE
    else:  # pragma: no cover - closed StrEnum plus strict Pydantic model
        raise ValueError(f"unsupported admin1 code system: {system}")
    _append_code_resolution(code, system, mapping, basis, resolved, unresolved)


def _resolve_admin2_code(
    code: str | None,
    system: AdministrativeCodeSystem | None,
    index: SpatialNormalizationIndex,
    resolved: list[_ResolvedCode],
    unresolved: list[str],
) -> None:
    if code is None or system is None:
        return
    if system is AdministrativeCodeSystem.GEOBOUNDARIES:
        mapping = index.admin2_code_indexes[AdministrativeCodeSystem.GEOBOUNDARIES]
        basis = SpatialBasis.CROSSWALK
    elif system is AdministrativeCodeSystem.ODIN_SCOPE_KEY:
        mapping = index.admin2_code_indexes[AdministrativeCodeSystem.ODIN_SCOPE_KEY]
        basis = SpatialBasis.SOURCE
    elif system in {
        AdministrativeCodeSystem.ISO_3166_2,
        AdministrativeCodeSystem.GDELT_ADM1,
    }:
        mapping = index.admin2_code_indexes[system]
        basis = SpatialBasis.CROSSWALK
    else:  # pragma: no cover - closed StrEnum plus strict Pydantic model
        raise ValueError(f"unsupported admin2 code system: {system}")
    _append_code_resolution(code, system, mapping, basis, resolved, unresolved)


def _append_code_resolution(
    code: str,
    system: StrEnum,
    mapping: Mapping[str, str],
    basis: SpatialBasis,
    resolved: list[_ResolvedCode],
    unresolved: list[str],
) -> None:
    scope_key = mapping.get(code)
    if scope_key is None:
        unresolved.append(f"{system.value}:{code}")
        return
    resolved.append(_ResolvedCode(scope_key, basis))


def _choose_explicit_scope(
    resolved: list[_ResolvedCode],
    index: SpatialNormalizationIndex,
) -> tuple[str | None, SpatialBasis | None, tuple[str, ...]]:
    if not resolved:
        return None, None, ()
    ordered = sorted(
        resolved,
        key=lambda item: (len(index.lineage(item.scope_key)), item.scope_key),
        reverse=True,
    )
    selected = ordered[0]
    conflicts = {
        item.scope_key
        for item in ordered[1:]
        if not _scopes_compatible(selected.scope_key, item.scope_key, index)
    }
    if conflicts:
        conflicts.add(selected.scope_key)
    return selected.scope_key, selected.basis, tuple(sorted(conflicts))


def _resolve_coordinate(
    longitude: float | None,
    latitude: float | None,
    index: SpatialNormalizationIndex,
) -> _CoordinateResolution:
    if longitude is None or latitude is None:
        return _CoordinateResolution(None, ())
    matches: dict[str, bool] = {}
    for scope_key, record in index.scopes.items():
        geometry = record.containment
        if geometry is None:
            continue
        on_boundary = _on_boundary(
            geometry,
            longitude=longitude,
            latitude=latitude,
        )
        if not on_boundary and not contains_point(
            geometry,
            longitude=longitude,
            latitude=latitude,
        ):
            continue
        matches[scope_key] = on_boundary
    if not matches:
        return _CoordinateResolution(None, ())

    terminal = tuple(
        sorted(
            scope_key
            for scope_key in matches
            if not any(
                scope_key in index.lineage(other)[:-1] for other in matches if other != scope_key
            )
        )
    )
    if len(terminal) == 1:
        only = terminal[0]
        if not matches[only]:
            return _CoordinateResolution(only, ())
        parent = index.scopes[only].parent_key
        if parent is not None and index.scopes[parent].kind is ScopeKind.WORLD:
            parent = None
        return _CoordinateResolution(parent, terminal)

    common = _deepest_common_scope(terminal, index)
    return _CoordinateResolution(common, terminal)


def _deepest_common_scope(
    scope_keys: tuple[str, ...],
    index: SpatialNormalizationIndex,
) -> str | None:
    if not scope_keys:
        return None
    lineages = tuple(index.lineage(scope_key) for scope_key in scope_keys)
    common: str | None = None
    for candidates in zip(*lineages, strict=False):
        if len(set(candidates)) != 1:
            break
        common = candidates[0]
    if common is not None and index.scopes[common].kind is ScopeKind.WORLD:
        return None
    return common


def _scopes_compatible(
    left: str,
    right: str,
    index: SpatialNormalizationIndex,
) -> bool:
    return left in index.lineage(right) or right in index.lineage(left)


def _result(
    raw: RawLocationIdentity,
    index: SpatialNormalizationIndex,
    *,
    scope_key: str | None,
    basis: SpatialBasis | None,
    conflict_scope_keys: tuple[str, ...],
    unresolved_codes: tuple[str, ...],
) -> SpatialNormalizationResult:
    lineage = index.lineage(scope_key) if scope_key is not None else ()
    country_scope_key = _scope_of_kind(lineage, index, ScopeKind.COUNTRY)
    admin1_scope_key = _scope_of_kind(lineage, index, ScopeKind.ADMIN1)
    admin2_scope_key = _scope_of_kind(lineage, index, ScopeKind.ADMIN2)
    has_point = raw.latitude is not None and raw.longitude is not None
    precision = _precision(
        has_point=has_point,
        country_scope_key=country_scope_key,
        admin1_scope_key=admin1_scope_key,
        admin2_scope_key=admin2_scope_key,
    )
    conflict = bool(conflict_scope_keys)
    status: Literal["resolved", "unresolved", "conflict"]
    if conflict:
        status = "conflict"
    elif scope_key is None:
        status = "unresolved"
    else:
        status = "resolved"
    return SpatialNormalizationResult(
        raw=raw,
        status=status,
        source_country_code=raw.country_code,
        source_country_code_system=raw.country_code_system,
        country_iso3=(
            index.country_iso3_by_scope.get(country_scope_key)
            if country_scope_key is not None
            else None
        ),
        admin1_code=_canonical_code(admin1_scope_key),
        admin2_code=_canonical_code(admin2_scope_key),
        country_scope_key=country_scope_key,
        admin1_scope_key=admin1_scope_key,
        admin2_scope_key=admin2_scope_key,
        latitude=raw.latitude,
        longitude=raw.longitude,
        spatial_basis=basis,
        spatial_precision=precision,
        spatial_catalog_revision=index.catalog_revision,
        spatial_derivation_revision=(
            index.scopes[scope_key].derivation_revision
            if scope_key is not None and not conflict
            else None
        ),
        spatial_conflict=conflict,
        spatial_conflict_scope_keys=conflict_scope_keys,
        unresolved_codes=unresolved_codes,
    )


def _scope_of_kind(
    lineage: tuple[str, ...],
    index: SpatialNormalizationIndex,
    kind: ScopeKind,
) -> str | None:
    return next((scope for scope in lineage if index.scopes[scope].kind is kind), None)


def _canonical_code(scope_key: str | None) -> str | None:
    if scope_key is None:
        return None
    return parse_scope_key(scope_key).canonical_code


def _precision(
    *,
    has_point: bool,
    country_scope_key: str | None,
    admin1_scope_key: str | None,
    admin2_scope_key: str | None,
) -> SpatialPrecision | None:
    if has_point:
        return SpatialPrecision.POINT
    if admin2_scope_key is not None:
        return SpatialPrecision.ADMIN2
    if admin1_scope_key is not None:
        return SpatialPrecision.ADMIN1
    if country_scope_key is not None:
        return SpatialPrecision.COUNTRY
    return None


def _on_boundary(
    geometry: BoundaryGeometry,
    *,
    longitude: float,
    latitude: float,
) -> bool:
    return any(
        _point_segment_distance_m(
            longitude,
            latitude,
            left[0],
            left[1],
            right[0],
            right[1],
        )
        <= _BOUNDARY_EPSILON_M
        for polygon in geometry.polygons
        for ring in polygon
        for left, right in zip(ring, ring[1:], strict=False)
    )


def _point_segment_distance_m(
    point_lon: float,
    point_lat: float,
    left_lon: float,
    left_lat: float,
    right_lon: float,
    right_lat: float,
) -> float:
    """Local geodesic projection used only for the sub-metre boundary epsilon."""

    latitude_radians = math.radians(point_lat)

    def projected(longitude: float, latitude: float) -> tuple[float, float]:
        delta_lon = (longitude - point_lon + 180.0) % 360.0 - 180.0
        return (
            math.radians(delta_lon) * _EARTH_RADIUS_M * math.cos(latitude_radians),
            math.radians(latitude - point_lat) * _EARTH_RADIUS_M,
        )

    left_x, left_y = projected(left_lon, left_lat)
    right_x, right_y = projected(right_lon, right_lat)
    delta_x = right_x - left_x
    delta_y = right_y - left_y
    squared_length = delta_x * delta_x + delta_y * delta_y
    if squared_length == 0:
        return math.hypot(left_x, left_y)
    fraction = max(
        0.0,
        min(1.0, -(left_x * delta_x + left_y * delta_y) / squared_length),
    )
    return math.hypot(left_x + fraction * delta_x, left_y + fraction * delta_y)


def _freeze_nested(
    value: Mapping[StrEnum, Mapping[str, str]],
) -> Mapping[StrEnum, Mapping[str, str]]:
    return MappingProxyType(
        {key: MappingProxyType(dict(entries)) for key, entries in value.items()}
    )


# Closed ISO-3166-1 alpha-2/alpha-3 adapter for the official identities present
# in the locked V1 country crosswalk.  Values are never scope keys: the builder
# still requires the target ISO3 to resolve through that reviewed crosswalk.
_ISO2_TO_ISO3: Mapping[str, str] = MappingProxyType(
    {
        "AE": "ARE",
        "AF": "AFG",
        "AL": "ALB",
        "AM": "ARM",
        "AO": "AGO",
        "AQ": "ATA",
        "AR": "ARG",
        "AT": "AUT",
        "AU": "AUS",
        "AZ": "AZE",
        "BA": "BIH",
        "BD": "BGD",
        "BE": "BEL",
        "BF": "BFA",
        "BG": "BGR",
        "BI": "BDI",
        "BJ": "BEN",
        "BN": "BRN",
        "BO": "BOL",
        "BR": "BRA",
        "BS": "BHS",
        "BT": "BTN",
        "BW": "BWA",
        "BY": "BLR",
        "BZ": "BLZ",
        "CA": "CAN",
        "CD": "COD",
        "CF": "CAF",
        "CG": "COG",
        "CH": "CHE",
        "CI": "CIV",
        "CL": "CHL",
        "CM": "CMR",
        "CN": "CHN",
        "CO": "COL",
        "CR": "CRI",
        "CU": "CUB",
        "CY": "CYP",
        "CZ": "CZE",
        "DE": "DEU",
        "DJ": "DJI",
        "DK": "DNK",
        "DO": "DOM",
        "DZ": "DZA",
        "EC": "ECU",
        "EE": "EST",
        "EG": "EGY",
        "EH": "ESH",
        "ER": "ERI",
        "ES": "ESP",
        "ET": "ETH",
        "FI": "FIN",
        "FJ": "FJI",
        "FK": "FLK",
        "FR": "FRA",
        "GA": "GAB",
        "GB": "GBR",
        "GE": "GEO",
        "GH": "GHA",
        "GL": "GRL",
        "GM": "GMB",
        "GN": "GIN",
        "GQ": "GNQ",
        "GR": "GRC",
        "GT": "GTM",
        "GW": "GNB",
        "GY": "GUY",
        "HN": "HND",
        "HR": "HRV",
        "HT": "HTI",
        "HU": "HUN",
        "ID": "IDN",
        "IE": "IRL",
        "IL": "ISR",
        "IN": "IND",
        "IQ": "IRQ",
        "IR": "IRN",
        "IS": "ISL",
        "IT": "ITA",
        "JM": "JAM",
        "JO": "JOR",
        "JP": "JPN",
        "KE": "KEN",
        "KG": "KGZ",
        "KH": "KHM",
        "KP": "PRK",
        "KR": "KOR",
        "KW": "KWT",
        "KZ": "KAZ",
        "LA": "LAO",
        "LB": "LBN",
        "LK": "LKA",
        "LR": "LBR",
        "LS": "LSO",
        "LT": "LTU",
        "LU": "LUX",
        "LV": "LVA",
        "LY": "LBY",
        "MA": "MAR",
        "MD": "MDA",
        "ME": "MNE",
        "MG": "MDG",
        "MK": "MKD",
        "ML": "MLI",
        "MM": "MMR",
        "MN": "MNG",
        "MR": "MRT",
        "MW": "MWI",
        "MX": "MEX",
        "MY": "MYS",
        "MZ": "MOZ",
        "NA": "NAM",
        "NC": "NCL",
        "NE": "NER",
        "NG": "NGA",
        "NI": "NIC",
        "NL": "NLD",
        "NO": "NOR",
        "NP": "NPL",
        "NZ": "NZL",
        "OM": "OMN",
        "PA": "PAN",
        "PE": "PER",
        "PG": "PNG",
        "PH": "PHL",
        "PK": "PAK",
        "PL": "POL",
        "PR": "PRI",
        "PS": "PSE",
        "PT": "PRT",
        "PY": "PRY",
        "QA": "QAT",
        "RO": "ROU",
        "RS": "SRB",
        "RU": "RUS",
        "RW": "RWA",
        "SA": "SAU",
        "SB": "SLB",
        "SD": "SDN",
        "SE": "SWE",
        "SI": "SVN",
        "SK": "SVK",
        "SL": "SLE",
        "SN": "SEN",
        "SO": "SOM",
        "SR": "SUR",
        "SS": "SSD",
        "SV": "SLV",
        "SY": "SYR",
        "SZ": "SWZ",
        "TD": "TCD",
        "TF": "ATF",
        "TG": "TGO",
        "TH": "THA",
        "TJ": "TJK",
        "TL": "TLS",
        "TM": "TKM",
        "TN": "TUN",
        "TR": "TUR",
        "TT": "TTO",
        "TW": "TWN",
        "TZ": "TZA",
        "UA": "UKR",
        "UG": "UGA",
        "US": "USA",
        "UY": "URY",
        "UZ": "UZB",
        "VE": "VEN",
        "VN": "VNM",
        "VU": "VUT",
        "YE": "YEM",
        "ZA": "ZAF",
        "ZM": "ZMB",
        "ZW": "ZWE",
    }
)
