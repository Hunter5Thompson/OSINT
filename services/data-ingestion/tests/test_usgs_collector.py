"""Tests for USGS earthquake collector with nuclear test site enrichment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from feeds.usgs_collector import (
    NUCLEAR_TEST_SITES,
    USGSCollector,
    concern_level,
    concern_score,
    haversine_km,
)


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.vllm_url = "http://localhost:8000"
    s.vllm_model = "qwen3.5"
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = USGSCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_haversine_known_distance():
    d = haversine_km(40.7128, -74.0060, 33.9425, -118.4081)
    assert 3900 < d < 4000


def test_haversine_same_point():
    d = haversine_km(41.28, 129.08, 41.28, 129.08)
    assert d == 0.0


def test_concern_score_near_site():
    score = concern_score(magnitude=5.5, distance_km=5.0, depth_km=2.0)
    assert score > 50


def test_concern_score_far_away():
    score = concern_score(magnitude=4.5, distance_km=90.0, depth_km=50.0)
    assert score < 25


def test_concern_score_critical():
    score = concern_score(magnitude=8.0, distance_km=0.0, depth_km=1.0)
    assert score >= 75


def test_concern_level_thresholds():
    assert concern_level(80.0) == "critical"
    assert concern_level(60.0) == "elevated"
    assert concern_level(30.0) == "moderate"
    assert concern_level(10.0) is None


def test_nuclear_test_sites_count():
    assert len(NUCLEAR_TEST_SITES) == 5
    assert "Punggye-ri (DPRK)" in NUCLEAR_TEST_SITES


SAMPLE_GEOJSON = {
    "features": [
        {
            "id": "us7000test",
            "properties": {
                "mag": 5.2,
                "place": "45km NE of Kilju, North Korea",
                "time": 1712000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test",
            },
            "geometry": {
                "coordinates": [129.1, 41.3, 8.0],
            },
        },
        {
            "id": "us7000far",
            "properties": {
                "mag": 6.0,
                "place": "100km S of Tokyo, Japan",
                "time": 1712000000000,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000far",
            },
            "geometry": {
                "coordinates": [139.7, 34.7, 30.0],
            },
        },
    ]
}


def test_parse_features(collector):
    results = collector._parse_features(SAMPLE_GEOJSON["features"])
    assert len(results) == 2

    near = results[0]
    assert near["usgs_id"] == "us7000test"
    assert near["magnitude"] == 5.2
    assert near["nearest_test_site"] is not None
    assert near["concern_score"] is not None
    assert near["concern_level"] is not None

    far = results[1]
    assert far["usgs_id"] == "us7000far"
    assert far["nearest_test_site"] is None
    assert far["concern_score"] is None
