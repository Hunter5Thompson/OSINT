import re

from suv_structured import write_templates as wt


def test_operates_is_type_guarded_and_match_only():
    t = wt.LINK_OPERATES
    assert "MATCH (op:Entity {name: $op_name, type: $op_type})" in t
    assert 'op.type IN ["MILITARY_UNIT", "ORGANIZATION"]' in t
    assert "MATCH (ws:Entity {name: $ws_name, type: $ws_type})" in t
    assert 'ws.type IN ["WEAPON_SYSTEM", "AIRCRAFT", "VESSEL", "SATELLITE"]' in t
    assert "MERGE (op)-[r:OPERATES]->(ws)" in t
    assert not re.search(r"MERGE \(op:Entity", t)
    assert not re.search(r"MERGE \(ws:Entity", t)
    for p in ("$count", "$count_raw", "$service_end", "$note", "$suv_url"):
        assert p in t
    assert 'r.data_source = "suv.report"' in t


def test_upsert_system_is_typed_and_non_destructive():
    t = wt.UPSERT_SYSTEM
    assert "MERGE (w:Entity {name: $name, type: $type})" in t
    assert "coalesce(w.aliases, [])" in t
    assert "coalesce(w.weapon_type, $weapon_type)" in t
    assert "coalesce(w.data_source, $data_source)" in t
    assert "coalesce(w.suv_url, $suv_url)" in t
    assert "w.suv_extracted_at = $extracted_at" in t
    assert "ON CREATE SET w.first_seen" in t


def test_upsert_operator_creates_typed_node():
    t = wt.UPSERT_OPERATOR
    assert "MERGE (o:Entity {name: $name, type: $type})" in t
    assert "coalesce(o.aliases, [])" in t
    assert "ON CREATE SET o.first_seen" in t
    assert "o.suv_extracted_at = $extracted_at" in t
