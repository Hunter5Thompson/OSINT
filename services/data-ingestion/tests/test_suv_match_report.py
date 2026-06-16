# tests/test_suv_match_report.py
from suv_structured.match_report import MatchDecision, build_match_report, load_approved
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
    import yaml
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
    import pytest
    import yaml
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump([
        {"name": "C", "suv_url": "uc", "decision": "ambiguous", "existing_name": None,
         "candidates": [], "approved": True}]))
    with pytest.raises(ValueError):
        load_approved(p)
