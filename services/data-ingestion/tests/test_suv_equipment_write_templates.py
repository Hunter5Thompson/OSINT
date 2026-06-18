import re

from suv_structured import write_templates as wt


def test_operates_is_type_guarded_and_match_only():
    t = wt.LINK_OPERATES
    # operator matched on exact (name, type) bound from the seed
    assert "MATCH (op:Entity {name: $op_name, type: $op_type})" in t
    # allowed-source-type invariant
    assert 'op.type IN ["MILITARY_UNIT", "ORGANIZATION"]' in t
    # target is WEAPON_SYSTEM, matched (never merged)
    assert 'MATCH (ws:Entity {name: $ws_name, type: "WEAPON_SYSTEM"})' in t
    # the relationship is merged; the endpoint NODES are not
    assert "MERGE (op)-[r:OPERATES]->(ws)" in t
    assert not re.search(r"MERGE \(op:Entity", t)
    assert not re.search(r"MERGE \(ws:Entity", t)
    # edge properties
    for p in ("$count", "$count_raw", "$service_end", "$note", "$suv_url"):
        assert p in t
    assert 'r.data_source = "suv.report"' in t


def test_upsert_weapon_system_is_non_destructive():
    t = wt.UPSERT_WEAPON_SYSTEM
    assert 'MERGE (w:Entity {name: $name, type: "WEAPON_SYSTEM"})' in t
    assert "coalesce(w.aliases, [])" in t          # alias append-dedup
    assert "coalesce(w.weapon_type, $weapon_type)" in t   # enrich-if-absent, never clobber
    assert "coalesce(w.data_source, $data_source)" in t
    assert "coalesce(w.suv_url, $suv_url)" in t
    assert "ON CREATE SET w.first_seen" in t


def test_upsert_operator_creates_typed_node():
    t = wt.UPSERT_OPERATOR
    assert "MERGE (o:Entity {name: $name, type: $type})" in t
    assert "coalesce(o.aliases, [])" in t
    assert "ON CREATE SET o.first_seen" in t
