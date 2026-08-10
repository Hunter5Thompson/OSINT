"""Pure spatial contracts for Qdrant projection and retrieval.

The relation-specific payload field supplies the relation.  Each value stored in
that field atomically pairs one canonical non-global scope key with the derivation
revision that belongs to that scope.
"""

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
    model_validator,
)
from qdrant_client import models

SCOPE_REVISION_TOKEN_PREFIX: Final = "sr1"
SCOPE_REVISION_TOKEN_VERSION: Final = SCOPE_REVISION_TOKEN_PREFIX
SCOPE_REVISION_TOKEN_SEPARATOR: Final = "|"
MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES: Final = 229
SPATIAL_DERIVATION_VERSION: Final = "spatial-deriver-v2"
ABOUT_GATE_REVISION: Final = (
    "about-gate-v1-unique-reviewed-crosswalk-confidence-gte-0.80"
)
_PROJECTION_SCHEMA_VERSION: Final = 1

_SCOPE_KEY = re.compile(
    r"^(?:"
    r"country:[A-Z]{3}|"
    r"country:m49:[0-9]{3}|"
    r"country:odin:[a-z0-9][a-z0-9._-]{0,79}|"
    r"admin1:iso3166-2:[A-Z]{2}-[A-Z0-9]{1,3}|"
    r"admin1:gbopen:[A-Za-z0-9._-]{1,80}|"
    r"admin2:[A-Za-z0-9._-]{1,24}:[A-Za-z0-9._-]{1,80}"
    r")$"
)
_DERIVATION_REVISION = re.compile(r"^spatial-derive-v[0-9]+-[a-f0-9]{12,64}$")
_SCOPE_KINDS: Final[tuple[tuple[ScopeKind, re.Pattern[str]], ...]]

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
type ProjectionRevision = Annotated[
    StrictStr,
    StringConstraints(
        min_length=34,
        max_length=90,
        pattern=r"^spatial-projection-v[0-9]+-[a-f0-9]{12,64}$",
    ),
]


class StrictFrozenModel(BaseModel):
    """Strict immutable contract at the service boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ScopeKind(StrEnum):
    WORLD = "world"
    COUNTRY = "country"
    ADMIN1 = "admin1"
    ADMIN2 = "admin2"


_SCOPE_KINDS = (
    (ScopeKind.WORLD, re.compile(r"^world$")),
    (ScopeKind.COUNTRY, re.compile(r"^country:[A-Z]{3}$")),
    (ScopeKind.COUNTRY, re.compile(r"^country:m49:[0-9]{3}$")),
    (
        ScopeKind.COUNTRY,
        re.compile(r"^country:odin:[a-z0-9][a-z0-9._-]{0,79}$"),
    ),
    (
        ScopeKind.ADMIN1,
        re.compile(r"^admin1:iso3166-2:[A-Z]{2}-[A-Z0-9]{1,3}$"),
    ),
    (ScopeKind.ADMIN1, re.compile(r"^admin1:gbopen:[A-Za-z0-9._-]{1,80}$")),
    (
        ScopeKind.ADMIN2,
        re.compile(r"^admin2:[A-Za-z0-9._-]{1,24}:[A-Za-z0-9._-]{1,80}$"),
    ),
)


class SpatialScopeTokenV1(StrictFrozenModel):
    """Pinned catalog identity supplied by the trusted scope resolver."""

    schema_version: Literal[1] = 1
    scope_key: ScopeKey
    kind: ScopeKind
    catalog_revision: CatalogRevision
    derivation_revision: DerivationRevision
    boundary_policy: Annotated[
        StrictStr,
        StringConstraints(
            min_length=1,
            max_length=96,
            pattern=r"^[A-Za-z0-9._-]+$",
        ),
    ]
    compatible_derivation_revisions: tuple[DerivationRevision, ...] = Field(
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_identity_and_compatibility(self) -> SpatialScopeTokenV1:
        if _scope_kind(self.scope_key) is not self.kind:
            raise ValueError("scope key kind does not match token kind")
        if self.derivation_revision not in self.compatible_derivation_revisions:
            raise ValueError("derivation_revision must be compatible")
        if len(set(self.compatible_derivation_revisions)) != len(
            self.compatible_derivation_revisions
        ):
            raise ValueError("compatible derivation revisions must be unique")
        return self


class RetrievalSpatialRelation(StrEnum):
    ABOUT = "about"
    OCCURRENCE = "occurrence"
    EITHER = "either"


class QdrantAoiBoxV1(StrictFrozenModel):
    """One finite non-wrapping box; dateline AOIs supply two boxes."""

    west: float
    south: float
    east: float
    north: float

    @model_validator(mode="after")
    def validate_box(self) -> QdrantAoiBoxV1:
        values = (self.west, self.south, self.east, self.north)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("AOI coordinates must be finite")
        if not -180 <= self.west <= self.east <= 180:
            raise ValueError("AOI longitude box must be non-wrapping")
        if not -90 <= self.south <= self.north <= 90:
            raise ValueError("AOI latitude range is invalid")
        return self


class SpatialLaneCoverageV1(StrictFrozenModel):
    """Machine-readable accounting for one corpus lane."""

    lane: Annotated[
        StrictStr,
        StringConstraints(
            min_length=1,
            max_length=64,
            pattern=r"^[a-z][a-z0-9_-]*$",
        ),
    ]
    total_points: StrictInt = Field(ge=0)
    filterable_points: StrictInt = Field(ge=0)
    conflict_points: StrictInt = Field(ge=0)
    stale_points: StrictInt = Field(ge=0)
    unsupported_points: StrictInt = Field(ge=0)
    unprojected_points: StrictInt = Field(ge=0)
    audit_only_points: StrictInt = Field(ge=0)
    inconsistent_points: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_accounting(self) -> SpatialLaneCoverageV1:
        accounted = (
            self.filterable_points
            + self.conflict_points
            + self.stale_points
            + self.unsupported_points
            + self.unprojected_points
            + self.audit_only_points
            + self.inconsistent_points
        )
        if accounted != self.total_points:
            raise ValueError("lane accounting must equal total points")
        return self


class SpatialCoverageSnapshotV1(StrictFrozenModel):
    """Coverage coupled to one target projection revision."""

    schema_version: Literal[1] = 1
    target_projection_revision: ProjectionRevision
    lanes: tuple[SpatialLaneCoverageV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_lanes(self) -> SpatialCoverageSnapshotV1:
        names = tuple(lane.lane for lane in self.lanes)
        if len(set(names)) != len(names):
            raise ValueError("coverage lanes must be unique")
        return self


class SpatialContractError(ValueError):
    """A value cannot cross the spatial payload seam safely."""


def unavailable_spatial_payload(reason: str) -> dict[str, object]:
    """Mark an unsupported writer lane without inventing a spatial assignment."""

    if not isinstance(reason, str) or not reason.strip():
        raise SpatialContractError("unavailable reason must be non-empty")
    return {
        "spatial_about_scope_revision_tokens": [],
        "spatial_occurrence_scope_revision_tokens": [],
        "spatial_basis": [],
        "spatial_derivation_version": SPATIAL_DERIVATION_VERSION,
        "spatial_conflict": False,
        "spatial_conflict_scope_keys": [],
        "spatial_derivation_status": "unavailable",
        "spatial_derivation_unavailable_reason": reason,
        "spatial_derivations": [],
    }


def derive_spatial_projection_revision(
    scope_derivation_revisions: Mapping[str, str],
) -> str:
    """Fingerprint projection semantics and the complete scope revision map."""

    if not isinstance(scope_derivation_revisions, Mapping):
        raise SpatialContractError("scope derivation revisions must be a mapping")
    canonical_pairs: list[tuple[str, str]] = []
    for scope_key, revision in scope_derivation_revisions.items():
        if not isinstance(scope_key, str):
            raise SpatialContractError("scope derivation revision key must be a string")
        try:
            _scope_kind(scope_key)
        except ValueError as error:
            raise SpatialContractError("invalid canonical scope key") from error
        if (
            not isinstance(revision, str)
            or _DERIVATION_REVISION.fullmatch(revision) is None
        ):
            raise SpatialContractError("invalid derivation revision")
        canonical_pairs.append((scope_key, revision))
    if not canonical_pairs:
        raise SpatialContractError("scope derivation revisions must not be empty")

    canonical_inputs = {
        "schema_version": _PROJECTION_SCHEMA_VERSION,
        "scope_revision_token_version": SCOPE_REVISION_TOKEN_VERSION,
        "derivation_version": SPATIAL_DERIVATION_VERSION,
        "about_gate_revision": ABOUT_GATE_REVISION,
        "sorted_scope_derivation_revisions": sorted(canonical_pairs),
    }
    encoded = json.dumps(
        canonical_inputs,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"spatial-projection-v1-{digest}"


def encode_scope_revision_token(scope_key: str, derivation_revision: str) -> str:
    """Return the injective V1 keyword for one scope/revision assignment.

    ``|`` is excluded by both input grammars.  Splitting a valid token into its
    three components therefore recovers exactly the original pair without a hash
    or collision domain.  ``world`` is intentionally not materialized.
    """

    if not isinstance(scope_key, str) or _SCOPE_KEY.fullmatch(scope_key) is None:
        raise SpatialContractError("invalid non-global scope key")
    if (
        not isinstance(derivation_revision, str)
        or _DERIVATION_REVISION.fullmatch(derivation_revision) is None
    ):
        raise SpatialContractError("invalid derivation revision")
    token = (
        f"{SCOPE_REVISION_TOKEN_PREFIX}{SCOPE_REVISION_TOKEN_SEPARATOR}"
        f"{scope_key}{SCOPE_REVISION_TOKEN_SEPARATOR}{derivation_revision}"
    )
    if len(token.encode("ascii")) > MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES:
        raise SpatialContractError(
            "scope revision token exceeds 229 ASCII bytes"
        )
    return token


_RELATION_FIELDS: Final = {
    RetrievalSpatialRelation.ABOUT: "spatial_about_scope_revision_tokens",
    RetrievalSpatialRelation.OCCURRENCE: "spatial_occurrence_scope_revision_tokens",
}


def compile_qdrant_scope_filter(
    token: SpatialScopeTokenV1,
    relation: RetrievalSpatialRelation,
) -> models.Filter | None:
    """Compile one allowlisted relation filter from a trusted pinned token."""

    if not isinstance(token, SpatialScopeTokenV1):
        raise SpatialContractError("scope token must be SpatialScopeTokenV1")
    if not isinstance(relation, RetrievalSpatialRelation):
        raise SpatialContractError("relation must be allowlisted")
    if token.kind is ScopeKind.WORLD:
        return None

    about = _relation_condition(
        _RELATION_FIELDS[RetrievalSpatialRelation.ABOUT],
        token,
    )
    occurrence = _relation_condition(
        _RELATION_FIELDS[RetrievalSpatialRelation.OCCURRENCE],
        token,
    )
    relation_condition: models.FieldCondition | models.Filter
    if relation is RetrievalSpatialRelation.ABOUT:
        relation_condition = about
    elif relation is RetrievalSpatialRelation.OCCURRENCE:
        relation_condition = occurrence
    else:
        relation_condition = models.Filter(should=[about, occurrence])
    return models.Filter(must=[relation_condition])


def compile_qdrant_aoi_filter(
    boxes: tuple[QdrantAoiBoxV1, ...],
) -> models.Filter:
    """Compile one or two already-segmented AOI boxes on the allowlisted geo field."""

    if not isinstance(boxes, tuple) or not 1 <= len(boxes) <= 2:
        raise SpatialContractError("AOI requires one or two boxes")
    if not all(isinstance(box, QdrantAoiBoxV1) for box in boxes):
        raise SpatialContractError("AOI boxes must be QdrantAoiBoxV1")
    conditions = [_aoi_condition(box) for box in boxes]
    geo_condition: models.FieldCondition | models.Filter = conditions[0]
    if len(conditions) == 2:
        geo_condition = models.Filter(should=conditions)
    return models.Filter(must=[geo_condition])


def combine_filters(
    base: models.Filter,
    spatial: models.Filter | None,
) -> models.Filter:
    """Nest spatial policy without mutating or flattening the corpus policy."""

    if not isinstance(base, models.Filter):
        raise SpatialContractError("base filter must be a Qdrant Filter")
    if spatial is None:
        return base
    if not isinstance(spatial, models.Filter):
        raise SpatialContractError("spatial filter must be a Qdrant Filter")
    return models.Filter(must=[base, spatial])


def _scope_kind(scope_key: str) -> ScopeKind:
    for kind, pattern in _SCOPE_KINDS:
        if pattern.fullmatch(scope_key) is not None:
            return kind
    raise ValueError("invalid canonical scope key")


def _scope_revision_tokens(token: SpatialScopeTokenV1) -> list[str]:
    return [
        encode_scope_revision_token(token.scope_key, revision)
        for revision in token.compatible_derivation_revisions
    ]


def _relation_condition(
    field: str,
    token: SpatialScopeTokenV1,
) -> models.FieldCondition:
    if field not in _RELATION_FIELDS.values():
        raise SpatialContractError("relation field must be allowlisted")
    return models.FieldCondition(
        key=field,
        match=models.MatchAny(any=_scope_revision_tokens(token)),
    )


def _aoi_condition(box: QdrantAoiBoxV1) -> models.FieldCondition:
    return models.FieldCondition(
        key="geo",
        geo_bounding_box=models.GeoBoundingBox(
            top_left=models.GeoPoint(lon=box.west, lat=box.north),
            bottom_right=models.GeoPoint(lon=box.east, lat=box.south),
        ),
    )


__all__ = [
    "MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES",
    "SCOPE_REVISION_TOKEN_PREFIX",
    "SCOPE_REVISION_TOKEN_SEPARATOR",
    "QdrantAoiBoxV1",
    "RetrievalSpatialRelation",
    "ScopeKind",
    "SpatialContractError",
    "SpatialCoverageSnapshotV1",
    "SpatialLaneCoverageV1",
    "SpatialScopeTokenV1",
    "combine_filters",
    "compile_qdrant_aoi_filter",
    "compile_qdrant_scope_filter",
    "encode_scope_revision_token",
    "unavailable_spatial_payload",
]
