# tests/test_suv_match_report.py
import pytest
import yaml

from suv_structured.match_report import (
    MatchDecision,
    build_match_report,
    detect_drift,
    load_approved,
)
from suv_structured.schemas import Company


def _co(name, url="u"):
    return Company(name=name, suv_url=url)


def test_classifies_new_match_and_ambiguous():
    companies = [_co("Rheinmetall AG"), _co("Hensoldt"), _co("Diehl")]
    lookup = {
        "rheinmetall ag": [("Rheinmetall", "ORGANIZATION", "e1")],   # single org -> match
        "hensoldt": [],                                              # none -> new
        "diehl": [("Diehl", "ORGANIZATION", "e2"),
                  ("Diehl", "PERSON", "e3")],                        # multiple -> ambiguous
    }
    report = build_match_report(companies, lookup)
    by_name = {r["name"]: r for r in report}
    assert by_name["Rheinmetall AG"]["decision"] == MatchDecision.MATCH
    assert by_name["Rheinmetall AG"]["existing_name"] == "Rheinmetall"
    assert by_name["Hensoldt"]["decision"] == MatchDecision.NEW
    assert by_name["Diehl"]["decision"] == MatchDecision.AMBIGUOUS
    assert all(r["approved"] is False for r in report)


def test_type_mismatch_single_nonorg_is_ambiguous():
    report = build_match_report([_co("Airbus")],
                                {"airbus": [("Airbus", "PERSON", "e9")]})
    assert report[0]["decision"] == MatchDecision.AMBIGUOUS


def test_load_approved_keeps_only_approved_match_and_new(tmp_path):
    report = [
        {"name": "A", "suv_url": "ua", "decision": "match", "existing_name": "A0",
         "candidates": [], "approved": True},
        {"name": "B", "suv_url": "ub", "decision": "new", "existing_name": None,
         "candidates": [], "approved": True},
        {"name": "C", "suv_url": "uc", "decision": "ambiguous", "existing_name": None,
         "candidates": [], "approved": False},
    ]
    p = tmp_path / "match_report.yaml"
    p.write_text(yaml.safe_dump(report))
    approved = load_approved(p)
    assert {a["name"] for a in approved} == {"A", "B"}


def test_load_approved_rejects_approved_but_ambiguous(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "C", "suv_url": "uc", "decision": "ambiguous", "existing_name": None,
         "candidates": [], "approved": True}]))
    with pytest.raises(ValueError):
        load_approved(p)


def test_load_approved_rejects_uppercase_ambiguous(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "C", "suv_url": "uc", "decision": "AMBIGUOUS", "existing_name": None,
         "candidates": [], "approved": True}]))
    with pytest.raises(ValueError):
        load_approved(p)


def test_load_approved_rejects_match_without_existing_name(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "M", "suv_url": "um", "decision": "match", "existing_name": None,
         "candidates": [], "approved": True}]))
    with pytest.raises(ValueError):
        load_approved(p)


def test_load_approved_rejects_unknown_decision(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "X", "suv_url": "ux", "decision": "maybe", "existing_name": None,
         "candidates": [], "approved": True}]))
    with pytest.raises(ValueError):
        load_approved(p)


def test_load_approved_rejects_missing_decision_key(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "Y", "suv_url": "uy", "existing_name": None,
         "candidates": [], "approved": True}]))
    with pytest.raises(ValueError):
        load_approved(p)


def test_load_approved_normalizes_decision_case(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "N", "suv_url": "un", "decision": "NEW", "existing_name": None,
         "candidates": [], "approved": True}]))
    approved = load_approved(p)
    assert approved[0]["decision"] == "new"


def test_detect_drift_none_when_report_matches_fresh():
    approved = [{"name": "A", "decision": "match", "existing_name": "X"},
                {"name": "B", "decision": "new", "existing_name": None}]
    fresh = [{"name": "A", "decision": "match", "existing_name": "X"},
             {"name": "B", "decision": "new", "existing_name": None}]
    assert detect_drift(approved, fresh) == []


def test_detect_drift_flags_new_became_ambiguous():
    approved = [{"name": "A", "decision": "new", "existing_name": None}]
    fresh = [{"name": "A", "decision": "ambiguous", "existing_name": None}]
    assert detect_drift(approved, fresh) == ["A"]


def test_detect_drift_flags_match_target_moved():
    approved = [{"name": "A", "decision": "match", "existing_name": "X"}]
    fresh = [{"name": "A", "decision": "match", "existing_name": "Y"}]
    assert detect_drift(approved, fresh) == ["A"]


def test_detect_drift_flags_missing_from_fresh():
    approved = [{"name": "A", "decision": "new", "existing_name": None}]
    assert detect_drift(approved, []) == ["A"]
