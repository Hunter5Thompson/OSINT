from graph_integrity.report import (
    GEO_COVERAGE,
    ORPHAN_BY_LABEL,
    DUP_ACTOR_EDGES,
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
    assert "ALLIED_WITH" in DUP_ACTOR_EDGES
    assert "SUPPLIES_TO" in DUP_ACTOR_EDGES
    assert "SPOTTED_AT" not in DUP_ACTOR_EDGES
    assert "OCCURRED_AT" not in DUP_ACTOR_EDGES


def test_shape_report_combines_sections():
    out = shape_report(
        orphans=[{"label": "Incident", "orphan": 1952, "total": 1952}],
        geo=[{"label": "Event", "located": 510, "total": 184633}],
        dup_edges=[{"rel": "ALLIED_WITH", "groups": 1, "extra": 8}],
    )
    assert out["orphans"][0]["label"] == "Incident"
    assert out["geo"][0]["located"] == 510
    assert out["dup_edges"][0]["extra"] == 8
