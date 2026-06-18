# services/data-ingestion/tests/test_suv_build_equipment.py
from pathlib import Path

import pytest

from suv_structured.build_equipment import (
    EquipmentBuildGateError,
    build_equipment_statements,
    dedup_systems,
    ws_write_name,
)
from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.operators import OperatorEntry, operators_by_slug

HEER = "hauptwaffensysteme-des-heeres"
URL = "https://suv.report/hauptwaffensysteme-des-heeres/"
OPS = operators_by_slug([OperatorEntry(
    page_slug=HEER, page_label="Heer", decision="match",
    target_name="Deutsches Heer", target_type="MILITARY_UNIT")])


def _row(muster, count=None, service_end=None):
    return WeaponSystemRow(muster=muster, type_raw="Kampfpanzer", count=count,
                           count_raw=str(count) if count else None,
                           service_end=service_end, page_slug=HEER, suv_url=URL)


def test_dedup_systems_by_muster():
    rows = [_row("Leopard 2"), _row("Leopard 2"), _row("Puma")]
    assert sorted(r.muster for r in dedup_systems(rows)) == ["Leopard 2", "Puma"]


def test_ws_write_name_match_vs_new():
    matched = {"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}
    new = {"name": "Schakal", "decision": "new", "approved_new": True, "evidence": "x"}
    assert ws_write_name(_row("Leopard 2"), matched) == "Leopard 2"
    assert ws_write_name(_row("Schakal"), new) == "Schakal"


def test_build_statements_orders_endpoints_before_link():
    rows = [_row("Leopard 2", count=310, service_end=2050)]
    approved = [{"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}]
    stmts = build_equipment_statements(rows, approved, OPS, extracted_at="2026-06-18T00:00:00Z")
    # the WEAPON_SYSTEM upsert (MERGE w) precedes the OPERATES link (MATCH op)
    ws_idx = next(i for i, s in enumerate(stmts) if "MERGE (w:Entity" in s["statement"])
    op_idx = next(i for i, s in enumerate(stmts) if "MERGE (op)-[r:OPERATES]" in s["statement"])
    assert ws_idx < op_idx
    link = stmts[op_idx]["parameters"]
    assert link == {"op_name": "Deutsches Heer", "op_type": "MILITARY_UNIT",
                    "ws_name": "Leopard 2", "count": 310, "count_raw": "310",
                    "service_end": 2050, "note": None, "suv_url": URL}


def test_build_equipment_module_has_no_qdrant_dependency():
    """Track 2a is graph-only: the build module must not import or touch Qdrant."""
    import suv_structured.build_equipment as be
    assert "qdrant" not in Path(be.__file__).read_text().lower()


def test_build_raises_on_missing_operator():
    """Fail-closed: an approved holding whose page has no operator seed must raise,
    never be silently skipped (defense-in-depth alongside the gate)."""
    rows = [_row("Leopard 2")]  # page_slug = HEER
    approved = [{"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}]
    with pytest.raises(EquipmentBuildGateError):
        build_equipment_statements(rows, approved, {}, extracted_at="t")  # empty operator map


def test_build_skips_unapproved_rows():
    rows = [_row("Leopard 2"), _row("UnapprovedThing")]
    approved = [{"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}]
    stmts = build_equipment_statements(rows, approved, OPS, extracted_at="t")
    assert not any("UnapprovedThing" in str(s["parameters"]) for s in stmts)


def test_build_creates_operator_for_create_decision():
    ops = operators_by_slug([OperatorEntry(
        page_slug=HEER, page_label="CIR", decision="create",
        target_name="Cyber- und Informationsraum", target_type="MILITARY_UNIT",
        create_properties={"aliases": ["CIR"]})])
    rows = [_row("Tool X")]
    approved = [{"name": "Tool X", "decision": "match", "existing_name": "Tool X"}]
    stmts = build_equipment_statements(rows, approved, ops, extracted_at="t")
    assert any("MERGE (o:Entity {name: $name, type: $type})" in s["statement"] for s in stmts)
