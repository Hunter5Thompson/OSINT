# services/data-ingestion/tests/test_suv_equipment_match_report.py
from pathlib import Path

import pytest

from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.match_report import build_match_report, dump_report, load_approved
from suv_structured.system_types import classify_system_type


def _classify(item):
    return classify_system_type(item.type_raw, item.muster)


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
    assert by["Leopard 2"]["decision"] == "match"
    assert by["Leopard 2"]["existing_name"] == "Leopard 2"
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


def test_type_aware_match_links_aircraft_and_vessel():
    rows = [
        WeaponSystemRow(muster="Eurofighter", type_raw="Kampfflugzeug", page_slug="p", suv_url="u"),
        WeaponSystemRow(muster="F123", type_raw="U-Jagd-Fregatte", page_slug="p", suv_url="u"),
        WeaponSystemRow(muster="Leopard 2", type_raw="Kampfpanzer", page_slug="p", suv_url="u"),
        WeaponSystemRow(muster="Newthing", type_raw="Kampfflugzeug", page_slug="p", suv_url="u"),
    ]
    lookup = {
        "eurofighter": [("Eurofighter", "AIRCRAFT", "id1")],
        "f123": [("F123", "VESSEL", "id2")],
        "leopard 2": [("Leopard 2", "WEAPON_SYSTEM", "id3")],
    }
    rep = build_match_report(rows, lookup, gate_new_creation=True, target_type_of=_classify)
    by = {r["name"]: r for r in rep}
    assert by["Eurofighter"]["decision"] == "match"
    assert by["Eurofighter"]["target_type"] == "AIRCRAFT"
    assert by["F123"]["decision"] == "match"
    assert by["F123"]["target_type"] == "VESSEL"
    assert by["Leopard 2"]["decision"] == "match"
    assert by["Leopard 2"]["target_type"] == "WEAPON_SYSTEM"
    assert by["Newthing"]["decision"] == "new"
    assert by["Newthing"]["target_type"] == "AIRCRAFT"


def test_wrong_type_existing_is_ambiguous():
    # an AIRCRAFT-classified system whose only existing node is a WEAPON_SYSTEM → ambiguous
    rows = [WeaponSystemRow(muster="Foo", type_raw="Kampfflugzeug", page_slug="p", suv_url="u")]
    lookup = {"foo": [("Foo", "WEAPON_SYSTEM", "id9")]}
    rep = build_match_report(rows, lookup, gate_new_creation=True, target_type_of=_classify)
    assert rep[0]["decision"] == "ambiguous"
