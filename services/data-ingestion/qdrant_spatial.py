"""Pure deterministic projection of reviewed spatial evidence into Qdrant payloads."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph_integrity.spatial_normalizer import (
    CountryCodeSystem,
    RawLocationIdentity,
    SpatialNormalizationIndex,
    SpatialNormalizationResult,
)
from spatial_catalog.identity import CountryCrosswalk, parse_scope_key
from spatial_catalog.models import ScopeKind

SCOPE_REVISION_TOKEN_VERSION: Final = "sr1"
MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES: Final = 229
SPATIAL_DERIVATION_VERSION: Final = "spatial-deriver-v2"
ABOUT_CONFIDENCE_THRESHOLD: Final = 0.80
ABOUT_GATE_REVISION: Final = (
    "about-gate-v1-unique-reviewed-crosswalk-confidence-gte-0.80"
)
_PROJECTION_SCHEMA_VERSION: Final = 1
_DERIVATION_REVISION = re.compile(r"^spatial-derive-v[0-9]+-[a-f0-9]{12,64}$")


class SpatialProjectionError(ValueError):
    """Evidence cannot cross the deterministic Qdrant projection seam."""


class SpatialRelation(StrEnum):
    ABOUT = "about"
    OCCURRENCE = "occurrence"


class SpatialEvidenceKind(StrEnum):
    STRUCTURED_EVENT_LOCATION = "structured_event_location"
    SENSOR_COORDINATE = "sensor_coordinate"
    EXTRACTED_GEO_ENTITY = "extracted_geo_entity"


class SpatialCrosswalkStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    UNIQUE_REVIEWED = "unique_reviewed"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"


class SpatialEvidenceV1(BaseModel):
    """One source-owned derivation with normalized Plan-06A provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relation: SpatialRelation
    evidence_kind: SpatialEvidenceKind
    evidence_id: str = Field(min_length=1, max_length=300)
    normalization: SpatialNormalizationResult
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    crosswalk_status: SpatialCrosswalkStatus

    @model_validator(mode="after")
    def validate_relation_kind(self) -> SpatialEvidenceV1:
        if self.relation is SpatialRelation.ABOUT:
            if self.evidence_kind is not SpatialEvidenceKind.EXTRACTED_GEO_ENTITY:
                raise ValueError("about evidence must be an extracted geo entity")
            if self.crosswalk_status is SpatialCrosswalkStatus.NOT_REQUIRED:
                raise ValueError("about evidence requires explicit crosswalk status")
        elif self.evidence_kind not in {
            SpatialEvidenceKind.STRUCTURED_EVENT_LOCATION,
            SpatialEvidenceKind.SENSOR_COORDINATE,
        }:
            raise ValueError("occurrence evidence must be a structured location")
        return self


@dataclass(frozen=True, slots=True)
class ReviewedGeoNameCrosswalk:
    """Exact-name lookup built only from reviewed registry entries."""

    _resolved: Mapping[str, RawLocationIdentity]
    _ambiguous: frozenset[str]

    def resolve(
        self,
        name: str,
    ) -> tuple[RawLocationIdentity | None, SpatialCrosswalkStatus]:
        key = _normalize_exact_name(name)
        if key in self._ambiguous:
            return None, SpatialCrosswalkStatus.AMBIGUOUS
        raw = self._resolved.get(key)
        if raw is None:
            return None, SpatialCrosswalkStatus.UNMATCHED
        return raw, SpatialCrosswalkStatus.UNIQUE_REVIEWED


def build_reviewed_country_name_crosswalk(
    crosswalk: CountryCrosswalk,
) -> ReviewedGeoNameCrosswalk:
    """Build a unique exact-label adapter from the reviewed country registry."""

    candidates: dict[str, list[RawLocationIdentity]] = {}
    for record in crosswalk.records:
        if record.scope_key is None:
            continue
        key = _normalize_exact_name(record.source_label)
        candidates.setdefault(key, []).append(
            RawLocationIdentity(
                country_code=record.scope_key,
                country_code_system=CountryCodeSystem.ODIN_SCOPE_KEY,
                source_country_name=record.source_label,
            )
        )

    resolved = {
        key: values[0]
        for key, values in candidates.items()
        if len(values) == 1
    }
    ambiguous = frozenset(key for key, values in candidates.items() if len(values) != 1)
    return ReviewedGeoNameCrosswalk(
        _resolved=MappingProxyType(resolved),
        _ambiguous=ambiguous,
    )


def derive_spatial_projection_revision(index: SpatialNormalizationIndex) -> str:
    """Fingerprint projection semantics without depending on catalog provenance."""

    return _derive_spatial_projection_revision(
        index.scope_derivation_revision_items()
    )


@lru_cache(maxsize=16)
def _derive_spatial_projection_revision(
    scope_derivation_revisions: tuple[tuple[str, str], ...],
) -> str:
    canonical_inputs = {
        "schema_version": _PROJECTION_SCHEMA_VERSION,
        "scope_revision_token_version": SCOPE_REVISION_TOKEN_VERSION,
        "derivation_version": SPATIAL_DERIVATION_VERSION,
        "about_gate_revision": ABOUT_GATE_REVISION,
        "sorted_scope_derivation_revisions": list(scope_derivation_revisions),
    }
    encoded = json.dumps(
        canonical_inputs,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"spatial-projection-v1-{digest}"


def project_spatial_payload(
    evidence: Sequence[SpatialEvidenceV1],
    index: SpatialNormalizationIndex,
) -> dict[str, Any]:
    """Project source evidence into one complete, deterministic spatial payload."""

    ordered = sorted(
        evidence,
        key=lambda item: (
            item.evidence_id,
            item.relation.value,
            item.evidence_kind.value,
        ),
    )
    candidates: list[tuple[SpatialEvidenceV1, list[dict[str, Any]], str]] = []
    bases: set[str] = set()
    precisions: set[str] = set()
    conflict_scope_keys: set[str] = set()
    conflicts_by_relation: dict[SpatialRelation, set[str]] = {
        relation: set() for relation in SpatialRelation
    }
    source_country_codes: set[str] = set()
    source_country_code_systems: set[str] = set()
    country_iso3_codes: set[str] = set()
    admin1_codes: set[str] = set()
    admin2_codes: set[str] = set()

    for item in ordered:
        result = item.normalization
        if result.spatial_catalog_revision != index.catalog_revision:
            raise SpatialProjectionError(
                "normalization catalog revision does not match projection index"
            )
        has_conflict_keys = bool(result.spatial_conflict_scope_keys)
        if (
            result.spatial_conflict is not has_conflict_keys
            or (result.status == "conflict") is not has_conflict_keys
        ):
            raise SpatialProjectionError(
                "normalization conflict flag and scope keys disagree"
            )
        assignments = _audit_assignments(result, index)
        reason = _filter_reason(item, assignments)
        candidates.append((item, assignments, reason))
        if result.spatial_conflict:
            conflict_scope_keys.update(result.spatial_conflict_scope_keys)
            conflicts_by_relation[item.relation].update(
                result.spatial_conflict_scope_keys
            )
        if result.source_country_code is not None:
            source_country_codes.add(result.source_country_code)
        if result.source_country_code_system is not None:
            source_country_code_systems.add(result.source_country_code_system.value)
        if result.country_iso3 is not None:
            country_iso3_codes.add(result.country_iso3)
        if result.admin1_code is not None:
            admin1_codes.add(result.admin1_code)
        if result.admin2_code is not None:
            admin2_codes.add(result.admin2_code)
    has_conflict = bool(conflict_scope_keys)
    about_assignments: set[tuple[int, str, str]] = set()
    occurrence_assignments: set[tuple[int, str, str]] = set()
    points: set[tuple[float, float]] = set()
    audits: list[dict[str, Any]] = []
    for item, assignments, reason in candidates:
        published: list[dict[str, Any]] = []
        withheld_conflict_scope_keys: list[str] = []
        audit_reason = reason
        if reason == "accepted":
            relation_conflicts = conflicts_by_relation[item.relation]
            published = [
                assignment
                for assignment in assignments
                if assignment["scope_key"] not in relation_conflicts
            ]
            withheld_conflict_scope_keys = sorted(
                {
                    assignment["scope_key"]
                    for assignment in assignments
                    if assignment["scope_key"] in relation_conflicts
                }
            )
            if not published:
                audit_reason = "relation_scope_conflict"
            elif withheld_conflict_scope_keys:
                audit_reason = "accepted_partial_conflict"

        if published:
            target = (
                about_assignments
                if item.relation is SpatialRelation.ABOUT
                else occurrence_assignments
            )
            for assignment in published:
                target.add(
                    (
                        int(assignment["depth"]),
                        assignment["scope_key"],
                        assignment["derivation_revision"],
                    )
                )
            result = item.normalization
            if result.spatial_basis is not None:
                bases.add(result.spatial_basis.value)
            if result.spatial_precision is not None:
                precisions.add(result.spatial_precision.value)
            if result.latitude is not None and result.longitude is not None:
                points.add((result.longitude, result.latitude))
        audits.append(
            _audit_derivation(
                item,
                assignments,
                audit_reason,
                published_assignments=published,
                withheld_conflict_scope_keys=withheld_conflict_scope_keys,
            )
        )

    about_tokens = _assignment_tokens(about_assignments)
    occurrence_tokens = _assignment_tokens(occurrence_assignments)
    status = (
        "filterable"
        if about_tokens or occurrence_tokens
        else "conflict" if has_conflict else "audit_only"
    )
    payload: dict[str, Any] = {
        "spatial_about_scope_revision_tokens": about_tokens,
        "spatial_occurrence_scope_revision_tokens": occurrence_tokens,
        "spatial_basis": sorted(bases),
        "spatial_catalog_revision": index.catalog_revision,
        "spatial_projection_revision": derive_spatial_projection_revision(index),
        "spatial_derivation_version": SPATIAL_DERIVATION_VERSION,
        "spatial_conflict": has_conflict,
        "spatial_conflict_scope_keys": sorted(conflict_scope_keys),
        "spatial_derivation_status": status,
        "spatial_derivations": audits,
        "source_country_code": sorted(source_country_codes),
        "source_country_code_system": sorted(source_country_code_systems),
        "country_iso3": sorted(country_iso3_codes),
        "admin1_code": sorted(admin1_codes),
        "admin2_code": sorted(admin2_codes),
    }
    precision = _finest_precision(precisions)
    if precision is not None:
        payload["spatial_precision"] = precision
    ordered_points = sorted(points)
    if len(ordered_points) == 1:
        lon, lat = ordered_points[0]
        payload["geo"] = {"lon": lon, "lat": lat}
    elif ordered_points:
        payload["geo"] = [
            {"lon": lon, "lat": lat}
            for lon, lat in ordered_points
        ]
    return payload


def unavailable_spatial_payload(reason: str) -> dict[str, Any]:
    """Return an explicit, non-filterable payload for an unsupported writer lane."""

    if not reason.strip():
        raise SpatialProjectionError("unavailable reason must be non-empty")
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


def _normalize_exact_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).casefold().strip()
    return " ".join(normalized.split())


def _audit_assignments(
    result: SpatialNormalizationResult,
    index: SpatialNormalizationIndex,
) -> list[dict[str, Any]]:
    terminal = (
        result.admin2_scope_key
        or result.admin1_scope_key
        or result.country_scope_key
    )
    if terminal is None:
        return []
    assignments = index.scope_derivation_assignments(terminal)
    if (
        not result.spatial_conflict
        and result.spatial_derivation_revision is not None
        and assignments
        and assignments[-1].derivation_revision != result.spatial_derivation_revision
    ):
        raise SpatialProjectionError("terminal derivation revision does not match index")
    return [
        {
            "scope_key": assignment.scope_key,
            "derivation_revision": assignment.derivation_revision,
            "depth": assignment.depth,
        }
        for assignment in assignments
    ]


def _filter_reason(
    evidence: SpatialEvidenceV1,
    assignments: Sequence[Mapping[str, Any]],
) -> str:
    result = evidence.normalization
    if result.spatial_conflict:
        return "spatial_conflict"
    if result.status != "resolved" or not assignments:
        return "normalization_unresolved"
    if evidence.relation is SpatialRelation.ABOUT:
        if evidence.crosswalk_status is not SpatialCrosswalkStatus.UNIQUE_REVIEWED:
            return f"about_crosswalk_{evidence.crosswalk_status.value}"
        if evidence.confidence < ABOUT_CONFIDENCE_THRESHOLD:
            return "about_confidence_below_gate"
    return "accepted"


def _audit_derivation(
    evidence: SpatialEvidenceV1,
    assignments: Sequence[Mapping[str, Any]],
    reason: str,
    *,
    published_assignments: Sequence[Mapping[str, Any]],
    withheld_conflict_scope_keys: Sequence[str],
) -> dict[str, Any]:
    result = evidence.normalization
    return {
        "relation": evidence.relation.value,
        "evidence_kind": evidence.evidence_kind.value,
        "evidence_id": evidence.evidence_id,
        "confidence": evidence.confidence,
        "crosswalk_status": evidence.crosswalk_status.value,
        "normalization_status": result.status,
        "filterable": bool(published_assignments),
        "filter_reason": reason,
        "scope_assignments": [
            {
                "scope_key": assignment["scope_key"],
                "derivation_revision": assignment["derivation_revision"],
            }
            for assignment in assignments
        ],
        "published_scope_assignments": [
            {
                "scope_key": assignment["scope_key"],
                "derivation_revision": assignment["derivation_revision"],
            }
            for assignment in published_assignments
        ],
        "withheld_conflict_scope_keys": list(withheld_conflict_scope_keys),
        "basis": result.spatial_basis.value if result.spatial_basis is not None else None,
        "precision": (
            result.spatial_precision.value
            if result.spatial_precision is not None
            else None
        ),
        "raw_location": result.raw.model_dump(mode="json", exclude_none=True),
        "conflict_scope_keys": list(result.spatial_conflict_scope_keys),
        "unresolved_codes": list(result.unresolved_codes),
    }


def _assignment_tokens(assignments: set[tuple[int, str, str]]) -> list[str]:
    return [
        _encode_scope_revision_token(scope_key, revision)
        for _depth, scope_key, revision in sorted(assignments)
    ]


def _encode_scope_revision_token(scope_key: str, revision: str) -> str:
    parsed = parse_scope_key(scope_key)
    if parsed.kind is ScopeKind.WORLD:
        raise SpatialProjectionError("world is never materialized in a pair token")
    if _DERIVATION_REVISION.fullmatch(revision) is None:
        raise SpatialProjectionError("invalid derivation revision")
    token = f"{SCOPE_REVISION_TOKEN_VERSION}|{scope_key}|{revision}"
    if len(token.encode("ascii")) > MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES:
        raise SpatialProjectionError(
            "scope revision token exceeds 229 ASCII bytes"
        )
    return token


def _finest_precision(precisions: set[str]) -> str | None:
    order = {"country": 0, "admin1": 1, "admin2": 2, "point": 3}
    if not precisions:
        return None
    return max(precisions, key=order.__getitem__)


__all__ = [
    "ABOUT_CONFIDENCE_THRESHOLD",
    "ABOUT_GATE_REVISION",
    "MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES",
    "ReviewedGeoNameCrosswalk",
    "SPATIAL_DERIVATION_VERSION",
    "SpatialCrosswalkStatus",
    "SpatialEvidenceKind",
    "SpatialEvidenceV1",
    "SpatialProjectionError",
    "SpatialRelation",
    "build_reviewed_country_name_crosswalk",
    "derive_spatial_projection_revision",
    "project_spatial_payload",
    "unavailable_spatial_payload",
]
