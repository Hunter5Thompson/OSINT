"""Strict source lock, offline hash verification, and catalog-plan policy."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field, StrictBool, StrictStr, StringConstraints, model_validator

from spatial_catalog.identity import CountryCrosswalk, CountryCrosswalkRecord, parse_scope_key
from spatial_catalog.models import AssetId, ScopeKey, ScopeKind, StrictFrozenModel

DEFAULT_SOURCE_LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "backend" / "data" / "spatial" / "source-lock.json"
)
CATALOG_PLAN_PATH = Path(__file__).resolve().parent / "catalog-plan.json"

_PLACEHOLDER_MARKERS = ("placeholder", "<pinned", "latest")
_GITHUB_COMMIT = re.compile(r"^[a-f0-9]{40}$")
_NPM_MAPSHAPER_TARBALL = re.compile(r"^/mapshaper/-/mapshaper-([0-9]+\.[0-9]+\.[0-9]+)\.tgz$")

type SourceIdentifier = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9._-]+$"),
]
type SourceRelease = Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
type Attribution = Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]
type LicenseId = Literal[
    "public-domain",
    "CC-BY-4.0",
    "ODbL-1.0",
    "LicenseRef-ODIN-Reviewed-Crosswalk",
    "MPL-2.0",
]


class SourceHashMismatchError(ValueError):
    """Bytes do not match the reviewed lock entry."""


class SourceFetcher(Protocol):
    """Network-capable fetch seam implemented only by the Plan 00B CLI."""

    def __call__(self, source: LockedSource, destination: Path) -> Path: ...


class LockedSource(StrictFrozenModel):
    source_id: SourceIdentifier
    release: SourceRelease
    url: StrictStr
    sha256: AssetId
    license_id: LicenseId
    attribution: Attribution

    @model_validator(mode="after")
    def validate_release_and_url(self) -> LockedSource:
        release_lower = self.release.lower()
        if any(marker in release_lower for marker in _PLACEHOLDER_MARKERS):
            raise ValueError("release must be concrete and pinned")
        if not _is_immutable_source_url(self.url, release=self.release):
            raise ValueError("immutable source URL is required")
        return self


class SourceLock(StrictFrozenModel):
    schema_version: Literal[1]
    sources: tuple[LockedSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_source_ids(self) -> SourceLock:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate source ID")
        return self

    def source(self, source_id: str) -> LockedSource:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise KeyError(f"unknown locked source: {source_id}")


class CatalogPlanEntry(StrictFrozenModel):
    scope_key: ScopeKey
    activation: Literal["active", "deferred", "unsupported"]
    max_level: Literal["country", "admin1", "admin2"]
    representation_source_id: SourceIdentifier
    children_source_id: SourceIdentifier | None
    representation_id: SourceIdentifier
    client_strict_containment_required: StrictBool

    @model_validator(mode="after")
    def validate_scope_and_sources(self) -> CatalogPlanEntry:
        parsed = parse_scope_key(self.scope_key)
        if parsed.canonical != self.scope_key or parsed.kind is not ScopeKind.COUNTRY:
            raise ValueError("catalog plan entries require canonical country scope keys")
        if self.max_level == "country" and self.children_source_id is not None:
            raise ValueError("country-only plan entry must not declare a children source")
        if self.max_level != "country" and self.children_source_id is None:
            raise ValueError("drillable plan entry requires a children source")
        return self

    @property
    def children_available(self) -> bool:
        return self.activation == "active" and self.max_level != "country"


class ReviewedNonScopeFeature(StrictFrozenModel):
    record_id: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    source_system: SourceIdentifier
    source_code: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    non_scope_reason: Literal["disputed-territory-context"]
    representation_id: SourceIdentifier


class CatalogPlan(StrictFrozenModel):
    schema_version: Literal[1]
    boundary_policy: Literal["odin-reference-v1"]
    scopes: tuple[CatalogPlanEntry, ...] = Field(min_length=1)
    non_scope_features: tuple[ReviewedNonScopeFeature, ...]

    @model_validator(mode="after")
    def validate_unique_records(self) -> CatalogPlan:
        scope_keys = [entry.scope_key for entry in self.scopes]
        if len(scope_keys) != len(set(scope_keys)):
            raise ValueError("duplicate catalog-plan scope")
        record_ids = [feature.record_id for feature in self.non_scope_features]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("duplicate catalog-plan non-scope record")
        return self


def _is_immutable_source_url(url: str, *, release: str) -> bool:
    if url.startswith("repo:"):
        relative = url.removeprefix("repo:")
        path = PurePosixPath(relative)
        return bool(relative) and not path.is_absolute() and ".." not in path.parts

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    lowered_path = parsed.path.lower()
    if "/current/" in lowered_path or "/latest/" in lowered_path:
        return False

    parts = tuple(part for part in parsed.path.split("/") if part)
    if parsed.hostname == "raw.githubusercontent.com":
        return len(parts) >= 4 and _GITHUB_COMMIT.fullmatch(parts[2]) is not None
    if parsed.hostname == "github.com":
        return (
            len(parts) >= 5
            and parts[2] == "raw"
            and _GITHUB_COMMIT.fullmatch(parts[3]) is not None
        )
    if parsed.hostname == "registry.npmjs.org":
        match = _NPM_MAPSHAPER_TARBALL.fullmatch(parsed.path)
        return match is not None and match.group(1) == release
    return False


def load_source_lock(path: Path = DEFAULT_SOURCE_LOCK_PATH) -> SourceLock:
    return SourceLock.model_validate_json(path.read_text(encoding="utf-8"))


def verify_source_bytes(source: LockedSource, payload: bytes) -> None:
    actual = hashlib.sha256(payload).hexdigest()
    if actual != source.sha256:
        raise SourceHashMismatchError(
            f"SOURCE_HASH_MISMATCH: {source.source_id}: expected {source.sha256}, got {actual}"
        )


def parse_verified_source[ParsedSource](
    source: LockedSource,
    payload: bytes,
    parser: Callable[[bytes], ParsedSource],
) -> ParsedSource:
    """Verify the content hash before invoking any format parser."""

    verify_source_bytes(source, payload)
    return parser(payload)


def read_verified_repo_source(source: LockedSource, *, repo_root: Path) -> bytes:
    if not source.url.startswith("repo:"):
        raise ValueError(f"source is not repository-local: {source.source_id}")
    root = repo_root.resolve()
    candidate = (root / source.url.removeprefix("repo:")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("repository source escapes repository root") from exc
    payload = candidate.read_bytes()
    verify_source_bytes(source, payload)
    return payload


def load_catalog_plan(
    path: Path = CATALOG_PLAN_PATH,
    *,
    crosswalk: CountryCrosswalk,
    source_lock: SourceLock,
) -> CatalogPlan:
    plan = CatalogPlan.model_validate_json(path.read_text(encoding="utf-8"))
    validate_catalog_plan(plan, crosswalk=crosswalk, source_lock=source_lock)
    return plan


def validate_catalog_plan(
    plan: CatalogPlan,
    *,
    crosswalk: CountryCrosswalk,
    source_lock: SourceLock,
) -> None:
    records_by_scope = {
        record.scope_key: record for record in crosswalk.records if record.scope_key is not None
    }
    plan_scope_keys = {entry.scope_key for entry in plan.scopes}
    unknown = sorted(plan_scope_keys - records_by_scope.keys())
    if unknown:
        raise ValueError(f"unknown plan scope: {unknown[0]}")
    missing = sorted(records_by_scope.keys() - plan_scope_keys)
    if missing:
        raise ValueError(f"explicit scope coverage missing: {missing[0]}")

    locked_ids = {source.source_id for source in source_lock.sources}
    for entry in plan.scopes:
        _validate_plan_entry(entry, record=records_by_scope[entry.scope_key])
        referenced_sources = {entry.representation_source_id}
        if entry.children_source_id is not None:
            referenced_sources.add(entry.children_source_id)
        unknown_sources = sorted(referenced_sources - locked_ids)
        if unknown_sources:
            raise ValueError(f"unknown locked source in catalog plan: {unknown_sources[0]}")

    expected_non_scope = {
        record.record_id: record
        for record in crosswalk.records
        if record.disposition == "non_scope_feature"
    }
    actual_non_scope = {feature.record_id: feature for feature in plan.non_scope_features}
    if set(actual_non_scope) != set(expected_non_scope):
        raise ValueError("explicit non-scope coverage does not match crosswalk")
    for record_id, feature in actual_non_scope.items():
        record = expected_non_scope[record_id]
        if (
            feature.source_system != record.source_system
            or feature.source_code != record.source_code
            or feature.non_scope_reason != record.non_scope_reason
            or feature.representation_id != record.representation_id
        ):
            raise ValueError(f"unreviewed special geometry: {record_id}")


def _validate_plan_entry(
    entry: CatalogPlanEntry,
    *,
    record: CountryCrosswalkRecord,
) -> None:
    if entry.representation_id != record.representation_id:
        raise ValueError(f"representation mismatch for plan scope: {entry.scope_key}")
