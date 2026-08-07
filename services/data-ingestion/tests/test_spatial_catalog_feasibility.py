from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from spatial_catalog.__main__ import (
    cached_source_path,
    create_parser,
    fetch_sources,
    main,
    read_cached_source,
)
from spatial_catalog.audit import (
    CatalogVerificationError,
    ContainmentFeasibilityRecord,
    WorldChildPackRecord,
    audit_catalog,
    build_feasibility_report,
    verify_catalog,
)
from spatial_catalog.compiler import compile_catalog
from spatial_catalog.emit import (
    AttributionRecord,
    ScopePackFeature,
    attribution_sources_sha256,
    emit_attribution,
    emit_boundary_pack,
    emit_containment_boundary,
    emit_render_boundary,
    publish_revision,
)
from spatial_catalog.manifest import (
    DerivationInputs,
    ManifestDraft,
    ManifestScopeInput,
    build_manifest,
    canonical_json_bytes,
)
from spatial_catalog.models import (
    CatalogProvenance,
    Lod,
    ScopeKind,
    ScopeNode,
    ScopePresentation,
)
from spatial_catalog.normalize import normalize_geometry
from spatial_catalog.source_lock import LockedSource, SourceHashMismatchError, SourceLock

CROSSWALK_HASH = "d393f5026dedd808cf2b517b574f16c311591a18891d0de6d738e327dbf4a369"
SCOPES = (
    "country:AFG",
    "country:ALB",
    "country:ARE",
    "country:AUS",
    "country:BRA",
    "country:CAN",
    "country:CHN",
    "country:DEU",
    "country:FJI",
    "country:FRA",
    "country:GBR",
    "country:UKR",
)


def _geometry(offset: float = 0.0):
    return normalize_geometry(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [offset, 0],
                    [offset + 0.5, 0],
                    [offset + 0.5, 0.5],
                    [offset, 0.5],
                    [offset, 0],
                ]
            ],
        }
    )


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


def _published_catalog(tmp_path: Path):
    asset = emit_render_boundary(_geometry(), lod=Lod.OVERVIEW)
    world = ScopeNode(
        key="world",
        kind=ScopeKind.WORLD,
        label="World",
        short_label="World",
        parent_key=None,
        children_available=False,
        presentation="boundary",
    )
    attribution_records = (
        AttributionRecord(
            "natural-earth-admin0",
            "5.1.2+f1890d9f152c",
            "public-domain",
            "Natural Earth",
        ),
    )
    manifest = build_manifest(
        ManifestDraft(
            schema_version=1,
            boundary_policy="odin-reference-v1",
            root_scope_key="world",
            attribution_sources_sha256=attribution_sources_sha256(attribution_records),
            scopes=(
                ManifestScopeInput(
                    scope=world,
                    path=("world",),
                    provenance=_provenance(),
                    presentation=ScopePresentation(
                        outline_lods={Lod.OVERVIEW: asset.descriptor}
                    ),
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
        attribution_records,
    )
    path = publish_revision(
        tmp_path / "catalogs",
        manifest=manifest,
        assets=(asset,),
        attribution=attribution,
    )
    return path, manifest, asset


def test_verify_detects_missing_corrupt_and_descriptor_drift(tmp_path: Path) -> None:
    catalog, _, asset = _published_catalog(tmp_path)
    asset_path = catalog / "assets" / f"{asset.asset_id}.json"

    verified = verify_catalog(catalog)
    assert verified.asset_count == 1

    original = asset_path.read_bytes()
    asset_path.write_bytes(b"corrupt")
    with pytest.raises(CatalogVerificationError, match="ASSET_HASH_MISMATCH"):
        verify_catalog(catalog)

    asset_path.write_bytes(original)
    asset_path.unlink()
    with pytest.raises(CatalogVerificationError, match="ASSET_MISSING"):
        verify_catalog(catalog)


def test_verify_rejects_missing_or_unbound_attribution_release(tmp_path: Path) -> None:
    catalog, _, _ = _published_catalog(tmp_path)
    attribution_path = catalog / "attribution.json"
    attribution = json.loads(attribution_path.read_bytes())
    attribution["sources"][0].pop("release")
    attribution_path.write_bytes(canonical_json_bytes(attribution))

    with pytest.raises(CatalogVerificationError, match="ATTRIBUTION_MISSING_OR_INVALID"):
        verify_catalog(catalog)


def test_verify_rejects_attribution_release_not_bound_by_manifest(tmp_path: Path) -> None:
    catalog, _, _ = _published_catalog(tmp_path)
    attribution_path = catalog / "attribution.json"
    attribution = json.loads(attribution_path.read_bytes())
    attribution["sources"][0]["release"] = "5.1.3-tampered"
    attribution_path.write_bytes(canonical_json_bytes(attribution))

    with pytest.raises(CatalogVerificationError, match="ATTRIBUTION_SOURCES_HASH_MISMATCH"):
        verify_catalog(catalog)


def test_audit_output_is_deterministic_and_enforces_seed_ceiling(tmp_path: Path) -> None:
    catalog, manifest, _ = _published_catalog(tmp_path)

    first = audit_catalog(catalog)
    second = audit_catalog(catalog)

    assert first == second
    payload = json.loads(first)
    assert payload["catalog_revision"] == manifest.catalog_revision
    assert payload["status"] == "pass"
    assert "built_at" not in payload

    with pytest.raises(CatalogVerificationError, match="SEED_CATALOG_SIZE"):
        verify_catalog(catalog, max_seed_bytes=1)


def test_feasibility_covers_mandatory_theater_and_top_ten_raw_ring_counts() -> None:
    records = tuple(
        ContainmentFeasibilityRecord(
            scope_key=scope_key,
            source_bytes=1_000 + index,
            normalized_bytes=900 + index,
            raw_ring_count=index,
            raw_vertex_count=index * 10,
            asset=emit_containment_boundary(
                _geometry(index),
                max_error_m=0.0,
                max_vertices=100,
            ),
            max_error_m=0.0,
        )
        for index, scope_key in enumerate(SCOPES, start=1)
    )
    pack = emit_boundary_pack(
        parent_scope_key="world",
        lod=Lod.OVERVIEW,
        allowed_child_scope_keys={"country:UKR"},
        features=(ScopePackFeature("country:UKR", "Ukraine", _geometry()),),
    )

    first = build_feasibility_report(
        catalog_revision="spatial-v1-001122334455",
        containment_records=records,
        mandatory_scope_keys={"country:AFG"},
        world_child_packs=(WorldChildPackRecord(Lod.OVERVIEW, pack),),
        emitted_world_lods={Lod.OVERVIEW},
        preferred_world_lod=Lod.OVERVIEW,
    )
    second = build_feasibility_report(
        catalog_revision="spatial-v1-001122334455",
        containment_records=tuple(reversed(records)),
        mandatory_scope_keys={"country:AFG"},
        world_child_packs=(WorldChildPackRecord(Lod.OVERVIEW, pack),),
        emitted_world_lods={Lod.OVERVIEW},
        preferred_world_lod=Lod.OVERVIEW,
    )

    assert first == second
    payload = json.loads(first)
    coverage = payload["containment"]["coverage_scope_keys"]
    assert payload["containment"]["max_error_semantics"] == (
        "deviation_from_locked_source_geometry_not_source_cartographic_accuracy"
    )
    assert "country:AFG" in coverage
    assert set(SCOPES[-10:]).issubset(coverage)
    world_pack = payload["world_child_packs"][0]
    assert world_pack["serialized_vertex_occurrences"] == pack.counts.vertex_count
    assert world_pack["canonical_wire_bytes"] == len(pack.content)
    assert world_pack["descriptor_vertex_count"] == pack.descriptor.vertex_count


def test_feasibility_fails_for_missing_coverage_or_world_lod() -> None:
    record = ContainmentFeasibilityRecord(
        scope_key="country:UKR",
        source_bytes=100,
        normalized_bytes=90,
        raw_ring_count=1,
        raw_vertex_count=5,
        asset=emit_containment_boundary(_geometry(), max_error_m=0, max_vertices=10),
        max_error_m=0,
    )
    pack = emit_boundary_pack(
        parent_scope_key="world",
        lod=Lod.OVERVIEW,
        allowed_child_scope_keys={"country:UKR"},
        features=(ScopePackFeature("country:UKR", "Ukraine", _geometry()),),
    )

    with pytest.raises(CatalogVerificationError, match="CONTAINMENT_COVERAGE_MISSING"):
        build_feasibility_report(
            catalog_revision="spatial-v1-001122334455",
            containment_records=(record,),
            mandatory_scope_keys={"country:POL"},
            world_child_packs=(WorldChildPackRecord(Lod.OVERVIEW, pack),),
            emitted_world_lods={Lod.OVERVIEW},
            preferred_world_lod=Lod.OVERVIEW,
        )

    with pytest.raises(CatalogVerificationError, match="WORLD_PACK_LOD_MISSING"):
        build_feasibility_report(
            catalog_revision="spatial-v1-001122334455",
            containment_records=(record,),
            mandatory_scope_keys={"country:UKR"},
            world_child_packs=(WorldChildPackRecord(Lod.OVERVIEW, pack),),
            emitted_world_lods={Lod.OVERVIEW, Lod.REGIONAL},
            preferred_world_lod=Lod.REGIONAL,
        )

    with pytest.raises(CatalogVerificationError, match="CONTAINMENT_COVERAGE_MISSING"):
        build_feasibility_report(
            catalog_revision="spatial-v1-001122334455",
            containment_records=(record,),
            mandatory_scope_keys=set(),
            raw_ring_counts={"country:POL": 2, "country:UKR": 1},
            world_child_packs=(WorldChildPackRecord(Lod.OVERVIEW, pack),),
            emitted_world_lods={Lod.OVERVIEW},
            preferred_world_lod=Lod.OVERVIEW,
        )


def test_fetch_writes_only_explicit_cache_and_hashes_before_publish(tmp_path: Path) -> None:
    payload = b'{"type":"FeatureCollection","features":[]}'
    source = LockedSource(
        source_id="fixture-source",
        release="2026.08.01+0123456789ab",
        url=(
            "https://raw.githubusercontent.com/example/project/"
            "0123456789abcdef0123456789abcdef01234567/source.geojson"
        ),
        sha256=hashlib.sha256(payload).hexdigest(),
        license_id="public-domain",
        attribution="Fixture",
    )
    source_lock = SourceLock(schema_version=1, sources=(source,))
    cache = tmp_path / "explicit-cache"
    calls: list[str] = []

    fetched = fetch_sources(
        source_lock,
        cache_dir=cache,
        repo_root=tmp_path,
        downloader=lambda locked: calls.append(locked.source_id) or payload,
    )

    assert fetched == (cached_source_path(cache, source),)
    assert fetched[0].read_bytes() == payload
    assert calls == ["fixture-source"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["explicit-cache"]


def test_cached_source_hash_is_checked_before_parser(tmp_path: Path) -> None:
    expected = b"valid"
    source = LockedSource(
        source_id="fixture-source",
        release="2026.08.01+0123456789ab",
        url=(
            "https://raw.githubusercontent.com/example/project/"
            "0123456789abcdef0123456789abcdef01234567/source.geojson"
        ),
        sha256=hashlib.sha256(expected).hexdigest(),
        license_id="public-domain",
        attribution="Fixture",
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    cached_source_path(cache, source).write_bytes(b"tampered")
    parser_called = False

    def parser(_: bytes) -> object:
        nonlocal parser_called
        parser_called = True
        return object()

    with pytest.raises(SourceHashMismatchError, match="SOURCE_HASH_MISMATCH"):
        read_cached_source(source, cache_dir=cache, parser=parser)
    assert not parser_called


def test_cli_argument_validation_and_offline_verify_audit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--source-lock", "lock.json"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "build",
                "--source-lock",
                "lock.json",
                "--cache-dir",
                "cache",
                "--out",
                "out",
                "--policy",
                "wrong-policy",
            ]
        )

    catalog, manifest, _ = _published_catalog(tmp_path)
    assert main(["verify", "--catalog", str(catalog)]) == 0
    assert manifest.catalog_revision in capsys.readouterr().out

    report = tmp_path / "audit.json"
    assert main(["audit", "--catalog", str(catalog), "--report", str(report)]) == 0
    assert report.read_bytes() == audit_catalog(catalog)


def test_offline_compiler_builds_byte_identical_revision_twice(tmp_path: Path) -> None:
    crosswalk_payload = json.loads(
        (Path(__file__).parents[1] / "spatial_catalog/data/country_crosswalk.json").read_text(
            encoding="utf-8"
        )
    )
    crosswalk_payload["records"] = [
        record
        for record in crosswalk_payload["records"]
        if record["scope_key"] in {"country:POL", "country:UKR"}
    ]
    crosswalk_bytes = json.dumps(
        crosswalk_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    natural_earth_bytes = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "UN_A3": "616",
                        "ISO_N3": "616",
                        "ISO_N3_EH": "616",
                        "NAME": "Poland",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[14, 49], [20, 49], [20, 55], [14, 55], [14, 49]]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "UN_A3": "804",
                        "ISO_N3": "804",
                        "ISO_N3_EH": "804",
                        "NAME": "Ukraine",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[20, 44], [41, 44], [41, 53], [20, 53], [20, 44]]],
                    },
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    admin1_geojson = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "shapeGroup": "UKR",
                        "shapeType": "ADM1",
                        "shapeID": "UKR-ADM1-1",
                        "shapeISO": "UA-01",
                        "shapeName": "West Fixture Oblast",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[20, 44], [30, 44], [30, 53], [20, 53], [20, 44]]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "shapeGroup": "UKR",
                        "shapeType": "ADM1",
                        "shapeID": "UKR-ADM1-2",
                        "shapeISO": "UA-02",
                        "shapeName": "East Fixture Oblast",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[30, 44], [41, 44], [41, 53], [30, 53], [30, 44]]],
                    },
                },
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    admin1_archive = io.BytesIO()
    with zipfile.ZipFile(admin1_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("geoBoundaries-UKR-ADM1.geojson", admin1_geojson)
    admin1_bytes = admin1_archive.getvalue()
    mapshaper_bytes = (
        Path(__file__).parents[1]
        / "spatial_catalog/data/mapshaper-0.7.49-offline.tgz"
    ).read_bytes()

    def locked(source_id: str, release: str, payload: bytes, license_id: str) -> LockedSource:
        return LockedSource(
            source_id=source_id,
            release=release,
            url=f"repo:fixtures/{source_id}.source",
            sha256=hashlib.sha256(payload).hexdigest(),
            license_id=license_id,
            attribution=f"Fixture {source_id}",
        )

    source_lock = SourceLock(
        schema_version=1,
        sources=(
            locked(
                "geoboundaries-gbopen-ukr-admin1",
                "fixture-2026.08.01",
                admin1_bytes,
                "CC-BY-4.0",
            ),
            locked("mapshaper", "0.7.49+odin-offline-v1", mapshaper_bytes, "MPL-2.0"),
            locked(
                "natural-earth-admin0",
                "fixture-2026.08.01",
                natural_earth_bytes,
                "public-domain",
            ),
            locked(
                "odin-country-crosswalk",
                "spatial-crosswalk-v1",
                crosswalk_bytes,
                "LicenseRef-ODIN-Reviewed-Crosswalk",
            ),
        ),
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    for source, payload in (
        (source_lock.source("geoboundaries-gbopen-ukr-admin1"), admin1_bytes),
        (source_lock.source("mapshaper"), mapshaper_bytes),
        (source_lock.source("natural-earth-admin0"), natural_earth_bytes),
        (source_lock.source("odin-country-crosswalk"), crosswalk_bytes),
    ):
        cached_source_path(cache, source).write_bytes(payload)
    plan_path = tmp_path / "catalog-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "boundary_policy": "odin-reference-v1",
                "scopes": [
                    {
                        "scope_key": "country:POL",
                        "activation": "active",
                        "max_level": "country",
                        "representation_source_id": "natural-earth-admin0",
                        "children_source_id": None,
                        "representation_id": "natural-earth-110m-admin0",
                        "client_strict_containment_required": False,
                    },
                    {
                        "scope_key": "country:UKR",
                        "activation": "active",
                        "max_level": "admin1",
                        "representation_source_id": "natural-earth-admin0",
                        "children_source_id": "geoboundaries-gbopen-ukr-admin1",
                        "representation_id": "natural-earth-110m-admin0",
                        "client_strict_containment_required": True,
                    }
                ],
                "non_scope_features": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    first = compile_catalog(
        source_lock=source_lock,
        cache_dir=cache,
        output_root=tmp_path / "first",
        policy="odin-reference-v1",
        catalog_plan_path=plan_path,
    )
    second = compile_catalog(
        source_lock=source_lock,
        cache_dir=cache,
        output_root=tmp_path / "second",
        policy="odin-reference-v1",
        catalog_plan_path=plan_path,
    )

    assert first.name == second.name
    first_files = {
        path.relative_to(first): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert verify_catalog(first).catalog_revision == first.name
    provenance = json.loads((first / "build-provenance.json").read_bytes())
    assert provenance["catalog_revision"] == first.name
    assert provenance["revision_forming"] is False
    assert provenance["toolchain"]["node"]["engine"] == ">=20.11.0"
    assert provenance["toolchain"]["node"]["version"].startswith("v")
    assert provenance["toolchain"]["mapshaper"]["release"] == (
        "0.7.49+odin-offline-v1"
    )
    manifest = json.loads((first / "manifest.json").read_bytes())
    pack_id = manifest["scopes"][0]["presentation"]["children_lods"]["overview"][
        "asset_id"
    ]
    assert b"catalog_revision" not in (first / "assets" / f"{pack_id}.json").read_bytes()

    scopes = {record["scope"]["key"]: record for record in manifest["scopes"]}
    ukraine = scopes["country:UKR"]
    poland = scopes["country:POL"]
    expected_children = {
        "admin1:iso3166-2:UA-01",
        "admin1:iso3166-2:UA-02",
    }
    assert ukraine["scope"]["children_available"] is True
    assert ukraine["presentation"]["preferred_lod"] == "regional"
    assert ukraine["presentation"]["children_lods"]["regional"]["feature_count"] == 2
    assert ukraine["provenance_ref"] == (
        "natural-earth-admin0+geoboundaries-gbopen-ukr-admin1"
    )
    assert poland["scope"]["children_available"] is False
    assert poland["presentation"]["children_lods"] == {}

    child_pack_id = ukraine["presentation"]["children_lods"]["regional"]["asset_id"]
    child_pack = json.loads((first / "assets" / f"{child_pack_id}.json").read_bytes())
    assert child_pack["parent_scope_key"] == "country:UKR"
    assert {feature["scope_key"] for feature in child_pack["features"]} == expected_children

    for child_key in expected_children:
        child = scopes[child_key]
        assert child["path"] == ["world", "country:UKR", child_key]
        assert child["scope"]["parent_key"] == "country:UKR"
        assert child["scope"]["children_available"] is False
        outline = child["presentation"]["outline_lods"]["regional"]
        assert outline["role"] == "render"
        assert outline["lod"] == "regional"
        assert outline["byte_length"] <= 4 * 1024 * 1024
        assert outline["vertex_count"] <= 50_000
        containment = child["presentation"]["containment"]
        assert containment["role"] == "containment"
        assert containment["max_error_m"] <= 50
        assert child["provenance"]["source_id"] == (
            "geoboundaries-gbopen-ukr-admin1"
        )

    feasibility = json.loads((first / "containment-feasibility.json").read_bytes())
    mandatory = set(feasibility["containment"]["mandatory_scope_keys"])
    reported = {
        record["scope_key"]: record
        for record in feasibility["containment"]["features"]
    }
    assert expected_children <= mandatory
    for child_key in expected_children:
        assert reported[child_key]["status"] == "pass"
        assert reported[child_key]["max_error_m"] <= 50
