import json

from graph_integrity.report import (
    ACTOR_RELS,
    COORD_DISAGREEMENT,
    DUP_ACTOR_EDGES,
    GEO_COVERAGE,
    NULL_ISLAND,
    ORPHAN_BY_LABEL,
    location_writer_inventory,
    shape_report,
)


def test_queries_are_read_only():
    for q in (GEO_COVERAGE, ORPHAN_BY_LABEL, DUP_ACTOR_EDGES):
        upper = q.upper()
        assert "CREATE" not in upper
        assert "MERGE" not in upper
        assert "DELETE" not in upper
        assert "SET " not in upper


def test_dup_actor_edges_is_allowlist_scoped():
    assert "ALLIED_WITH" in ACTOR_RELS
    assert "SUPPLIES_TO" in ACTOR_RELS
    assert "SPOTTED_AT" not in ACTOR_RELS   # observation edge, never deduped
    assert "OCCURRED_AT" not in ACTOR_RELS
    assert "$actor_rels" in DUP_ACTOR_EDGES  # parameter-bound, not interpolated


def test_all_actor_rels_are_real_relation_types():
    expected = {"ALLIED_WITH", "SUPPLIES_TO", "COMPETES_WITH", "MEMBER_OF",
                "OPERATES_IN", "TARGETS", "COMMANDS", "NEGOTIATES_WITH", "SANCTIONS"}
    assert set(ACTOR_RELS) == expected


def test_shape_report_combines_sections():
    out = shape_report(
        orphans=[{"label": "Incident", "orphan": 1952, "total": 1952}],
        geo=[{"label": "Event", "located": 510, "total": 184633}],
        dup_edges=[{"rel": "ALLIED_WITH", "groups": 1, "extra": 8}],
    )
    assert out["orphans"][0]["label"] == "Incident"
    assert out["geo"][0]["located"] == 510
    assert out["dup_edges"][0]["extra"] == 8


def test_new_geo_queries_are_read_only():
    for q in (GEO_COVERAGE, COORD_DISAGREEMENT, NULL_ISLAND):
        upper = q.upper()
        assert "CREATE" not in upper
        assert "MERGE" not in upper
        assert "DELETE" not in upper
        assert "SET " not in upper


def test_geo_coverage_excludes_null_island():
    assert "0.0" in GEO_COVERAGE
    assert "WHERE NOT (l.lat = 0.0 AND l.lon = 0.0)" in GEO_COVERAGE


def test_shape_report_includes_geo_health_sections():
    out = shape_report(
        orphans=[{"label": "Event", "orphan": 0, "total": 1}],
        geo=[{"label": "Event", "located": 1, "total": 1}],
        dup_edges=[],
        coord_disagreements=[{"coord_disagreements": 0}],
        null_island=[{"null_island_locations": 0, "attached_nodes": 0}],
    )
    assert out["coord_disagreements"] == [{"coord_disagreements": 0}]
    assert out["null_island"] == [{"null_island_locations": 0, "attached_nodes": 0}]


def test_location_writer_inventory_enumerates_supported_and_unsupported_lanes():
    inventory = location_writer_inventory()
    lanes = {lane["lane"]: lane for lane in inventory["lanes"]}

    assert inventory["schema_version"] == 1
    assert [lane["lane"] for lane in inventory["lanes"]] == sorted(lanes)
    assert {
        "gdelt_raw",
        "rss_pipeline",
        "military_aircraft",
        "backend_incident",
        "intelligence_link_event_location",
        "graph_integrity_geo_gdelt",
        "graph_integrity_geo_incident",
        "graph_integrity_rekey_incident_locations",
    } == set(lanes)
    assert {
        lane["lane"]
        for lane in lanes.values()
        if lane["active"] and lane["normalization"] == "shared_spatial_normalizer"
    } == {"gdelt_raw", "rss_pipeline", "military_aircraft"}
    assert lanes["backend_incident"] == {
        "lane": "backend_incident",
        "path": "services/backend/app/cypher/incident_write.py",
        "active": True,
        "normalization": "unsupported",
        "reason": "cross_service_normalizer_not_integrated",
    }
    assert lanes["intelligence_link_event_location"]["active"] is False
    assert lanes["intelligence_link_event_location"]["reason"] == "no_production_call_sites"
    assert json.loads(json.dumps(inventory)) == inventory


def test_shape_report_embeds_machine_readable_location_writer_inventory():
    out = shape_report(orphans=[], geo=[], dup_edges=[])

    assert out["location_writer_inventory"] == location_writer_inventory()
