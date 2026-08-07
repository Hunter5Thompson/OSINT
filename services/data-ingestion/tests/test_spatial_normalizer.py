from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from graph_integrity.spatial_normalizer import (
    AdministrativeCodeSystem,
    CountryCodeSystem,
    RawLocationIdentity,
    SpatialBasis,
    SpatialNormalizationIndex,
    SpatialPrecision,
    build_normalization_index,
    load_normalization_index,
    normalize_location,
)
from spatial_catalog.identity import load_country_crosswalk
from spatial_catalog.normalize import normalize_geometry

DATA_INGESTION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_DIRECTORY = (
    REPOSITORY_ROOT / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799"
)
CROSSWALK_PATH = DATA_INGESTION_ROOT / "spatial_catalog/data/country_crosswalk.json"
SHARED_BORDER_PATH = DATA_INGESTION_ROOT / "tests/fixtures/spatial_catalog/shared_border.geojson"


@pytest.fixture(scope="module")
def published_index() -> SpatialNormalizationIndex:
    return load_normalization_index(
        CATALOG_DIRECTORY,
        crosswalk_path=CROSSWALK_PATH,
    )


@pytest.fixture(scope="module")
def shared_border_index() -> SpatialNormalizationIndex:
    payload = json.loads(SHARED_BORDER_PATH.read_text(encoding="utf-8"))
    geometry_by_scope = {
        feature["properties"]["scope_key"]: normalize_geometry(feature["geometry"])
        for feature in payload["features"]
    }
    parent = normalize_geometry(
        {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
        }
    )
    return build_normalization_index(
        catalog_revision="spatial-v1-111111111111",
        country_crosswalk=load_country_crosswalk(CROSSWALK_PATH),
        scope_parents={
            "country:UKR": None,
            "admin1:gbopen:TEST.LEFT": "country:UKR",
            "admin1:gbopen:TEST.RIGHT": "country:UKR",
        },
        scope_derivation_revisions={
            "country:UKR": "spatial-derive-v1-111111111111",
            "admin1:gbopen:TEST.LEFT": "spatial-derive-v1-222222222222",
            "admin1:gbopen:TEST.RIGHT": "spatial-derive-v1-333333333333",
        },
        containment={
            "country:UKR": parent,
            **geometry_by_scope,
        },
    )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"country_code": "UP"}, "country code and system"),
        (
            {"country_code_system": CountryCodeSystem.GDELT_GEC},
            "country code and system",
        ),
        ({"admin1_code": "UA-14"}, "admin1 code and system"),
        (
            {"admin1_code_system": AdministrativeCodeSystem.ISO_3166_2},
            "admin1 code and system",
        ),
        ({"admin2_code": "example"}, "admin2 code and system"),
        (
            {"admin2_code_system": AdministrativeCodeSystem.GEOBOUNDARIES},
            "admin2 code and system",
        ),
        ({"latitude": 0.0}, "latitude and longitude"),
        ({"longitude": 0.0}, "latitude and longitude"),
    ],
)
def test_raw_identity_requires_paired_values(values: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RawLocationIdentity(**values)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)],
)
def test_raw_identity_rejects_coordinates_outside_range(
    latitude: float,
    longitude: float,
) -> None:
    with pytest.raises(ValidationError):
        RawLocationIdentity(latitude=latitude, longitude=longitude)


def test_raw_identity_is_strict_and_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RawLocationIdentity(latitude="0", longitude=0.0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RawLocationIdentity.model_validate({"display_name": "Ukraine"})


def test_real_zero_zero_point_is_preserved(published_index: SpatialNormalizationIndex) -> None:
    raw = RawLocationIdentity(latitude=0.0, longitude=0.0)

    result = normalize_location(raw, published_index)

    assert result.latitude == 0.0
    assert result.longitude == 0.0
    assert result.spatial_precision is SpatialPrecision.POINT
    assert result.country_scope_key is None
    assert result.status == "unresolved"


@pytest.mark.parametrize(
    ("system", "code"),
    [
        (CountryCodeSystem.ISO2, "UA"),
        (CountryCodeSystem.ISO3, "UKR"),
        (CountryCodeSystem.UN_M49, "804"),
        (CountryCodeSystem.NATURAL_EARTH_M49, "804"),
        (CountryCodeSystem.GDELT_GEC, "UP"),
        (CountryCodeSystem.ODIN_SCOPE_KEY, "country:UKR"),
    ],
)
def test_country_code_adapters_resolve_only_reviewed_identities(
    published_index: SpatialNormalizationIndex,
    system: CountryCodeSystem,
    code: str,
) -> None:
    result = normalize_location(
        RawLocationIdentity(country_code=code, country_code_system=system),
        published_index,
    )

    assert result.status == "resolved"
    assert result.country_scope_key == "country:UKR"
    assert result.country_iso3 == "UKR"
    assert result.admin1_scope_key is None


def test_gdelt_gec_is_not_assumed_to_be_iso2(
    published_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(
            country_code="UP",
            country_code_system=CountryCodeSystem.GDELT_GEC,
        ),
        published_index,
    )

    assert result.country_scope_key == "country:UKR"
    assert result.spatial_basis is SpatialBasis.CROSSWALK


def test_iso2_and_gdelt_use_distinct_explicit_adapters(
    published_index: SpatialNormalizationIndex,
) -> None:
    iso = normalize_location(
        RawLocationIdentity(
            country_code="GB",
            country_code_system=CountryCodeSystem.ISO2,
        ),
        published_index,
    )
    gdelt = normalize_location(
        RawLocationIdentity(
            country_code="UK",
            country_code_system=CountryCodeSystem.GDELT_GEC,
        ),
        published_index,
    )

    assert iso.country_scope_key == "country:GBR"
    assert gdelt.country_scope_key == "country:GBR"


def test_unofficial_iso2_does_not_reach_odin_disputed_scope(
    published_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(
            country_code="XK",
            country_code_system=CountryCodeSystem.ISO2,
        ),
        published_index,
    )

    assert result.status == "unresolved"
    assert result.country_scope_key is None
    assert result.unresolved_codes == ("iso2:XK",)


def test_iso_3166_2_resolves_admin1_and_parent_country(
    published_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(
            admin1_code="UA-14",
            admin1_code_system=AdministrativeCodeSystem.ISO_3166_2,
        ),
        published_index,
    )

    assert result.status == "resolved"
    assert result.country_scope_key == "country:UKR"
    assert result.admin1_scope_key == "admin1:iso3166-2:UA-14"
    assert result.admin1_code == "UA-14"
    assert result.spatial_precision is SpatialPrecision.ADMIN1


def test_country_only_never_invents_point_or_admin_scope(
    published_index: SpatialNormalizationIndex,
) -> None:
    raw = RawLocationIdentity(
        country_code="UP",
        country_code_system=CountryCodeSystem.GDELT_GEC,
        source_country_name="Ukraine",
    )

    result = normalize_location(raw, published_index)

    assert result.raw == raw
    assert result.source_country_code == "UP"
    assert result.source_country_code_system is CountryCodeSystem.GDELT_GEC
    assert result.latitude is None
    assert result.longitude is None
    assert result.admin1_scope_key is None
    assert result.spatial_precision is SpatialPrecision.COUNTRY


def test_free_name_is_preserved_but_never_promoted_to_scope(
    published_index: SpatialNormalizationIndex,
) -> None:
    raw = RawLocationIdentity(source_country_name="Ukraine")

    result = normalize_location(raw, published_index)

    assert result.raw.source_country_name == "Ukraine"
    assert result.status == "unresolved"
    assert result.country_scope_key is None
    assert result.spatial_derivation_revision is None


def test_coordinate_only_interior_uses_published_containment(
    published_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(latitude=48.0, longitude=37.8),
        published_index,
    )

    assert result.status == "resolved"
    assert result.country_scope_key == "country:UKR"
    assert result.admin1_scope_key == "admin1:iso3166-2:UA-14"
    assert result.spatial_basis is SpatialBasis.COORDINATE
    assert result.spatial_precision is SpatialPrecision.POINT
    assert result.spatial_conflict is False


def test_shared_boundary_keeps_common_ancestor_and_all_candidates(
    shared_border_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(latitude=0.5, longitude=1.0),
        shared_border_index,
    )

    assert result.status == "conflict"
    assert result.country_scope_key == "country:UKR"
    assert result.admin1_scope_key is None
    assert result.spatial_conflict is True
    assert result.spatial_conflict_scope_keys == (
        "admin1:gbopen:TEST.LEFT",
        "admin1:gbopen:TEST.RIGHT",
    )


def test_single_child_outer_boundary_falls_back_to_parent(
    shared_border_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(latitude=0.5, longitude=0.0),
        shared_border_index,
    )

    assert result.status == "conflict"
    assert result.country_scope_key == "country:UKR"
    assert result.admin1_scope_key is None
    assert result.spatial_conflict_scope_keys == ("admin1:gbopen:TEST.LEFT",)


def test_explicit_source_admin_wins_over_coordinate_ambiguity_but_audits_it(
    shared_border_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(
            admin1_code="admin1:gbopen:TEST.LEFT",
            admin1_code_system=AdministrativeCodeSystem.ODIN_SCOPE_KEY,
            latitude=0.5,
            longitude=1.0,
        ),
        shared_border_index,
    )

    assert result.admin1_scope_key == "admin1:gbopen:TEST.LEFT"
    assert result.spatial_basis is SpatialBasis.SOURCE
    assert result.spatial_conflict is True
    assert result.spatial_conflict_scope_keys == (
        "admin1:gbopen:TEST.LEFT",
        "admin1:gbopen:TEST.RIGHT",
    )


def test_contradictory_source_codes_are_explicit_conflict(
    published_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(
            country_code="US",
            country_code_system=CountryCodeSystem.GDELT_GEC,
            admin1_code="UA-14",
            admin1_code_system=AdministrativeCodeSystem.ISO_3166_2,
        ),
        published_index,
    )

    assert result.status == "conflict"
    assert result.spatial_conflict is True
    assert set(result.spatial_conflict_scope_keys) == {
        "country:USA",
        "admin1:iso3166-2:UA-14",
    }


def test_unknown_code_fails_closed_without_coordinate_fallback(
    published_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(
            country_code="ZZ",
            country_code_system=CountryCodeSystem.GDELT_GEC,
            latitude=48.0,
            longitude=37.8,
        ),
        published_index,
    )

    assert result.status == "unresolved"
    assert result.country_scope_key is None
    assert result.admin1_scope_key is None
    assert result.spatial_conflict is False
    assert result.unresolved_codes == ("gdelt-gec:ZZ",)


def test_catalog_and_derivation_revisions_remain_separate(
    published_index: SpatialNormalizationIndex,
) -> None:
    result = normalize_location(
        RawLocationIdentity(
            country_code="UP",
            country_code_system=CountryCodeSystem.GDELT_GEC,
        ),
        published_index,
    )

    assert result.spatial_catalog_revision == "spatial-v1-e76a16bff799"
    assert result.spatial_derivation_revision == "spatial-derive-v1-d30efa07e141"
    assert result.spatial_catalog_revision != result.spatial_derivation_revision
