"""Tests for military aircraft collector (adsb.fi + OpenSky fallback)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from feeds.military_aircraft_collector import (
    MilitaryAircraftCollector,
    build_aircraft_location_statement,
    identify_branch,
    in_hotspot_coverage,
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

def test_hotspot_coverage_is_a_filter_not_a_place():
    assert in_hotspot_coverage(48.0, 35.0) is True
    assert in_hotspot_coverage(33.3, 44.4) is True   # Baghdad: inside the old "iran" box
    assert in_hotspot_coverage(0.0, 0.0) is False
    assert in_hotspot_coverage(52.5, 13.4) is False  # Berlin: only in a meta-region


@pytest.mark.parametrize(
    ("name", "lat", "lon", "expected"),
    [
        # First-match boxes used to label these "ukraine" / "iran" / "north_korea".
        ("Rostov-on-Don", 47.2, 39.7, "RUS"),
        ("Belgorod", 50.6, 36.6, "RUS"),
        ("Baghdad", 33.3, 44.4, "unresolved"),   # IRQ not in the test catalog
        ("Seoul", 37.6, 127.0, "unresolved"),    # KOR not in the test catalog
    ],
)
def test_aircraft_location_is_named_by_country_not_hotspot_box(
    collector, spatial_index, name, lat, lon, expected,
) -> None:
    raw = {**SAMPLE_ADSB_FI_RESPONSE,
           "ac": [{**SAMPLE_ADSB_FI_RESPONSE["ac"][0], "lat": lat, "lon": lon}]}
    aircraft = collector._parse_adsb_fi(raw)[0]
    assert "region" not in aircraft

    write = build_aircraft_location_statement(aircraft, spatial_index)

    assert write["parameters"]["name"] == expected, name
    assert "region" not in write["parameters"]
    assert "l.region" not in write["statement"]

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
    assert "ukraine" not in write["statement"]
    assert write["parameters"]["loc_key"].startswith("aircraft-observation:adf7c8|")
    assert write["parameters"]["name"] == "UKR"
    assert write["parameters"]["latitude"] == 48.5
    assert write["parameters"]["longitude"] == 35.2
    assert write["parameters"]["country_scope_key"] == "country:UKR"
    assert write["parameters"]["spatial_precision"] == "point"
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
        "in_coverage": False,
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
        "in_coverage": False,
        "latitude": latitude,
        "longitude": longitude,
    }

    assert build_aircraft_location_statement(aircraft, spatial_index) is None


# SPOTTED_AT.timestamp contract: epoch milliseconds (adsb.fi reports `now` in ms).


def test_parse_keeps_adsb_fi_epoch_ms_and_buckets_dedup_by_15_minutes(collector):
    raw = {**SAMPLE_ADSB_FI_RESPONSE, "now": 1_790_458_913_700}
    ac = collector._parse_adsb_fi(raw)[0]
    assert ac["timestamp"] == 1_790_458_913_700
    bucket = int(ac["dedup_key"].split("|")[1])
    assert bucket % 900_000 == 0
    assert bucket <= ac["timestamp"] < bucket + 900_000


def test_parse_polls_within_one_quarter_hour_share_a_dedup_key(collector):
    first = collector._parse_adsb_fi({**SAMPLE_ADSB_FI_RESPONSE, "now": 1_790_458_200_000})[0]
    later = collector._parse_adsb_fi({**SAMPLE_ADSB_FI_RESPONSE, "now": 1_790_459_099_999})[0]
    nxt = collector._parse_adsb_fi({**SAMPLE_ADSB_FI_RESPONSE, "now": 1_790_459_100_000})[0]
    assert first["dedup_key"] == later["dedup_key"] != nxt["dedup_key"]


def test_parse_normalizes_epoch_seconds_and_missing_now_to_ms(collector, monkeypatch):
    seconds = collector._parse_adsb_fi({**SAMPLE_ADSB_FI_RESPONSE, "now": 1_790_458_913})[0]
    assert seconds["timestamp"] == 1_790_458_913_000

    monkeypatch.setattr("feeds.military_aircraft_collector.time.time", lambda: 1_790_458_913.25)
    without_now = {k: v for k, v in SAMPLE_ADSB_FI_RESPONSE.items() if k != "now"}
    assert collector._parse_adsb_fi(without_now)[0]["timestamp"] == 1_790_458_913_250


def test_location_write_keeps_coordinates_consistent_with_latest_observation(
    collector, spatial_index,
) -> None:
    # A repeated poll in the same bucket updates the edge; the Location's
    # lat/lon/name must move with its geo and country derivation.
    aircraft = collector._parse_adsb_fi(SAMPLE_ADSB_FI_RESPONSE)[0]
    statement = build_aircraft_location_statement(aircraft, spatial_index)["statement"]
    on_create = statement.split("ON CREATE SET", 1)[1].split(" SET ", 1)[0]
    assert "l.lat" not in on_create and "l.name" not in on_create
    assert "l.lat = $latitude" in statement and "l.name = $name" in statement
