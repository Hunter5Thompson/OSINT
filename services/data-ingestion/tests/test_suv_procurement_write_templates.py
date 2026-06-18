import re

from suv_structured import write_templates as wt


def test_upsert_program_keyed_on_title_type():
    t = wt.UPSERT_PROCUREMENT_PROGRAM
    assert 'MERGE (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})' in t
    # F1 fix: new-value-first coalesce (brief Step 1 had args swapped)
    assert "coalesce($status, p.status)" in t
    assert "p.cost_eur = coalesce($cost_eur, p.cost_eur)" in t
    assert "p.contractor_raw = coalesce($contractor_raw, p.contractor_raw)" in t
    assert "p.suv_extracted_at = $extracted_at" in t
    assert "ON CREATE SET p.first_seen" in t


def test_procures_type_guarded_match_only():
    t = wt.LINK_PROCURES
    assert "MATCH (op:Entity {name: $op_name, type: $op_type})" in t
    assert 'op.type IN ["MILITARY_UNIT", "ORGANIZATION"]' in t
    assert 'MATCH (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})' in t
    assert "MERGE (op)-[r:PROCURES]->(p)" in t
    assert not re.search(r"MERGE \(op:Entity", t) and not re.search(r"MERGE \(p:Entity", t)


def test_contracted_to_match_only():
    t = wt.LINK_CONTRACTED_TO
    assert 'MATCH (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})' in t
    assert 'MATCH (c:Entity {name: $company, type: "ORGANIZATION"})' in t
    assert "MERGE (p)-[r:CONTRACTED_TO]->(c)" in t
    assert not re.search(r"MERGE \(c:Entity", t)


def test_concerns_system_type_guarded():
    t = wt.LINK_CONCERNS_SYSTEM
    assert 'MATCH (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})' in t
    assert "MATCH (s:Entity {name: $sys_name, type: $sys_type})" in t
    assert 's.type IN ["WEAPON_SYSTEM", "AIRCRAFT", "VESSEL", "SATELLITE"]' in t
    assert "MERGE (p)-[r:CONCERNS_SYSTEM]->(s)" in t
    assert not re.search(r"MERGE \(s:Entity", t)
