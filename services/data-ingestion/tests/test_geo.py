"""Tests for shared geospatial utilities."""

from feeds.geo import haversine_km


def test_haversine_known_distance():
    """NYC to LA ≈ 3944 km."""
    d = haversine_km(40.7128, -74.0060, 33.9425, -118.4081)
    assert 3900 < d < 4000


def test_haversine_same_point():
    d = haversine_km(41.28, 129.08, 41.28, 129.08)
    assert d == 0.0


def test_haversine_short_distance():
    """Two points ~1.1km apart in central London."""
    d = haversine_km(51.5074, -0.1278, 51.5174, -0.1278)
    assert 1.0 < d < 1.2
