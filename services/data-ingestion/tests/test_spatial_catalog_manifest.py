from __future__ import annotations

from collections import Counter

import pytest
from pydantic import ValidationError

from spatial_catalog.manifest import (
    CatalogManifest,
    DerivationInputs,
    ManifestDraft,
    ManifestScopeInput,
    build_manifest,
    canonical_json_bytes,
    canonical_manifest_bytes,
)
from spatial_catalog.models import (
    CONTRACT_DOC_OWNERS,
    CatalogProvenance,
    ContainmentDescriptor,
    GeometryDescriptor,
    Lod,
    ScopeKind,
    ScopeNode,
    ScopePresentation,
)

CROSSWALK_HASH = "d393f5026dedd808cf2b517b574f16c311591a18891d0de6d738e327dbf4a369"
WORLD_PACK_ID = "a" * 64
ATTRIBUTION_SOURCES_HASH = "e" * 64


def _provenance() -> CatalogProvenance:
    return CatalogProvenance(
        boundary_policy="odin-reference-v1",
        representation_id="natural-earth-110m-admin0",
        dispute_status="none",
        source_id="natural-earth-admin0",
        source_release="5.1.2+f1890d9f152c",
        license_id="public-domain",
        attribution="Natural Earth",
    )


def _node(
    key: str,
    kind: ScopeKind,
    parent_key: str | None,
    *,
    children_available: bool,
    label: str | None = None,
) -> ScopeNode:
    return ScopeNode(
        key=key,
        kind=kind,
        label=label or key,
        short_label=label or key,
        parent_key=parent_key,
        children_available=children_available,
        presentation="boundary",
    )


def _scope_input(
    scope: ScopeNode,
    path: tuple[str, ...],
    *,
    presentation: ScopePresentation | None = None,
    assignment_asset_ids: tuple[str, ...] = (),
) -> ManifestScopeInput:
    return ManifestScopeInput(
        scope=scope,
        path=path,
        provenance=_provenance(),
        presentation=presentation or ScopePresentation(),
        provenance_ref="natural-earth-admin0",
        derivation_inputs=DerivationInputs(
            crosswalk_sha256=CROSSWALK_HASH,
            scope_path=path,
            assignment_asset_ids=assignment_asset_ids,
        ),
    )


def _draft(*, world_label: str = "World", reverse: bool = False) -> ManifestDraft:
    world_pack = GeometryDescriptor(
        asset_id=WORLD_PACK_ID,
        media_type="application/vnd.odin.boundary-pack+json;v=1",
        byte_length=1000,
        vertex_count=100,
        feature_count=1,
        role="render",
        lod=Lod.OVERVIEW,
    )
    world = _scope_input(
        _node("world", ScopeKind.WORLD, None, children_available=True, label=world_label),
        ("world",),
        presentation=ScopePresentation(
            preferred_lod=Lod.OVERVIEW,
            children_lods={Lod.OVERVIEW: world_pack},
        ),
    )
    ukraine = _scope_input(
        _node("country:UKR", ScopeKind.COUNTRY, "world", children_available=False),
        ("world", "country:UKR"),
    )
    scopes = (ukraine, world) if reverse else (world, ukraine)
    return ManifestDraft(
        schema_version=1,
        boundary_policy="odin-reference-v1",
        root_scope_key="world",
        attribution_sources_sha256=ATTRIBUTION_SOURCES_HASH,
        scopes=scopes,
        assets=(WORLD_PACK_ID,),
    )


def test_manifest_rejects_unknown_parent() -> None:
    draft = _draft()
    orphan = _scope_input(
        _node(
            "admin1:iso3166-2:UA-14",
            ScopeKind.ADMIN1,
            "country:POL",
            children_available=False,
        ),
        ("world", "country:POL", "admin1:iso3166-2:UA-14"),
    )
    with pytest.raises(ValueError, match="unknown parent"):
        build_manifest(draft.model_copy(update={"scopes": (*draft.scopes, orphan)}))


def test_manifest_rejects_incomplete_path() -> None:
    draft = _draft()
    ukraine = draft.scopes[1]
    broken = ukraine.model_copy(
        update={
            "path": ("country:UKR",),
            "derivation_inputs": ukraine.derivation_inputs.model_copy(
                update={"scope_path": ("country:UKR",)}
            ),
        }
    )
    with pytest.raises(ValueError, match="complete root-to-scope path"):
        build_manifest(draft.model_copy(update={"scopes": (draft.scopes[0], broken)}))


def test_manifest_rejects_cycles() -> None:
    world = _node("world", ScopeKind.WORLD, None, children_available=True)
    country = ScopeNode.model_construct(
        key="country:UKR",
        kind=ScopeKind.COUNTRY,
        label="Ukraine",
        short_label="Ukraine",
        parent_key="admin1:iso3166-2:UA-14",
        children_available=True,
        presentation="boundary",
    )
    admin1 = ScopeNode.model_construct(
        key="admin1:iso3166-2:UA-14",
        kind=ScopeKind.ADMIN1,
        label="Donetsk",
        short_label="Donetsk",
        parent_key="country:UKR",
        children_available=True,
        presentation="boundary",
    )
    def unsafe_scope_input(scope: ScopeNode, path: tuple[str, ...]) -> ManifestScopeInput:
        return ManifestScopeInput.model_construct(
            scope=scope,
            path=path,
            provenance=_provenance(),
            presentation=ScopePresentation(),
            provenance_ref="natural-earth-admin0",
            derivation_inputs=DerivationInputs(
                crosswalk_sha256=CROSSWALK_HASH,
                scope_path=path,
            ),
            reviewed_compatible_derivation_revisions=(),
        )

    scopes = (
        unsafe_scope_input(world, ("world",)),
        unsafe_scope_input(country, ("world", "country:UKR")),
        unsafe_scope_input(admin1, ("world", "country:UKR", admin1.key)),
    )
    draft = ManifestDraft.model_construct(
        schema_version=1,
        boundary_policy="odin-reference-v1",
        root_scope_key="world",
        attribution_sources_sha256=ATTRIBUTION_SOURCES_HASH,
        scopes=scopes,
        assets=(),
    )
    with pytest.raises(ValueError, match="cycle"):
        build_manifest(draft)


def test_manifest_rejects_inconsistent_children_available() -> None:
    draft = _draft()
    world = draft.scopes[0]
    no_children = world.scope.model_copy(update={"children_available": False})
    broken_world = world.model_copy(
        update={"scope": no_children, "presentation": ScopePresentation()}
    )
    with pytest.raises(ValueError, match="children_available is inconsistent"):
        build_manifest(draft.model_copy(update={"scopes": (broken_world, draft.scopes[1])}))


def test_manifest_rejects_missing_and_duplicate_assets() -> None:
    with pytest.raises(ValueError, match="asset missing from manifest"):
        build_manifest(_draft().model_copy(update={"assets": ()}))
    with pytest.raises(ValueError, match="duplicate asset ID"):
        build_manifest(_draft().model_copy(update={"assets": (WORLD_PACK_ID, WORLD_PACK_ID)}))


def test_catalog_only_change_carries_forward_derivation_revision() -> None:
    first = build_manifest(_draft(world_label="World"))
    second = build_manifest(_draft(world_label="Earth"), previous=first)
    first_world = next(record for record in first.scopes if record.scope.key == "world")
    second_world = next(record for record in second.scopes if record.scope.key == "world")

    assert first.catalog_revision != second.catalog_revision
    assert first_world.derivation_revision == second_world.derivation_revision
    assert second_world.carry_forward_from == first.catalog_revision
    assert second_world.compatible_derivation_revisions == (
        second_world.derivation_revision,
    )


def test_identical_rebuild_with_previous_is_byte_identical() -> None:
    first = build_manifest(_draft())
    second = build_manifest(_draft(reverse=True), previous=first)

    assert second.catalog_revision == first.catalog_revision
    assert canonical_manifest_bytes(second) == canonical_manifest_bytes(first)


def test_manifest_rejects_incompatible_declared_derivation() -> None:
    manifest = build_manifest(_draft())
    payload = manifest.model_dump(mode="json")
    payload["scopes"][0]["derivation_revision"] = "spatial-derive-v1-ffffffffffff"
    with pytest.raises(ValidationError, match="derivation revision does not match inputs"):
        CatalogManifest.model_validate(payload)


def test_manifest_record_and_key_order_are_byte_deterministic() -> None:
    first = build_manifest(_draft(reverse=False))
    second = build_manifest(_draft(reverse=True))

    assert first.catalog_revision == second.catalog_revision
    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)
    assert canonical_json_bytes({"z": 1.0, "a": {"y": -0.0, "x": 2}}) == (
        b'{"a":{"x":2,"y":0},"z":1}'
    )


def test_manifest_revision_inputs_forbid_volatile_timestamp() -> None:
    payload = _draft().model_dump(mode="json")
    payload["built_at"] = "2026-08-01T12:00:00Z"
    with pytest.raises(ValidationError, match="built_at"):
        ManifestDraft.model_validate(payload)


def test_shared_contract_symbols_have_one_normative_doc_owner() -> None:
    counts = Counter(symbol for symbol, _ in CONTRACT_DOC_OWNERS)
    assert counts == {
        "CatalogRevision": 1,
        "DerivationRevision": 1,
        "ScopeKey": 1,
        "ScopeKind": 1,
    }
    assert all(
        owner.endswith("02-scope-identity-and-boundary-policy.md")
        for _, owner in CONTRACT_DOC_OWNERS
    )


CONTAINMENT_A = "c" * 64
CONTAINMENT_B = "d" * 64


def _draft_with_ukraine(
    *, containment_asset: str | None, crosswalk: str = CROSSWALK_HASH,
) -> ManifestDraft:
    base = _draft()
    world = next(s for s in base.scopes if s.scope.key == "world")
    presentation = ScopePresentation()
    if containment_asset is not None:
        presentation = ScopePresentation(
            containment=ContainmentDescriptor(
                asset_id=containment_asset,
                media_type="application/vnd.odin.boundary+json;v=1",
                byte_length=100,
                vertex_count=10,
                role="containment",
                max_error_m=0,
            ),
        )
    path = ("world", "country:UKR")
    ukraine = ManifestScopeInput(
        scope=_node("country:UKR", ScopeKind.COUNTRY, "world", children_available=False),
        path=path,
        provenance=_provenance(),
        presentation=presentation,
        provenance_ref="natural-earth-admin0",
        derivation_inputs=DerivationInputs(
            crosswalk_sha256=crosswalk,
            scope_path=path,
            assignment_asset_ids=(containment_asset,) if containment_asset else (),
        ),
    )
    assets = (WORLD_PACK_ID,) + ((containment_asset,) if containment_asset else ())
    return base.model_copy(update={"scopes": (world, ukraine), "assets": assets})


def _ukraine(manifest: CatalogManifest):
    return next(s for s in manifest.scopes if s.scope.key == "country:UKR")


def test_adding_containment_invalidates_prior_coordinate_checks() -> None:
    """A source code may conflict with coordinates only after coverage expands."""
    code_only = build_manifest(_draft_with_ukraine(containment_asset=None))
    extended = build_manifest(
        _draft_with_ukraine(containment_asset=CONTAINMENT_A),
        previous=code_only,
    )

    before, after = _ukraine(code_only), _ukraine(extended)
    assert after.derivation_revision != before.derivation_revision
    assert before.derivation_revision not in after.compatible_derivation_revisions
    assert after.compatible_derivation_revisions == (after.derivation_revision,)
    assert after.carry_forward_from is None


def test_changed_containment_geometry_is_not_silently_compatible() -> None:
    first = build_manifest(_draft_with_ukraine(containment_asset=CONTAINMENT_A))
    second = build_manifest(
        _draft_with_ukraine(containment_asset=CONTAINMENT_B), previous=first,
    )

    assert _ukraine(first).derivation_revision not in (
        _ukraine(second).compatible_derivation_revisions
    )


def test_containment_extension_with_changed_crosswalk_is_not_compatible() -> None:
    code_only = build_manifest(_draft_with_ukraine(containment_asset=None))
    extended = build_manifest(
        _draft_with_ukraine(containment_asset=CONTAINMENT_A, crosswalk="f" * 64),
        previous=code_only,
    )

    assert _ukraine(code_only).derivation_revision not in (
        _ukraine(extended).compatible_derivation_revisions
    )


def test_neighbor_containment_changes_invalidate_an_unchanged_country() -> None:
    draft = _draft_with_ukraine(containment_asset=CONTAINMENT_A)
    poland = _scope_input(
        _node("country:POL", ScopeKind.COUNTRY, "world", children_available=False),
        ("world", "country:POL"),
    )
    before = build_manifest(draft.model_copy(update={"scopes": (*draft.scopes, poland)}))
    changed = _draft_with_ukraine(containment_asset=CONTAINMENT_B)
    after = build_manifest(
        changed.model_copy(update={"scopes": (*changed.scopes, poland)}),
        previous=before,
    )
    old = next(s for s in before.scopes if s.scope.key == "country:POL")
    new = next(s for s in after.scopes if s.scope.key == "country:POL")
    assert old.derivation_revision != new.derivation_revision
    assert old.derivation_revision not in new.compatible_derivation_revisions


def test_legacy_manifest_bytes_are_preserved_when_reading() -> None:
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "backend/data/spatial/catalogs/spatial-v1-0180e188358c/manifest.json"
    )
    raw = path.read_bytes()
    assert canonical_manifest_bytes(CatalogManifest.model_validate_json(raw)) == raw
