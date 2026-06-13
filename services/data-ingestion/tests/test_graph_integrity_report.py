from graph_integrity.report import (
    ACTOR_RELS,
    DUP_ACTOR_EDGES,
    GEO_COVERAGE,
    ORPHAN_BY_LABEL,
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
