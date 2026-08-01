from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spatial_catalog.emit import (
    AssetBudgetError,
    AttributionRecord,
    ContextPackFeature,
    PublicationError,
    ScopePackFeature,
    emit_attribution,
    emit_boundary_pack,
    emit_render_boundary,
    publish_revision,
)
from spatial_catalog.lod import BoundaryFeature
from spatial_catalog.manifest import (
    DerivationInputs,
    ManifestDraft,
    ManifestScopeInput,
    build_manifest,
)
from spatial_catalog.models import (
    CatalogProvenance,
    Lod,
    ScopeKind,
    ScopeNode,
    ScopePresentation,
)
from spatial_catalog.normalize import normalize_geometry

FIXTURES = Path(__file__).parent / "fixtures" / "spatial_catalog"
CROSSWALK_HASH = "d393f5026dedd808cf2b517b574f16c311591a18891d0de6d738e327dbf4a369"
def _shared_border_features() -> tuple[BoundaryFeature, ...]:
    payload = json.loads((FIXTURES / "shared_border.geojson").read_text(encoding="utf-8"))
    return tuple(
        BoundaryFeature(
            feature_id=feature["id"],
            geometry=normalize_geometry(feature["geometry"]),
        )
        for feature in payload["features"]
    )


def test_boundary_geometry_uses_exact_wire_schema_and_hashes_written_bytes() -> None:
    geometry = normalize_geometry(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
    )

    emitted = emit_render_boundary(geometry, lod=Lod.OVERVIEW)

    assert json.loads(emitted.content) == {
        "schema_version": 1,
        "geometry_type": "MultiPolygon",
        "polygons": [[[[0, 0], [1, 0], [0, 1], [0, 0]]]],
    }
    assert emitted.asset_id == hashlib.sha256(emitted.content).hexdigest()
    assert emitted.descriptor.asset_id == emitted.asset_id
    assert emitted.descriptor.byte_length == len(emitted.content)
    assert emitted.descriptor.vertex_count == 4
    assert emitted.counts.ring_count == 1
    assert emitted.counts.max_ring_vertices == 4


def test_pack_strips_source_properties_and_enforces_scope_or_context_identity() -> None:
    left, right = _shared_border_features()
    emitted = emit_boundary_pack(
        parent_scope_key="world",
        lod=Lod.OVERVIEW,
        allowed_child_scope_keys={"country:UKR"},
        features=(
            ContextPackFeature(
                feature_id="natural-earth-admin0:N. Cyprus",
                label="Northern Cyprus",
                non_scope_reason="disputed-territory-context",
                geometry=right.geometry,
            ),
            ScopePackFeature(
                scope_key="country:UKR",
                label="Ukraine",
                geometry=left.geometry,
            ),
        ),
    )

    payload = json.loads(emitted.content)
    assert set(payload) == {"schema_version", "parent_scope_key", "features"}
    assert "catalog_revision" not in emitted.content.decode("utf-8")
    assert payload["features"] == [
        {
            "feature_id": "natural-earth-admin0:N. Cyprus",
            "geometry": right.geometry.to_wire(),
            "kind": "context",
            "label": "Northern Cyprus",
            "non_scope_reason": "disputed-territory-context",
        },
        {
            "geometry": left.geometry.to_wire(),
            "kind": "scope",
            "label": "Ukraine",
            "scope_key": "country:UKR",
        },
    ]
    serialized = emitted.content.decode("utf-8")
    assert "properties" not in serialized
    assert "url" not in serialized.lower()

    with pytest.raises(ValueError, match="INVALID_SCOPE_KEY"):
        ScopePackFeature(
            scope_key="country:Ukraine",
            label="Ukraine",
            geometry=left.geometry,
        )
    with pytest.raises(AssetBudgetError, match="DIRECT_MANIFEST_CHILD_REQUIRED"):
        emit_boundary_pack(
            parent_scope_key="world",
            lod=Lod.OVERVIEW,
            allowed_child_scope_keys={"country:POL"},
            features=(
                ScopePackFeature(
                    scope_key="country:UKR",
                    label="Ukraine",
                    geometry=left.geometry,
                ),
            ),
        )
    with pytest.raises(ValueError, match="invalid non_scope_reason"):
        ContextPackFeature(
            feature_id="context",
            label="Context",
            non_scope_reason="free text",
            geometry=right.geometry,
        )


def test_pack_counts_expanded_shared_borders_and_closure_from_one_wire_walk() -> None:
    left, right = _shared_border_features()
    emitted = emit_boundary_pack(
        parent_scope_key="world",
        lod=Lod.OVERVIEW,
        allowed_child_scope_keys={"country:POL", "country:UKR"},
        features=(
            ScopePackFeature("country:UKR", "Ukraine", right.geometry),
            ScopePackFeature("country:POL", "Poland", left.geometry),
        ),
    )

    assert emitted.counts.vertex_count == 12
    assert emitted.counts.ring_count == 2
    assert emitted.descriptor.vertex_count == emitted.counts.vertex_count
    assert emitted.descriptor.feature_count == 2
    assert emitted.descriptor.byte_length == emitted.counts.byte_length
    assert emitted.descriptor.byte_length == len(emitted.content)


def test_pack_feature_order_and_bytes_are_stable() -> None:
    left, right = _shared_border_features()
    poland = ScopePackFeature("country:POL", "Poland", left.geometry)
    ukraine = ScopePackFeature("country:UKR", "Ukraine", right.geometry)

    first = emit_boundary_pack(
        parent_scope_key="world",
        lod=Lod.OVERVIEW,
        allowed_child_scope_keys={"country:POL", "country:UKR"},
        features=(ukraine, poland),
    )
    second = emit_boundary_pack(
        parent_scope_key="world",
        lod=Lod.OVERVIEW,
        allowed_child_scope_keys={"country:UKR", "country:POL"},
        features=(poland, ukraine),
    )

    assert first.content == second.content
    assert first.asset_id == second.asset_id
    assert [feature["scope_key"] for feature in json.loads(first.content)["features"]] == [
        "country:POL",
        "country:UKR",
    ]


def test_asset_budget_counts_ring_closure_not_unique_coordinates() -> None:
    geometry = normalize_geometry(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
    )

    with pytest.raises(AssetBudgetError, match="ASSET_VERTEX_BUDGET"):
        emit_render_boundary(
            geometry,
            lod=Lod.OVERVIEW,
            max_vertices=3,
        )


def test_attribution_and_atomic_revision_publication_are_deterministic(tmp_path: Path) -> None:
    geometry = normalize_geometry(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
    )
    asset = emit_render_boundary(geometry, lod=Lod.OVERVIEW)
    world = ScopeNode(
        key="world",
        kind=ScopeKind.WORLD,
        label="World",
        short_label="World",
        parent_key=None,
        children_available=False,
        presentation="boundary",
    )
    manifest = build_manifest(
        ManifestDraft(
            schema_version=1,
            boundary_policy="odin-reference-v1",
            root_scope_key="world",
            scopes=(
                ManifestScopeInput(
                    scope=world,
                    path=("world",),
                    provenance=CatalogProvenance(
                        boundary_policy="odin-reference-v1",
                        representation_id="natural-earth-110m-admin0",
                        dispute_status="none",
                        source_id="natural-earth-admin0",
                        source_release="5.1.2+f1890d9f152c",
                        license_id="public-domain",
                        attribution="Natural Earth",
                    ),
                    presentation=ScopePresentation(),
                    provenance_ref="natural-earth-admin0",
                    derivation_inputs=DerivationInputs(
                        crosswalk_sha256=CROSSWALK_HASH,
                        scope_path=("world",),
                    ),
                ),
            ),
            assets=(asset.asset_id,),
        )
    )
    attribution = emit_attribution(
        manifest.catalog_revision,
        (
            AttributionRecord("natural-earth-admin0", "public-domain", "Natural Earth"),
            AttributionRecord("mapshaper", "MPL-2.0", "Mapshaper by Matthew Bloch"),
        ),
    )
    output_root = tmp_path / "catalogs"

    first = publish_revision(
        output_root,
        manifest=manifest,
        assets=(asset,),
        attribution=attribution,
    )
    second = publish_revision(
        output_root,
        manifest=manifest,
        assets=(asset,),
        attribution=attribution,
    )

    assert first == second == output_root / manifest.catalog_revision
    assert (first / "assets" / f"{asset.asset_id}.json").read_bytes() == asset.content
    assert hashlib.sha256(
        (first / "assets" / f"{asset.asset_id}.json").read_bytes()
    ).hexdigest() == asset.asset_id
    assert json.loads((first / "attribution.json").read_bytes())["sources"][0][
        "source_id"
    ] == "mapshaper"
    assert not any(
        path.name.startswith(f".{manifest.catalog_revision}-")
        for path in output_root.iterdir()
    )

    (first / "attribution.json").write_bytes(b"corrupt")
    with pytest.raises(PublicationError, match="IMMUTABLE_REVISION_CONFLICT"):
        publish_revision(
            output_root,
            manifest=manifest,
            assets=(asset,),
            attribution=attribution,
        )
