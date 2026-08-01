from __future__ import annotations

from collections.abc import Iterable

import pytest
from pydantic import TypeAdapter, ValidationError

from spatial_catalog.models import (
    AssetId,
    CatalogRevision,
    DerivationCompatibility,
    DerivationRevision,
    GeometryDescriptor,
    Lod,
    ScopeKind,
    ScopeNode,
    ScopePresentation,
    validate_scope_path,
    validate_scope_presentation,
)


def _revision(prefix: str, value: int) -> str:
    return f"{prefix}{value:012x}"


@pytest.mark.parametrize(
    ("adapter", "accepted"),
    [
        (TypeAdapter(CatalogRevision), "spatial-v1-001122334455"),
        (TypeAdapter(CatalogRevision), f"spatial-v12-{'a' * 64}"),
        (TypeAdapter(DerivationRevision), "spatial-derive-v1-001122334455"),
        (TypeAdapter(DerivationRevision), f"spatial-derive-v12-{'f' * 64}"),
        (TypeAdapter(AssetId), "0" * 64),
        (TypeAdapter(AssetId), "abcdef0123456789" * 4),
    ],
)
def test_revision_and_asset_contracts_accept_canonical_values(
    adapter: TypeAdapter[str], accepted: str
) -> None:
    assert adapter.validate_python(accepted) == accepted


@pytest.mark.parametrize(
    ("adapter", "rejected"),
    [
        (TypeAdapter(CatalogRevision), "spatial-v1-placeholder"),
        (TypeAdapter(CatalogRevision), "spatial-v1-ABCDEF123456"),
        (TypeAdapter(CatalogRevision), "spatial-v1-00112233445"),
        (TypeAdapter(DerivationRevision), "spatial-v1-001122334455"),
        (TypeAdapter(DerivationRevision), "spatial-derive-v1-xyzxyzxyzxyz"),
        (TypeAdapter(AssetId), "f" * 63),
        (TypeAdapter(AssetId), "F" * 64),
        (TypeAdapter(AssetId), "g" * 64),
    ],
)
def test_revision_and_asset_contracts_reject_malformed_values(
    adapter: TypeAdapter[str], rejected: str
) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(rejected)


def _node(
    key: str,
    kind: ScopeKind,
    parent_key: str | None,
    *,
    children_available: bool = False,
) -> ScopeNode:
    return ScopeNode(
        key=key,
        kind=kind,
        label=key,
        short_label=key,
        parent_key=parent_key,
        children_available=children_available,
        presentation="boundary",
    )


def test_scope_node_enforces_kind_and_parent_relation() -> None:
    world = _node("world", ScopeKind.WORLD, None, children_available=True)
    ukraine = _node("country:UKR", ScopeKind.COUNTRY, "world", children_available=True)
    donetsk = _node("admin1:iso3166-2:UA-14", ScopeKind.ADMIN1, "country:UKR")

    validate_scope_path((world, ukraine, donetsk))

    with pytest.raises(ValidationError, match="world scope must not have a parent"):
        _node("world", ScopeKind.WORLD, "world")
    with pytest.raises(ValidationError, match="country scope must have a world parent"):
        _node("country:UKR", ScopeKind.COUNTRY, "country:POL")
    with pytest.raises(ValidationError, match="key kind does not match"):
        _node("country:UKR", ScopeKind.ADMIN1, "world")


def test_scope_path_rejects_incomplete_or_excessive_lineage() -> None:
    world = _node("world", ScopeKind.WORLD, None, children_available=True)
    ukraine = _node("country:UKR", ScopeKind.COUNTRY, "world", children_available=True)
    donetsk = _node("admin1:iso3166-2:UA-14", ScopeKind.ADMIN1, "country:UKR")
    district = _node("admin2:gbopen:UA.14.1_1", ScopeKind.ADMIN2, donetsk.key)

    with pytest.raises(ValueError, match="path must start at world"):
        validate_scope_path((ukraine,))
    with pytest.raises(ValueError, match="path is not contiguous"):
        validate_scope_path((world, donetsk))
    with pytest.raises(ValueError, match="maximum lineage depth is 4"):
        validate_scope_path((world, ukraine, donetsk, district, district))


def _asset(lod: Lod) -> GeometryDescriptor:
    return GeometryDescriptor(
        asset_id="a" * 64,
        media_type="application/vnd.odin.boundary-pack+json;v=1",
        byte_length=1024,
        vertex_count=64,
        feature_count=4,
        role="render",
        lod=lod,
    )


def test_drillable_scope_requires_preferred_child_lod() -> None:
    scope = _node("country:UKR", ScopeKind.COUNTRY, "world", children_available=True)

    with pytest.raises(ValueError, match="preferred_lod must name an available children LOD"):
        validate_scope_presentation(
            scope,
            ScopePresentation(preferred_lod=Lod.REGIONAL, children_lods={}),
        )

    presentation = ScopePresentation(
        preferred_lod=Lod.REGIONAL,
        children_lods={Lod.REGIONAL: _asset(Lod.REGIONAL)},
    )
    validate_scope_presentation(scope, presentation)


def test_non_drillable_scope_rejects_child_geometry() -> None:
    scope = _node("country:POL", ScopeKind.COUNTRY, "world")

    with pytest.raises(ValueError, match="non-drillable scope cannot publish children LODs"):
        validate_scope_presentation(
            scope,
            ScopePresentation(
                preferred_lod=Lod.REGIONAL,
                children_lods={Lod.REGIONAL: _asset(Lod.REGIONAL)},
            ),
        )


def test_geometry_descriptor_rejects_lod_key_mismatch() -> None:
    scope = _node("country:UKR", ScopeKind.COUNTRY, "world", children_available=True)
    presentation = ScopePresentation(
        preferred_lod=Lod.REGIONAL,
        children_lods={Lod.REGIONAL: _asset(Lod.OVERVIEW)},
    )

    with pytest.raises(ValueError, match="descriptor LOD must match its map key"):
        validate_scope_presentation(scope, presentation)


def test_derivation_compatibility_rejects_ninth_revision_instead_of_truncating() -> None:
    current = _revision("spatial-derive-v1-", 0)
    revisions: Iterable[str] = (
        _revision("spatial-derive-v1-", value) for value in range(9)
    )

    with pytest.raises(ValidationError):
        DerivationCompatibility(
            catalog_revision="spatial-v1-001122334455",
            current=current,
            compatible=tuple(revisions),
        )


def test_derivation_compatibility_requires_current_and_unique_revisions() -> None:
    current = _revision("spatial-derive-v1-", 1)
    other = _revision("spatial-derive-v1-", 2)

    with pytest.raises(ValidationError, match="current derivation revision must be compatible"):
        DerivationCompatibility(
            catalog_revision="spatial-v1-001122334455",
            current=current,
            compatible=(other,),
        )
    with pytest.raises(ValidationError, match="compatible derivation revisions must be unique"):
        DerivationCompatibility(
            catalog_revision="spatial-v1-001122334455",
            current=current,
            compatible=(current, current),
        )


def test_public_models_are_frozen_and_strict() -> None:
    node = _node("world", ScopeKind.WORLD, None)
    with pytest.raises(ValidationError):
        node.label = "Other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        GeometryDescriptor(
            asset_id="a" * 64,
            media_type="application/vnd.odin.boundary+json;v=1",
            byte_length="1024",
            vertex_count=64,
            role="render",
            lod=Lod.OVERVIEW,
        )
