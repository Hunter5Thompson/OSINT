from gdelt_raw.schemas import GDELTEventWrite
from gdelt_raw.writers.neo4j_writer import MERGE_LOCATION, location_params_for


def test_merge_location_template():
    assert "MERGE (l:Location {loc_key: $loc_key})" in MERGE_LOCATION
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in MERGE_LOCATION
    assert "gdelt_actiongeo" in MERGE_LOCATION


def test_location_params_uses_build_location_id():
    ev = GDELTEventWrite(
        event_id="gdelt:event:1", cameo_code="193", cameo_root=19, quad_class=4,
        goldstein=-6.5, avg_tone=-4.0, num_mentions=3, num_sources=2, num_articles=3,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://x", codebook_type="conflict.armed", filter_reason="tactical",
        action_geo_lat=48.0, action_geo_long=37.8, action_geo_fullname="Donetsk, Ukraine",
        action_geo_country_code="UP", action_geo_feature_id="-1044367",
    )
    p = location_params_for(ev)
    assert p["loc_key"] == "gdelt:loc:-1044367"
    assert p["event_id"] == "gdelt:event:1"
    assert p["lat"] == 48.0


def test_location_params_none_when_no_coords():
    ev = GDELTEventWrite(
        event_id="gdelt:event:2", cameo_code="010", cameo_root=1, quad_class=1,
        goldstein=0.0, avg_tone=0.0, num_mentions=1, num_sources=1, num_articles=1,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://y", codebook_type="other.unclassified", filter_reason="tactical",
    )
    assert location_params_for(ev) is None


def test_location_params_null_island_is_none():
    ev = GDELTEventWrite(
        event_id="gdelt:event:3", cameo_code="010", cameo_root=1, quad_class=1,
        goldstein=0.0, avg_tone=0.0, num_mentions=1, num_sources=1, num_articles=1,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://z", codebook_type="other.unclassified", filter_reason="tactical",
        action_geo_lat=0.0, action_geo_long=0.0, action_geo_fullname="",
        action_geo_country_code="", action_geo_feature_id="",
    )
    assert location_params_for(ev) is None
