# services/data-ingestion/tests/test_suv_equipment_match_report.py
from pathlib import Path

import pytest

from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.match_report import build_match_report, dump_report, load_approved


def _row(muster):
    return WeaponSystemRow(muster=muster, page_slug="p", suv_url="u")


def test_weapon_system_match_new_ambiguous():
    rows = [_row("Leopard 2"), _row("Schakal"), _row("PATRIOT")]
    lookup = {
        "leopard 2": [("Leopard 2", "WEAPON_SYSTEM", "id1")],
        "patriot": [("Patriot", "WEAPON_SYSTEM", "id2"), ("PATRIOT", "WEAPON_SYSTEM", "id3")],
    }
    report = build_match_report(rows, lookup, target_type="WEAPON_SYSTEM", gate_new_creation=True)
    by = {r["name"]: r for r in report}
    assert by["Leopard 2"]["decision"] == "match" and by["Leopard 2"]["existing_name"] == "Leopard 2"
    assert by["Schakal"]["decision"] == "new"
    assert by["PATRIOT"]["decision"] == "ambiguous"
    # new-policy fields are present for curation
    assert by["Schakal"]["approved_new"] is False and by["Schakal"]["evidence"] == ""


def test_gate_rejects_approved_new_without_evidence(tmp_path: Path):
    report = [{"name": "Schakal", "suv_url": "u", "decision": "new", "existing_name": None,
               "candidates": [], "approved": True, "approved_new": False, "evidence": ""}]
    p = tmp_path / "r.yaml"
    dump_report(report, p)
    with pytest.raises(ValueError, match="Schakal"):
        load_approved(p, gate_new_creation=True)


def test_gate_accepts_approved_new_with_evidence(tmp_path: Path):
    report = [{"name": "Schakal", "suv_url": "u", "decision": "new", "existing_name": None,
               "candidates": [], "approved": True, "approved_new": True,
               "evidence": "New 2025 IFV, no existing node"}]
    p = tmp_path / "r.yaml"
    dump_report(report, p)
    approved = load_approved(p, gate_new_creation=True)
    assert len(approved) == 1 and approved[0]["name"] == "Schakal"
