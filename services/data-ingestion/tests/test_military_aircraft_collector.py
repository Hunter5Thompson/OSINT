"""Tests for military aircraft collector (adsb.fi + OpenSky fallback)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from feeds.military_aircraft_collector import (
    MilitaryAircraftCollector,
    build_aircraft_location_statement,
    classify_region,
    identify_branch,
)
from graph_integrity.spatial_normalizer import load_normalization_index

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


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.opensky_client_id = ""
    s.opensky_client_secret = ""
    s.neo4j_url = "bolt://localhost:7687"
    s.neo4j_http_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = MilitaryAircraftCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_identify_branch_usaf():
    assert identify_branch("ADF7C8") == "USAF"
    assert identify_branch("AFFFFF") == "USAF"

def test_identify_branch_raf():
    assert identify_branch("400000") == "RAF"
    assert identify_branch("43C000") == "RAF"

def test_identify_branch_nato():
    assert identify_branch("4D0000") == "NATO"

def test_identify_branch_unknown():
    assert identify_branch("000000") is None
    assert identify_branch("FFFFFF") is None

def test_identify_branch_gaf():
    assert identify_branch("3EA000") == "GAF"

def test_identify_branch_faf():
    assert identify_branch("3AA000") == "FAF"

def test_identify_branch_iaf():
    assert identify_branch("738A00") == "IAF"

def test_classify_region():
    assert classify_region(48.0, 35.0) == "ukraine"
    assert classify_region(33.0, 44.0) == "iran"
    assert classify_region(0.0, 0.0) == "unknown"

SAMPLE_ADSB_FI_RESPONSE = {
    "ac": [
        {
            "hex": "ADF7C8",
            "flight": "RCH401  ",
            "lat": 48.5,
            "lon": 35.2,
            "alt_baro": 35000,
            "gs": 450.0,
            "track": 90.0,
            "t": "C17",
            "r": "05-5139",
        },
    ],
    "now": 1712000000,
    "total": 1,
}

def test_parse_adsb_fi(collector):
    aircraft = collector._parse_adsb_fi(SAMPLE_ADSB_FI_RESPONSE)
    assert len(aircraft) == 1
    ac = aircraft[0]
    assert ac["icao24"] == "adf7c8"
    assert ac["callsign"] == "RCH401"
    assert ac["military_branch"] == "USAF"
    assert ac["latitude"] == 48.5
    assert ac["altitude_m"] == round(35000 * 0.3048, 1)


def test_aircraft_location_is_observation_keyed_and_spatially_normalized(
    collector,
    spatial_index,
) -> None:
    aircraft = collector._parse_adsb_fi(SAMPLE_ADSB_FI_RESPONSE)[0]

    write = build_aircraft_location_statement(aircraft, spatial_index)

    assert "MERGE (l:Location {loc_key: $loc_key})" in write["statement"]
    assert "point({longitude: $longitude, latitude: $latitude})" in write["statement"]
    assert "$region" in write["statement"]
    assert "ukraine" not in write["statement"]
    assert write["parameters"]["loc_key"].startswith("aircraft-observation:adf7c8|")
    assert write["parameters"]["name"] == "ukraine"
    assert write["parameters"]["latitude"] == 48.5
    assert write["parameters"]["longitude"] == 35.2
    assert write["parameters"]["country_scope_key"] == "country:UKR"
    assert write["parameters"]["spatial_precision"] == "point"
    assert write["parameters"]["region"] == "ukraine"
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
        assert f"l.{field} = ${field}" in write["statement"]
    assert "country:UKR" not in write["statement"]


def test_aircraft_null_island_sentinel_has_no_location_write(spatial_index) -> None:
    aircraft = {
        "dedup_key": "000001|1712000000",
        "region": "unknown",
        "latitude": 0.0,
        "longitude": 0.0,
    }

    write = build_aircraft_location_statement(aircraft, spatial_index)

    assert write is None


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    ((None, None), (48.5, None), (None, 35.2)),
)
def test_aircraft_incomplete_position_has_no_location_write(
    spatial_index,
    latitude: float | None,
    longitude: float | None,
) -> None:
    aircraft = {
        "dedup_key": "000001|1712000000",
        "region": "unknown",
        "latitude": latitude,
        "longitude": longitude,
    }

    assert build_aircraft_location_statement(aircraft, spatial_index) is None
