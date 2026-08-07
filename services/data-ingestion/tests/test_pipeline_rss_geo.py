"""RSS Location writer uses structured ISO2 without synthetic centroids."""

from pathlib import Path

import pytest

from graph_integrity.spatial_normalizer import load_normalization_index
from pipeline import _RESPONSE_SCHEMA, _SYSTEM_PROMPT, build_event_geo_fragment

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        REPOSITORY_ROOT
        / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799",
        crosswalk_path=(
            REPOSITORY_ROOT
            / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
        ),
    )


def test_event_geo_fragment_writes_country_scope_without_point(spatial_index) -> None:
    fragment = build_event_geo_fragment(country_code="UA", spatial_index=spatial_index)

    assert fragment is not None
    assert "MATCH" not in fragment["cypher"].upper()
    assert "id(ev)" not in fragment["cypher"]
    assert "MERGE (l:Location {loc_key: $loc_key})" in fragment["cypher"]
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in fragment["cypher"]
    assert "point(" not in fragment["cypher"]
    assert "$latitude" not in fragment["cypher"]
    assert fragment["parameters"]["loc_key"] == "spatial:country:ua"
    assert fragment["parameters"]["source_country_code"] == "UA"
    assert fragment["parameters"]["source_country_code_system"] == "iso2"
    assert fragment["parameters"]["country_scope_key"] == "country:UKR"
    assert fragment["parameters"]["admin1_scope_key"] is None
    assert fragment["parameters"]["spatial_precision"] == "country"
    for field in (
        "source_country_code",
        "source_country_code_system",
        "country_iso3",
        "admin1_code",
        "admin2_code",
        "country_scope_key",
        "admin1_scope_key",
        "admin2_scope_key",
        "spatial_basis",
        "spatial_precision",
        "spatial_catalog_revision",
        "spatial_derivation_revision",
        "spatial_conflict",
        "spatial_conflict_scope_keys",
    ):
        assert f"l.{field} = ${field}" in fragment["cypher"]
    assert "country:UKR" not in fragment["cypher"]
    assert "UA" not in fragment["cypher"]


def test_event_geo_fragment_fails_closed_for_unknown_or_free_name(spatial_index) -> None:
    assert build_event_geo_fragment(country_code="ZZ", spatial_index=spatial_index) is None
    assert build_event_geo_fragment(country_code=None, spatial_index=spatial_index) is None
    assert (
        build_event_geo_fragment(country_code="Ukraine", spatial_index=spatial_index)
        is None
    )
    assert build_event_geo_fragment(country_code="ua", spatial_index=spatial_index) is None


def test_extraction_contract_requires_uppercase_iso2_country_codes() -> None:
    country = _RESPONSE_SCHEMA["properties"]["locations"]["items"]["properties"][
        "country"
    ]

    assert country["pattern"] == "^[A-Z]{2}$"
    assert "ISO 3166-1 alpha-2" in _SYSTEM_PROMPT
