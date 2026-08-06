"""Strict runtime and HTTP contracts for the reviewed spatial catalog."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

type ScopeKey = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:._-]+$"),
]
type CatalogRevision = Annotated[
    StrictStr,
    StringConstraints(
        min_length=23,
        max_length=79,
        pattern=r"^spatial-v[0-9]+-[a-f0-9]{12,64}$",
    ),
]
type DerivationRevision = Annotated[
    StrictStr,
    StringConstraints(
        min_length=30,
        max_length=96,
        pattern=r"^spatial-derive-v[0-9]+-[a-f0-9]{12,64}$",
    ),
]
type AssetId = Annotated[
    StrictStr,
    StringConstraints(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"),
]
type Label = Annotated[StrictStr, StringConstraints(min_length=1, max_length=120)]
type PolicyIdentifier = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9._-]+$"),
]


class StrictFrozenModel(BaseModel):
    """Reject unknown or coercible data at every local catalog trust boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ScopeKind(StrEnum):
    WORLD = "world"
    COUNTRY = "country"
    ADMIN1 = "admin1"
    ADMIN2 = "admin2"


class SpatialScopeTokenV1(StrictFrozenModel):
    """Backend-owned scope identity resolved from one immutable catalog revision."""

    schema_version: Literal[1] = 1
    scope_key: ScopeKey
    kind: ScopeKind
    catalog_revision: CatalogRevision
    derivation_revision: DerivationRevision
    boundary_policy: PolicyIdentifier
    compatible_derivation_revisions: tuple[DerivationRevision, ...] = Field(
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_identity_and_compatibility(self) -> SpatialScopeTokenV1:
        if parse_scope_key(self.scope_key).kind is not self.kind:
            raise ValueError("scope key kind does not match token kind")
        if self.derivation_revision not in self.compatible_derivation_revisions:
            raise ValueError("derivation_revision must be compatible")
        if len(set(self.compatible_derivation_revisions)) != len(
            self.compatible_derivation_revisions
        ):
            raise ValueError("compatible derivation revisions must be unique")
        return self


class Lod(StrEnum):
    OVERVIEW = "overview"
    REGIONAL = "regional"
    LOCAL = "local"


class CatalogProblemCode(StrEnum):
    CATALOG_UNAVAILABLE = "CATALOG_UNAVAILABLE"
    CATALOG_REVISION_UNAVAILABLE = "CATALOG_REVISION_UNAVAILABLE"
    INVALID_CATALOG_REVISION = "INVALID_CATALOG_REVISION"
    INVALID_SCOPE_KEY = "INVALID_SCOPE_KEY"
    INVALID_ASSET_ID = "INVALID_ASSET_ID"
    UNKNOWN_SCOPE = "UNKNOWN_SCOPE"
    UNKNOWN_ASSET = "UNKNOWN_ASSET"
    ASSET_BUSY = "ASSET_BUSY"
    ASSET_CORRUPT = "ASSET_CORRUPT"


class SpatialCatalogProblem(StrictFrozenModel):
    """Transport-independent problem produced by the catalog service."""

    code: CatalogProblemCode
    message: StrictStr = Field(min_length=1, max_length=200)
    target: StrictStr | None = Field(default=None, max_length=128)
    recoverable: bool
    active_catalog_revision: CatalogRevision | None = None


class ScopeProblemDetail(StrictFrozenModel):
    schema_version: Literal[1] = 1
    code: CatalogProblemCode
    message: StrictStr = Field(min_length=1, max_length=200)
    target: StrictStr | None = Field(default=None, max_length=128)
    recoverable: bool
    active_catalog_revision: CatalogRevision | None = None


class ScopeProblemResponse(StrictFrozenModel):
    detail: ScopeProblemDetail


class ScopeNode(StrictFrozenModel):
    key: ScopeKey
    kind: ScopeKind
    label: Label
    short_label: Label
    parent_key: ScopeKey | None
    children_available: bool
    presentation: Literal["boundary", "semantic-only"]

    @model_validator(mode="after")
    def validate_identity_and_parent(self) -> ScopeNode:
        parsed = parse_scope_key(self.key)
        if parsed.kind is not self.kind:
            raise ValueError("key kind does not match declared scope kind")
        if self.kind is ScopeKind.WORLD:
            if self.parent_key is not None:
                raise ValueError("world scope must not have a parent")
            return self
        if self.parent_key is None:
            raise ValueError(f"{self.kind.value} scope must have a parent")
        parent = parse_scope_key(self.parent_key)
        expected_parent = {
            ScopeKind.COUNTRY: ScopeKind.WORLD,
            ScopeKind.ADMIN1: ScopeKind.COUNTRY,
            ScopeKind.ADMIN2: ScopeKind.ADMIN1,
        }[self.kind]
        if parent.kind is not expected_parent:
            raise ValueError(
                f"{self.kind.value} scope must have a {expected_parent.value} parent"
            )
        return self


class CatalogProvenance(StrictFrozenModel):
    boundary_policy: PolicyIdentifier
    representation_id: PolicyIdentifier
    dispute_status: Literal["none", "disputed", "multiple-representations"]
    source_id: PolicyIdentifier
    source_release: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    license_id: PolicyIdentifier
    attribution: Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]


class DerivationInputs(StrictFrozenModel):
    crosswalk_sha256: AssetId
    scope_path: tuple[ScopeKey, ...] = Field(min_length=1, max_length=4)
    assignment_asset_ids: tuple[AssetId, ...] = ()

    @model_validator(mode="after")
    def validate_inputs(self) -> DerivationInputs:
        if len(self.assignment_asset_ids) != len(set(self.assignment_asset_ids)):
            raise ValueError("duplicate assignment asset ID")
        for scope_key in self.scope_path:
            if parse_scope_key(scope_key).canonical != scope_key:
                raise ValueError("derivation scope path must be canonical")
        return self


class GeometryDescriptor(StrictFrozenModel):
    asset_id: AssetId
    media_type: Literal[
        "application/vnd.odin.boundary+json;v=1",
        "application/vnd.odin.boundary-pack+json;v=1",
    ]
    byte_length: StrictInt = Field(gt=0)
    vertex_count: StrictInt = Field(gt=0)
    feature_count: StrictInt | None = Field(default=None, gt=0)
    role: Literal["render"]
    lod: Lod

    @model_validator(mode="after")
    def validate_media_shape(self) -> GeometryDescriptor:
        is_pack = self.media_type == "application/vnd.odin.boundary-pack+json;v=1"
        if is_pack and self.feature_count is None:
            raise ValueError("boundary-pack descriptor requires feature_count")
        if not is_pack and self.feature_count is not None:
            raise ValueError("boundary descriptor must not declare feature_count")
        return self


class ContainmentDescriptor(StrictFrozenModel):
    asset_id: AssetId
    media_type: Literal["application/vnd.odin.boundary+json;v=1"]
    byte_length: StrictInt = Field(gt=0)
    vertex_count: StrictInt = Field(gt=0)
    role: Literal["containment"]
    max_error_m: float = Field(ge=0, le=50)


class ScopePresentation(StrictFrozenModel):
    preferred_lod: Lod | None = None
    outline_lods: dict[Lod, GeometryDescriptor] = Field(default_factory=dict)
    children_lods: dict[Lod, GeometryDescriptor] = Field(default_factory=dict)
    containment: ContainmentDescriptor | None = None


class ManifestScope(StrictFrozenModel):
    scope: ScopeNode
    path: tuple[ScopeKey, ...] = Field(min_length=1, max_length=4)
    provenance: CatalogProvenance
    presentation: ScopePresentation
    provenance_ref: Annotated[StrictStr, StringConstraints(min_length=1, max_length=256)]
    derivation_inputs: DerivationInputs
    derivation_revision: DerivationRevision
    compatible_derivation_revisions: tuple[DerivationRevision, ...] = Field(
        min_length=1,
        max_length=8,
    )
    carry_forward_from: CatalogRevision | None = None

    @model_validator(mode="after")
    def validate_derivation(self) -> ManifestScope:
        expected = derive_derivation_revision(self.derivation_inputs)
        if self.derivation_revision != expected:
            raise ValueError("derivation revision does not match inputs")
        if self.derivation_revision not in self.compatible_derivation_revisions:
            raise ValueError("current derivation revision must be compatible")
        if len(set(self.compatible_derivation_revisions)) != len(
            self.compatible_derivation_revisions
        ):
            raise ValueError("compatible derivation revisions must be unique")
        if self.path != self.derivation_inputs.scope_path:
            raise ValueError("scope path must match derivation lineage inputs")
        return self


class CatalogPointer(StrictFrozenModel):
    """Deployment-owned active/previous catalog selection."""

    schema_version: Literal[1]
    active_catalog_revision: CatalogRevision
    served_catalog_revisions: tuple[CatalogRevision, ...] = Field(
        min_length=1,
        max_length=2,
    )

    @model_validator(mode="after")
    def validate_selection(self) -> CatalogPointer:
        if self.served_catalog_revisions[0] != self.active_catalog_revision:
            raise ValueError("active catalog revision must be first")
        if len(set(self.served_catalog_revisions)) != len(
            self.served_catalog_revisions
        ):
            raise ValueError("served catalog revisions must be unique")
        return self


class CatalogManifest(StrictFrozenModel):
    schema_version: Literal[1]
    catalog_revision: CatalogRevision
    boundary_policy: Literal["odin-reference-v1"]
    root_scope_key: ScopeKey
    attribution_sources_sha256: AssetId
    scopes: tuple[ManifestScope, ...] = Field(min_length=1)
    assets: tuple[AssetId, ...]

    @model_validator(mode="after")
    def validate_complete_manifest(self) -> CatalogManifest:
        records_by_key: dict[str, ManifestScope] = {}
        for record in self.scopes:
            if record.scope.key in records_by_key:
                raise ValueError(f"duplicate manifest scope: {record.scope.key}")
            records_by_key[record.scope.key] = record

        root = records_by_key.get(self.root_scope_key)
        if root is None or self.root_scope_key != "world" or root.scope.parent_key is not None:
            raise ValueError("manifest root must be world without a parent")
        for record in self.scopes:
            parent_key = record.scope.parent_key
            if parent_key is not None and parent_key not in records_by_key:
                raise ValueError(f"unknown parent: {parent_key}")
        _reject_lineage_cycles(records_by_key)

        children_by_parent: dict[str, list[str]] = {}
        for record in self.scopes:
            if record.scope.parent_key is not None:
                children_by_parent.setdefault(record.scope.parent_key, []).append(
                    record.scope.key
                )
        for record in self.scopes:
            expected_path = _lineage_path(record.scope.key, records_by_key)
            if record.path != expected_path:
                raise ValueError(f"complete root-to-scope path required for {record.scope.key}")
            if record.scope.children_available != bool(
                children_by_parent.get(record.scope.key)
            ):
                raise ValueError("children_available does not match manifest lineage")
            _validate_scope_presentation(record.scope, record.presentation)

        if len(self.assets) != len(set(self.assets)):
            raise ValueError("duplicate asset ID")
        if self.assets != tuple(sorted(self.assets)):
            raise ValueError("manifest asset records are not canonically ordered")
        expected_scopes = tuple(
            sorted(self.scopes, key=lambda item: (len(item.path), item.scope.key))
        )
        if self.scopes != expected_scopes:
            raise ValueError("manifest scope records are not canonically ordered")

        referenced = set(iter_manifest_asset_ids(self))
        if referenced != set(self.assets):
            raise ValueError("manifest assets must exactly match descriptor references")

        expected_revision = derive_catalog_revision(self)
        if self.catalog_revision != expected_revision:
            raise ValueError("catalog revision does not match stable manifest content")
        return self


class AttributionSource(StrictFrozenModel):
    source_id: PolicyIdentifier
    release: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    license_id: PolicyIdentifier
    attribution: Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]

    @field_validator("attribution")
    @classmethod
    def reject_html(cls, value: str) -> str:
        if "<" in value or ">" in value:
            raise ValueError("attribution must not contain HTML")
        return value


class CatalogAttribution(StrictFrozenModel):
    schema_version: Literal[1]
    catalog_revision: CatalogRevision
    sources: tuple[AttributionSource, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_sources(self) -> CatalogAttribution:
        source_ids = tuple(source.source_id for source in self.sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate attribution source")
        if source_ids != tuple(sorted(source_ids)):
            raise ValueError("attribution sources must be canonically ordered")
        return self


class SourceLockRecord(StrictFrozenModel):
    source_id: PolicyIdentifier
    release: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    url: Annotated[StrictStr, StringConstraints(min_length=1, max_length=2048)]
    sha256: AssetId
    license_id: PolicyIdentifier
    attribution: Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]

    @field_validator("attribution")
    @classmethod
    def reject_html(cls, value: str) -> str:
        if "<" in value or ">" in value:
            raise ValueError("attribution must not contain HTML")
        return value


class SourceLock(StrictFrozenModel):
    schema_version: Literal[1]
    sources: tuple[SourceLockRecord, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_sources(self) -> SourceLock:
        source_ids = tuple(source.source_id for source in self.sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate source-lock source")
        return self


class CatalogCapabilities(StrictFrozenModel):
    max_enabled_kind: ScopeKind
    timeline_scope: Literal["bbox_approximate", "exact"]
    intelligence_scope: Literal["unavailable", "exact"]


class BootstrapAttributionSource(StrictFrozenModel):
    source_id: PolicyIdentifier
    release: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    license_id: PolicyIdentifier
    text: Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]


class BootstrapAttribution(StrictFrozenModel):
    catalog_revision: CatalogRevision
    representation_note: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=500),
    ]
    sources: tuple[BootstrapAttributionSource, ...] = Field(min_length=1, max_length=32)


class CatalogBootstrapResponse(StrictFrozenModel):
    schema_version: Literal[1] = 1
    active_catalog_revision: CatalogRevision
    served_catalog_revisions: tuple[CatalogRevision, ...] = Field(min_length=1, max_length=2)
    boundary_policy: Literal["odin-reference-v1"]
    root_scope_key: ScopeKey
    capabilities: CatalogCapabilities
    attributions: tuple[BootstrapAttribution, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_served_attributions(self) -> CatalogBootstrapResponse:
        if self.active_catalog_revision != self.served_catalog_revisions[0]:
            raise ValueError("active revision must be first in served revisions")
        attribution_revisions = tuple(item.catalog_revision for item in self.attributions)
        if attribution_revisions != self.served_catalog_revisions:
            raise ValueError("exactly one attribution is required per served revision")
        return self


class BoundaryRenderDescriptor(StrictFrozenModel):
    asset_id: AssetId
    media_type: Literal["application/vnd.odin.boundary+json;v=1"]
    byte_length: StrictInt = Field(gt=0)
    vertex_count: StrictInt = Field(gt=0)
    role: Literal["render"]
    lod: Lod


class BoundaryPackRenderDescriptor(StrictFrozenModel):
    asset_id: AssetId
    media_type: Literal["application/vnd.odin.boundary-pack+json;v=1"]
    byte_length: StrictInt = Field(gt=0)
    vertex_count: StrictInt = Field(gt=0)
    feature_count: StrictInt = Field(gt=0)
    role: Literal["render"]
    lod: Lod


type RenderDescriptor = BoundaryRenderDescriptor | BoundaryPackRenderDescriptor


class ScopePresentationResponse(StrictFrozenModel):
    preferred_lod: Lod | None
    outline_lods: dict[Lod, RenderDescriptor]
    children_lods: dict[Lod, RenderDescriptor]


class ScopeBundleResponse(StrictFrozenModel):
    schema_version: Literal[1] = 1
    catalog_revision: CatalogRevision
    boundary_policy: Literal["odin-reference-v1"]
    canonicalized_from: ScopeKey | None
    scope: ScopeNode
    path: tuple[ScopeNode, ...] = Field(min_length=1, max_length=4)
    presentation: ScopePresentationResponse
    containment: ContainmentDescriptor | None
    provenance_ref: Annotated[StrictStr, StringConstraints(min_length=1, max_length=256)]


class ParsedScopeKey(StrictFrozenModel):
    canonical: ScopeKey
    kind: ScopeKind
    namespace: StrictStr | None
    canonical_code: StrictStr | None


_LEXICAL_SCOPE_KEY: Final = re.compile(r"^[A-Za-z0-9:._-]+$")
_CATALOG_REVISION: Final = re.compile(r"^spatial-v[0-9]+-[a-f0-9]{12,64}$")
_ASSET_ID: Final = re.compile(r"^[a-f0-9]{64}$")
_NORMALIZABLE_ISO3: Final = re.compile(r"^country:([A-Za-z]{3})$")
_NORMALIZABLE_ISO3166_2: Final = re.compile(
    r"^admin1:iso3166-2:([A-Za-z]{2})-([A-Za-z0-9]{1,3})$"
)
_SCOPE_KEY_PATTERNS: Final[tuple[tuple[ScopeKind, str | None, re.Pattern[str]], ...]] = (
    (ScopeKind.WORLD, None, re.compile(r"^world$")),
    (ScopeKind.COUNTRY, "iso3166-1", re.compile(r"^country:([A-Z]{3})$")),
    (ScopeKind.COUNTRY, "m49", re.compile(r"^country:m49:([0-9]{3})$")),
    (
        ScopeKind.COUNTRY,
        "odin",
        re.compile(r"^country:odin:([a-z0-9][a-z0-9._-]{0,79})$"),
    ),
    (
        ScopeKind.ADMIN1,
        "iso3166-2",
        re.compile(r"^admin1:iso3166-2:([A-Z]{2}-[A-Z0-9]{1,3})$"),
    ),
    (
        ScopeKind.ADMIN1,
        "gbopen",
        re.compile(r"^admin1:gbopen:([A-Za-z0-9._-]{1,80})$"),
    ),
    (
        ScopeKind.ADMIN2,
        None,
        re.compile(r"^admin2:([A-Za-z0-9._-]{1,24}):([A-Za-z0-9._-]{1,80})$"),
    ),
)


def normalize_scope_key_candidate(candidate: str) -> str:
    """Canonicalize only the ISO-owned segments of a validated candidate."""

    if not isinstance(candidate, str):
        raise ValueError("INVALID_SCOPE_KEY")
    try:
        encoded_length = len(candidate.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("INVALID_SCOPE_KEY") from exc
    if not 1 <= encoded_length <= 128 or _LEXICAL_SCOPE_KEY.fullmatch(candidate) is None:
        raise ValueError("INVALID_SCOPE_KEY")
    iso3 = _NORMALIZABLE_ISO3.fullmatch(candidate)
    if iso3 is not None:
        return f"country:{iso3.group(1).upper()}"
    iso3166_2 = _NORMALIZABLE_ISO3166_2.fullmatch(candidate)
    if iso3166_2 is not None:
        return (
            "admin1:iso3166-2:"
            f"{iso3166_2.group(1).upper()}-{iso3166_2.group(2).upper()}"
        )
    return candidate


def parse_scope_key(candidate: str) -> ParsedScopeKey:
    canonical = normalize_scope_key_candidate(candidate)
    for kind, namespace, pattern in _SCOPE_KEY_PATTERNS:
        match = pattern.fullmatch(canonical)
        if match is None:
            continue
        if kind is ScopeKind.WORLD:
            return ParsedScopeKey(
                canonical=canonical,
                kind=kind,
                namespace=None,
                canonical_code=None,
            )
        if kind is ScopeKind.ADMIN2:
            return ParsedScopeKey(
                canonical=canonical,
                kind=kind,
                namespace=match.group(1),
                canonical_code=match.group(2),
            )
        code = match.group(1)
        if namespace == "iso3166-1" and code == "XKX":
            raise ValueError("INVALID_SCOPE_KEY")
        return ParsedScopeKey(
            canonical=canonical,
            kind=kind,
            namespace=namespace,
            canonical_code=code,
        )
    raise ValueError("INVALID_SCOPE_KEY")


def validate_catalog_revision_candidate(candidate: str) -> str:
    if (
        not isinstance(candidate, str)
        or not 23 <= len(candidate) <= 79
        or _CATALOG_REVISION.fullmatch(candidate) is None
    ):
        raise ValueError("INVALID_CATALOG_REVISION")
    return candidate


def validate_asset_id_candidate(candidate: str) -> str:
    if (
        not isinstance(candidate, str)
        or len(candidate) != 64
        or _ASSET_ID.fullmatch(candidate) is None
    ):
        raise ValueError("INVALID_ASSET_ID")
    return candidate


def derive_derivation_revision(inputs: DerivationInputs) -> str:
    payload = {
        "schema_version": 1,
        "crosswalk_sha256": inputs.crosswalk_sha256,
        "scope_path": inputs.scope_path,
        "assignment_asset_ids": tuple(sorted(inputs.assignment_asset_ids)),
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"spatial-derive-v1-{digest[:12]}"


def derive_catalog_revision(manifest: CatalogManifest) -> str:
    payload = {
        "schema_version": manifest.schema_version,
        "boundary_policy": manifest.boundary_policy,
        "root_scope_key": manifest.root_scope_key,
        "attribution_sources_sha256": manifest.attribution_sources_sha256,
        "scopes": manifest.scopes,
        "assets": manifest.assets,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"spatial-v1-{digest[:12]}"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _normalize_json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def iter_manifest_asset_ids(manifest: CatalogManifest) -> tuple[str, ...]:
    asset_ids: list[str] = []
    for record in manifest.scopes:
        asset_ids.extend(
            descriptor.asset_id
            for descriptor in (
                *record.presentation.outline_lods.values(),
                *record.presentation.children_lods.values(),
            )
        )
        if record.presentation.containment is not None:
            asset_ids.append(record.presentation.containment.asset_id)
    return tuple(asset_ids)


def iter_manifest_descriptors(
    manifest: CatalogManifest,
) -> tuple[GeometryDescriptor | ContainmentDescriptor, ...]:
    descriptors: list[GeometryDescriptor | ContainmentDescriptor] = []
    for record in manifest.scopes:
        descriptors.extend(record.presentation.outline_lods.values())
        descriptors.extend(record.presentation.children_lods.values())
        if record.presentation.containment is not None:
            descriptors.append(record.presentation.containment)
    return tuple(descriptors)


def _validate_scope_presentation(
    scope: ScopeNode,
    presentation: ScopePresentation,
) -> None:
    for lod, descriptor in (
        *presentation.outline_lods.items(),
        *presentation.children_lods.items(),
    ):
        if descriptor.lod is not lod:
            raise ValueError("descriptor LOD must match its map key")
    if scope.children_available:
        if (
            presentation.preferred_lod is None
            or presentation.preferred_lod not in presentation.children_lods
        ):
            raise ValueError("preferred_lod must name an available children LOD")
    elif presentation.children_lods or presentation.preferred_lod is not None:
        raise ValueError("non-drillable scope cannot publish children LODs")


def _reject_lineage_cycles(records_by_key: Mapping[str, ManifestScope]) -> None:
    for start in records_by_key:
        seen: set[str] = set()
        current: str | None = start
        while current is not None:
            if current in seen:
                raise ValueError(f"manifest lineage contains a cycle at {current}")
            seen.add(current)
            current = records_by_key[current].scope.parent_key


def _lineage_path(
    scope_key: str,
    records_by_key: Mapping[str, ManifestScope],
) -> tuple[str, ...]:
    reversed_path: list[str] = []
    current: str | None = scope_key
    while current is not None:
        reversed_path.append(current)
        current = records_by_key[current].scope.parent_key
    return tuple(reversed(reversed_path))


def _normalize_json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _normalize_json_value(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON rejects non-finite numbers")
        if value == 0:
            return 0
        if value.is_integer():
            return int(value)
    if value is None or isinstance(value, (bool, int, str, float)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")
