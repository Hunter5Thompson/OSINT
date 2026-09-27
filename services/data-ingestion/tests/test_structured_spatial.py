from pathlib import Path

import pytest

from graph_integrity.spatial_normalizer import load_normalization_index
from source_spatial import project_feed_spatial, source_location


@pytest.fixture(scope="module")
def index():
    root = Path(__file__).resolve().parents[2]
    return load_normalization_index(
        root / "backend/data/spatial/catalogs/spatial-v1-a8e3a4af02d0",
        crosswalk_path=Path("spatial_catalog/data/country_crosswalk.json"),
    )


@pytest.mark.parametrize(
    "source,id_field",
    [
        ("usgs", "usgs_id"),
        ("firms", "content_hash"),
        ("ucdp", "ucdp_id"),
        ("eonet", "eonet_id"),
        ("gdacs", "gdacs_id"),
    ],
)
def test_structured_source_coordinates_produce_occurrence_tokens(index, source, id_field):
    payload = {
        "source": source,
        id_field: "one",
        "where_prec": 1,
        "latitude": 33.3152,
        "longitude": 44.3661,
    }
    result = project_feed_spatial(payload, index)
    assert result["spatial_occurrence_scope_revision_tokens"]
    assert result["spatial_about_scope_revision_tokens"] == []
    assert result["geo"] == {"lat": 33.3152, "lon": 44.3661}
    assert source_location(payload).latitude == 33.3152


@pytest.mark.parametrize(
    "values",
    [
        {"latitude": 91.0, "longitude": 44.0},
        {"latitude": 33.0},
        {"latitude": 0.0, "longitude": 0.0},
    ],
)
def test_invalid_evidence_cannot_reuse_old_tokens(index, values):
    result = project_feed_spatial({"source": "usgs", "usgs_id": "x", **values}, index)
    assert result["spatial_occurrence_scope_revision_tokens"] == []


def test_unknown_source_or_missing_identity_is_not_inferred(index):
    for payload in [
        {"source": "rss", "usgs_id": "x", "latitude": 33.3152, "longitude": 44.3661},
        {"source": "usgs", "latitude": 33.3152, "longitude": 44.3661},
    ]:
        assert (
            project_feed_spatial(payload, index)["spatial_occurrence_scope_revision_tokens"] == []
        )


def test_graph_and_vector_writes_share_normalized_identity(index):
    from source_spatial import observation_geo_fragment

    payload = {"source": "usgs", "usgs_id": "one", "latitude": 33.3152, "longitude": 44.3661}
    fragment = observation_geo_fragment(payload, index)
    vector = project_feed_spatial(payload, index)
    params = fragment["parameters"]
    assert params["country_iso3"] == "IRQ"
    assert params["latitude"] == vector["geo"]["lat"]
    assert params["longitude"] == vector["geo"]["lon"]
    assert (
        f"sr1|{params['country_scope_key']}|{params['spatial_derivation_revision']}"
        in vector["spatial_occurrence_scope_revision_tokens"]
    )
    assert "OCCURRED_AT" in fragment["cypher"]


def test_mutable_observation_refresh_updates_existing_location_without_new_event(index):
    from source_spatial import observation_refresh_fragment

    payload = {"source": "eonet", "eonet_id": "one", "latitude": 33.3152, "longitude": 44.3661}
    before = observation_refresh_fragment(payload, index)
    after = observation_refresh_fragment({**payload, "longitude": 45.0}, index)
    assert before["parameters"]["loc_key"] == after["parameters"]["loc_key"]
    assert after["parameters"]["longitude"] == 45.0
    assert "MATCH (l:Location" in after["cypher"]
    assert "MERGE" not in after["cypher"]
    assert "(ev)" not in after["cypher"]


@pytest.mark.parametrize("precision", [None, 2, 3, 4, 5, 6, 7])
def test_ucdp_uncertain_reference_points_do_not_become_exact_occurrences(index, precision):
    payload = {
        "source": "ucdp",
        "ucdp_id": "one",
        "where_prec": precision,
        "latitude": 33.3152,
        "longitude": 44.3661,
    }
    assert project_feed_spatial(payload, index)["spatial_occurrence_scope_revision_tokens"] == []


def test_structured_graph_retains_source_coordinate_semantics_and_time(index):
    from source_spatial import observation_geo_fragment

    payload = {
        "source": "gdacs",
        "gdacs_id": "one",
        "latitude": 33.3152,
        "longitude": 44.3661,
        "from_date": "2026-09-20",
        "to_date": "2026-09-22",
    }
    params = observation_geo_fragment(payload, index)["parameters"]
    assert params["coordinate_basis"] == "reported_centroid"
    assert params["source_time_start"] == "2026-09-20"
    assert params["source_time_end"] == "2026-09-22"


def test_invalid_source_projection_explicitly_clears_old_derived_geometry(index):
    result = project_feed_spatial({"source": "usgs", "usgs_id": "one"}, index)
    assert result["geo"] is None
    assert result["country_iso3"] == []
    assert result["spatial_catalog_revision"] == index.catalog_revision
