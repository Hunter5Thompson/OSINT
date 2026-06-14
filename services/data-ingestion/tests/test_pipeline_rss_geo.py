"""Tests for RSS event country-centroid geo fragment (Task 10)."""

from pipeline import build_event_geo_fragment


def test_event_geo_fragment_for_known_country():
    frag = build_event_geo_fragment(country="UA")
    assert frag is not None
    # Fragment continues an existing `WITH ev` chain — NO standalone MATCH/id(ev).
    assert "MATCH" not in frag["cypher"].upper()
    assert "id(ev)" not in frag["cypher"]
    assert "MERGE (l:Location {loc_key: $loc_key})" in frag["cypher"]
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in frag["cypher"]
    assert frag["parameters"]["loc_key"] == "centroid:ua"
    assert frag["parameters"]["geo_basis"] == "country_centroid"
    assert frag["parameters"]["geo_precision"] == "country"


def test_event_geo_fragment_none_for_unknown_country():
    assert build_event_geo_fragment(country="ZZ") is None
    assert build_event_geo_fragment(country=None) is None


def test_event_geo_fragment_accepts_country_name():
    frag = build_event_geo_fragment(country="Ukraine")
    assert frag is not None
    assert frag["parameters"]["loc_key"] == "centroid:ua"


def test_event_geo_fragment_accepts_lowercase_name():
    assert build_event_geo_fragment(country="ukraine")["parameters"]["loc_key"] == "centroid:ua"
