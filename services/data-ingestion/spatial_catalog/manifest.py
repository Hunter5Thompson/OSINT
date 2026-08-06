"""Pure deterministic spatial-manifest construction and validation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictStr, StringConstraints, model_validator

from spatial_catalog.identity import parse_scope_key
from spatial_catalog.models import (
    AssetId,
    CatalogProvenance,
    CatalogRevision,
    DerivationRevision,
    ScopeKey,
    ScopeNode,
    ScopePresentation,
    StrictFrozenModel,
    validate_scope_path,
    validate_scope_presentation,
)

type ProvenanceRef = Annotated[StrictStr, StringConstraints(min_length=1, max_length=256)]


class DerivationInputs(StrictFrozenModel):
    """Only inputs that can change a materialized scope assignment."""

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


class ManifestScopeInput(StrictFrozenModel):
    scope: ScopeNode
    path: tuple[ScopeKey, ...] = Field(min_length=1, max_length=4)
    provenance: CatalogProvenance
    presentation: ScopePresentation
    provenance_ref: ProvenanceRef
    derivation_inputs: DerivationInputs
    reviewed_compatible_derivation_revisions: tuple[DerivationRevision, ...] = Field(
        default=(),
        max_length=8,
    )


class ManifestScope(StrictFrozenModel):
    scope: ScopeNode
    path: tuple[ScopeKey, ...] = Field(min_length=1, max_length=4)
    provenance: CatalogProvenance
    presentation: ScopePresentation
    provenance_ref: ProvenanceRef
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


class ManifestDraft(StrictFrozenModel):
    schema_version: Literal[1]
    boundary_policy: Literal["odin-reference-v1"]
    root_scope_key: ScopeKey
    attribution_sources_sha256: AssetId
    scopes: tuple[ManifestScopeInput, ...] = Field(min_length=1)
    assets: tuple[AssetId, ...]


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
        _validate_manifest_records(
            root_scope_key=self.root_scope_key,
            scopes=self.scopes,
            assets=self.assets,
            require_canonical_order=True,
        )
        expected = _catalog_revision(
            schema_version=self.schema_version,
            boundary_policy=self.boundary_policy,
            root_scope_key=self.root_scope_key,
            attribution_sources_sha256=self.attribution_sources_sha256,
            scopes=self.scopes,
            assets=self.assets,
        )
        if self.catalog_revision != expected:
            raise ValueError("catalog revision does not match stable manifest content")
        return self


def canonical_json_bytes(value: object) -> bytes:
    """Serialize stable JSON with sorted keys and normalized finite numbers."""

    normalized = _normalize_json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_manifest_bytes(manifest: CatalogManifest) -> bytes:
    return canonical_json_bytes(manifest)


def derive_derivation_revision(inputs: DerivationInputs) -> str:
    payload = {
        "schema_version": 1,
        "crosswalk_sha256": inputs.crosswalk_sha256,
        "scope_path": inputs.scope_path,
        "assignment_asset_ids": tuple(sorted(inputs.assignment_asset_ids)),
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"spatial-derive-v1-{digest[:12]}"


def build_manifest(
    draft: ManifestDraft,
    *,
    previous: CatalogManifest | None = None,
) -> CatalogManifest:
    """Build a canonical manifest without filesystem or clock dependencies."""

    _prevalidate_draft_lineage(draft)
    if previous is not None and _draft_matches_previous(draft, previous):
        return previous
    previous_by_scope = (
        {record.scope.key: record for record in previous.scopes} if previous is not None else {}
    )
    records = tuple(
        _build_scope_record(
            scope_input,
            previous=previous_by_scope.get(scope_input.scope.key),
            previous_catalog_revision=(
                previous.catalog_revision if previous is not None else None
            ),
        )
        for scope_input in sorted(
            draft.scopes,
            key=lambda item: (len(item.path), item.scope.key),
        )
    )
    assets = tuple(sorted(draft.assets))
    _validate_manifest_records(
        root_scope_key=draft.root_scope_key,
        scopes=records,
        assets=assets,
        require_canonical_order=True,
    )
    catalog_revision = _catalog_revision(
        schema_version=draft.schema_version,
        boundary_policy=draft.boundary_policy,
        root_scope_key=draft.root_scope_key,
        attribution_sources_sha256=draft.attribution_sources_sha256,
        scopes=records,
        assets=assets,
    )
    return CatalogManifest(
        schema_version=draft.schema_version,
        catalog_revision=catalog_revision,
        boundary_policy=draft.boundary_policy,
        root_scope_key=draft.root_scope_key,
        attribution_sources_sha256=draft.attribution_sources_sha256,
        scopes=records,
        assets=assets,
    )


def _draft_matches_previous(draft: ManifestDraft, previous: CatalogManifest) -> bool:
    if (
        draft.schema_version != previous.schema_version
        or draft.boundary_policy != previous.boundary_policy
        or draft.root_scope_key != previous.root_scope_key
        or draft.attribution_sources_sha256 != previous.attribution_sources_sha256
        or tuple(sorted(draft.assets)) != previous.assets
        or len(draft.scopes) != len(previous.scopes)
    ):
        return False

    previous_by_scope = {record.scope.key: record for record in previous.scopes}
    for scope_input in draft.scopes:
        prior = previous_by_scope.get(scope_input.scope.key)
        if prior is None:
            return False
        current = derive_derivation_revision(scope_input.derivation_inputs)
        reviewed = scope_input.reviewed_compatible_derivation_revisions
        if reviewed:
            normalized_reviewed = (current,) + tuple(
                sorted(revision for revision in set(reviewed) if revision != current)
            )
            if normalized_reviewed != prior.compatible_derivation_revisions:
                return False
        if (
            scope_input.scope != prior.scope
            or scope_input.path != prior.path
            or scope_input.provenance != prior.provenance
            or scope_input.presentation != prior.presentation
            or scope_input.provenance_ref != prior.provenance_ref
            or scope_input.derivation_inputs != prior.derivation_inputs
            or current != prior.derivation_revision
        ):
            return False
    return True


def _prevalidate_draft_lineage(draft: ManifestDraft) -> None:
    records_by_key: dict[str, ManifestScopeInput] = {}
    for record in draft.scopes:
        if record.scope.key in records_by_key:
            raise ValueError(f"duplicate manifest scope: {record.scope.key}")
        records_by_key[record.scope.key] = record
    for record in draft.scopes:
        parent_key = record.scope.parent_key
        if parent_key is not None and parent_key not in records_by_key:
            raise ValueError(f"unknown parent: {parent_key}")
    _reject_cycles(records_by_key)


def validate_manifest(manifest: CatalogManifest) -> None:
    """Revalidate a manifest at a trust boundary."""

    CatalogManifest.model_validate(manifest.model_dump(mode="json"))


def _build_scope_record(
    scope_input: ManifestScopeInput,
    *,
    previous: ManifestScope | None,
    previous_catalog_revision: str | None,
) -> ManifestScope:
    current = derive_derivation_revision(scope_input.derivation_inputs)
    reviewed = scope_input.reviewed_compatible_derivation_revisions
    if reviewed and current not in reviewed:
        raise ValueError("reviewed compatibility must include current derivation revision")

    compatible = list(reviewed or (current,))
    carry_forward_from = None
    if previous is not None and previous.derivation_revision == current:
        if previous_catalog_revision is None:
            raise ValueError("previous manifest revision context is required for carry-forward")
        carry_forward_from = previous_catalog_revision
        compatible.extend(previous.compatible_derivation_revisions)

    ordered_compatible = (current,) + tuple(
        sorted(revision for revision in set(compatible) if revision != current)
    )
    return ManifestScope(
        scope=scope_input.scope,
        path=scope_input.path,
        provenance=scope_input.provenance,
        presentation=scope_input.presentation,
        provenance_ref=scope_input.provenance_ref,
        derivation_inputs=scope_input.derivation_inputs,
        derivation_revision=current,
        compatible_derivation_revisions=ordered_compatible,
        carry_forward_from=carry_forward_from,
    )


def _validate_manifest_records(
    *,
    root_scope_key: str,
    scopes: tuple[ManifestScope, ...],
    assets: tuple[str, ...],
    require_canonical_order: bool,
) -> None:
    records_by_key: dict[str, ManifestScope] = {}
    for record in scopes:
        if record.scope.key in records_by_key:
            raise ValueError(f"duplicate manifest scope: {record.scope.key}")
        records_by_key[record.scope.key] = record

    root = records_by_key.get(root_scope_key)
    if root is None or root_scope_key != "world" or root.scope.parent_key is not None:
        raise ValueError("manifest root must be world without a parent")
    for record in scopes:
        parent_key = record.scope.parent_key
        if parent_key is not None and parent_key not in records_by_key:
            raise ValueError(f"unknown parent: {parent_key}")

    _reject_cycles(records_by_key)
    children_by_parent: dict[str, list[str]] = {}
    for record in scopes:
        if record.scope.parent_key is not None:
            children_by_parent.setdefault(record.scope.parent_key, []).append(record.scope.key)

    for record in scopes:
        expected_path = _lineage_path(record.scope.key, records_by_key)
        if record.path != expected_path:
            raise ValueError(f"complete root-to-scope path required for {record.scope.key}")
        validate_scope_path(tuple(records_by_key[key].scope for key in record.path))
        has_manifest_children = bool(children_by_parent.get(record.scope.key))
        if record.scope.children_available != has_manifest_children:
            raise ValueError(
                f"children_available is inconsistent with manifest children: {record.scope.key}"
            )
        validate_scope_presentation(record.scope, record.presentation)

    if len(assets) != len(set(assets)):
        raise ValueError("duplicate asset ID")
    asset_set = set(assets)
    for record in scopes:
        for asset_id in _referenced_asset_ids(record):
            if asset_id not in asset_set:
                raise ValueError(f"asset missing from manifest: {asset_id}")
        for asset_id in record.derivation_inputs.assignment_asset_ids:
            if asset_id not in asset_set:
                raise ValueError(f"assignment asset missing from manifest: {asset_id}")

    if require_canonical_order:
        expected_scopes = tuple(sorted(scopes, key=lambda item: (len(item.path), item.scope.key)))
        if scopes != expected_scopes:
            raise ValueError("manifest scope records are not canonically ordered")
        if assets != tuple(sorted(assets)):
            raise ValueError("manifest asset records are not canonically ordered")


def _reject_cycles(
    records_by_key: Mapping[str, ManifestScope | ManifestScopeInput],
) -> None:
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


def _referenced_asset_ids(record: ManifestScope) -> tuple[str, ...]:
    render_descriptors = (
        *record.presentation.outline_lods.values(),
        *record.presentation.children_lods.values(),
    )
    referenced = [descriptor.asset_id for descriptor in render_descriptors]
    if record.presentation.containment is not None:
        referenced.append(record.presentation.containment.asset_id)
    return tuple(referenced)


def _catalog_revision(
    *,
    schema_version: int,
    boundary_policy: str,
    root_scope_key: str,
    attribution_sources_sha256: str,
    scopes: tuple[ManifestScope, ...],
    assets: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": schema_version,
        "boundary_policy": boundary_policy,
        "root_scope_key": root_scope_key,
        "attribution_sources_sha256": attribution_sources_sha256,
        "scopes": scopes,
        "assets": assets,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"spatial-v1-{digest[:12]}"


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
