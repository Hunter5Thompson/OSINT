"""Tests for military aircraft collector (adsb.fi + OpenSky fallback)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.military_aircraft_collector import (
    MilitaryAircraftCollector,
    classify_region,
    identify_branch,
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
    s.neo4j_url = "http://localhost:7474"
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
