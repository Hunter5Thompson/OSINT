"""Frozen public contracts for the offline spatial catalog.

Identity, provenance, derivation compatibility, and geometry descriptors stay in
separate models.  Manifest assembly composes them instead of allowing build stages
to maintain parallel, weaker dictionaries.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
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

_IDENTITY_SPEC = (
    "docs/superpowers/specs/2026-07-31-spatial-scope-drilldown/"
    "02-scope-identity-and-boundary-policy.md"
)
CONTRACT_DOC_OWNERS: Final[tuple[tuple[str, str], ...]] = (
    ("CatalogRevision", _IDENTITY_SPEC),
    ("DerivationRevision", _IDENTITY_SPEC),
    ("ScopeKey", _IDENTITY_SPEC),
    ("ScopeKind", _IDENTITY_SPEC),
)


class ScopeKind(StrEnum):
    WORLD = "world"
    COUNTRY = "country"
    ADMIN1 = "admin1"
    ADMIN2 = "admin2"


class Lod(StrEnum):
    OVERVIEW = "overview"
    REGIONAL = "regional"
    DETAIL = "detail"


class StrictFrozenModel(BaseModel):
    """Shared model policy without weakening JSON enum decoding."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopeNode(StrictFrozenModel):
    """Stable semantic identity and its immediate lineage relation."""

    key: ScopeKey
    kind: ScopeKind
    label: Label
    short_label: Label
    parent_key: ScopeKey | None
    children_available: bool
    presentation: Literal["boundary", "semantic-only"]

    @model_validator(mode="after")
    def validate_identity_and_parent(self) -> ScopeNode:
        # Local import avoids making the identity parser depend on manifest models.
        from spatial_catalog.identity import InvalidScopeKeyError, parse_scope_key

        try:
            parsed = parse_scope_key(self.key)
        except InvalidScopeKeyError as exc:
            raise ValueError(str(exc)) from exc
        if parsed.kind is not self.kind:
            raise ValueError("key kind does not match declared scope kind")

        if self.kind is ScopeKind.WORLD:
            if self.parent_key is not None:
                raise ValueError("world scope must not have a parent")
            return self
        if self.parent_key is None:
            raise ValueError(f"{self.kind.value} scope must have a parent")

        try:
            parent = parse_scope_key(self.parent_key)
        except InvalidScopeKeyError as exc:
            raise ValueError(str(exc)) from exc
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
    """Reviewed political representation and source attribution."""

    boundary_policy: PolicyIdentifier
    representation_id: PolicyIdentifier
    dispute_status: Literal["none", "disputed", "multiple-representations"]
    source_id: PolicyIdentifier
    source_release: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    license_id: PolicyIdentifier
    attribution: Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]


class DerivationCompatibility(StrictFrozenModel):
    """Per-scope compatibility; catalog and derivation revisions never mix."""

    catalog_revision: CatalogRevision
    current: DerivationRevision
    compatible: tuple[DerivationRevision, ...] = Field(min_length=1, max_length=8)
    carry_forward_from: CatalogRevision | None = None

    @model_validator(mode="after")
    def validate_compatible_revisions(self) -> DerivationCompatibility:
        if self.current not in self.compatible:
            raise ValueError("current derivation revision must be compatible")
        if len(set(self.compatible)) != len(self.compatible):
            raise ValueError("compatible derivation revisions must be unique")
        return self


class GeometryDescriptor(StrictFrozenModel):
    """Content-addressed render geometry descriptor."""

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
    """Topology-preserving containment asset, never a render LOD."""

    asset_id: AssetId
    media_type: Literal["application/vnd.odin.boundary+json;v=1"]
    byte_length: StrictInt = Field(gt=0)
    vertex_count: StrictInt = Field(gt=0)
    role: Literal["containment"]
    max_error_m: float = Field(ge=0, le=50)


class ScopePresentation(StrictFrozenModel):
    """Geometry references kept separate from semantic scope identity."""

    preferred_lod: Lod | None = None
    outline_lods: dict[Lod, GeometryDescriptor] = Field(default_factory=dict)
    children_lods: dict[Lod, GeometryDescriptor] = Field(default_factory=dict)
    containment: ContainmentDescriptor | None = None


def validate_scope_presentation(scope: ScopeNode, presentation: ScopePresentation) -> None:
    """Validate the cross-model drillability rules without merging the models."""

    descriptors = (*presentation.outline_lods.items(), *presentation.children_lods.items())
    for lod, descriptor in descriptors:
        if descriptor.lod is not lod:
            raise ValueError("descriptor LOD must match its map key")

    if scope.children_available:
        if (
            presentation.preferred_lod is None
            or presentation.preferred_lod not in presentation.children_lods
        ):
            raise ValueError("preferred_lod must name an available children LOD")
        return
    if presentation.children_lods or presentation.preferred_lod is not None:
        raise ValueError("non-drillable scope cannot publish children LODs")


def validate_scope_path(path: tuple[ScopeNode, ...]) -> None:
    """Require a complete, contiguous root-to-scope path of bounded depth."""

    if not path or path[0].kind is not ScopeKind.WORLD or path[0].key != "world":
        raise ValueError("path must start at world")
    if len(path) > 4:
        raise ValueError("maximum lineage depth is 4")
    if len({node.key for node in path}) != len(path):
        raise ValueError("scope path contains a cycle")
    for parent, child in zip(path, path[1:], strict=False):
        if child.parent_key != parent.key:
            raise ValueError("path is not contiguous")
    expected_depth = {
        ScopeKind.WORLD: 1,
        ScopeKind.COUNTRY: 2,
        ScopeKind.ADMIN1: 3,
        ScopeKind.ADMIN2: 4,
    }[path[-1].kind]
    if len(path) != expected_depth:
        raise ValueError("path is incomplete for scope kind")
