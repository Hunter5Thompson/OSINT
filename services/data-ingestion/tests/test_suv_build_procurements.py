# services/data-ingestion/tests/test_suv_build_procurements.py
from pathlib import Path

import pytest

from suv_structured.build_procurements import (
    ProcurementBuildGateError,
    _program_point_id,
    build_procurement_statements,
    subject_candidate,
)
from suv_structured.operators import load_operators
from suv_structured.procurement_schemas import ProcurementProgram

SEED = Path(__file__).parent.parent / "suv_structured" / "seeds" / "suv_operators.yaml"
OPS = load_operators(SEED)
URL = "https://suv.report/modernisierungsvorhaben/"


def _p(title, branch="Heer", contractor_raw=None):
    return ProcurementProgram(
        title=title, branch=branch, contractor_raw=contractor_raw, suv_url=URL
    )


def test_subject_candidate_longest_match():
    # equip_names is the set of EXISTING equipment node names (original case)
    equip = {"Puma", "Leopard 2", "Leopard"}
    assert subject_candidate(_p("Konsolidierte Nachrüstung Puma 1. Los"), equip) == "Puma"
    assert subject_candidate(_p("Leopard 2 A6A3 / A6A3M"), equip) == "Leopard 2"  # longest wins
    assert subject_candidate(_p("Beobachtungsausstattung III"), equip) is None


def test_program_point_id_namespaced_and_deterministic():
    a = _program_point_id("Eurofighter")
    b = _program_point_id("Eurofighter")
    c = _program_point_id("Tornado")
    assert a == b and a != c and "-" in a   # uuid5 string


def test_build_statements_program_then_edges_ordered():
    progs = [_p("Konsolidierte Nachrüstung Puma 1. Los", branch="Heer",
               contractor_raw="PSM")]
    stmts = build_procurement_statements(
        progs, OPS, approved_contractors=[], approved_subjects=[], extracted_at="t")
    kinds = [s["statement"] for s in stmts]
    prog_idx = next(
        i for i, s in enumerate(kinds)
        if 'MERGE (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})' in s
    )
    proc_idx = next(i for i, s in enumerate(kinds) if "MERGE (op)-[r:PROCURES]" in s)
    assert prog_idx < proc_idx                      # program upserted before PROCURES
    assert stmts[proc_idx]["parameters"]["op_name"] == "Deutsches Heer"


def test_build_links_approved_contractor_and_subject():
    progs = [_p("Konsolidierte Nachrüstung Puma 1. Los", branch="Heer", contractor_raw="KNDS")]
    approved_contractors = [
        {"name": "KNDS", "decision": "match", "existing_name": "KNDS",
         "program_title": "Konsolidierte Nachrüstung Puma 1. Los"},
    ]
    approved_subjects = [
        {"name": "Puma", "decision": "match", "existing_name": "Puma",
         "target_type": "WEAPON_SYSTEM",
         "program_title": "Konsolidierte Nachrüstung Puma 1. Los"},
    ]
    stmts = build_procurement_statements(
        progs, OPS, approved_contractors=approved_contractors,
        approved_subjects=approved_subjects, extracted_at="t")
    assert any(
        "MERGE (p)-[r:CONTRACTED_TO]" in s["statement"]
        and s["parameters"]["company"] == "KNDS"
        for s in stmts
    )
    assert any(
        "MERGE (p)-[r:CONCERNS_SYSTEM]" in s["statement"]
        and s["parameters"]["sys_name"] == "Puma"
        and s["parameters"]["sys_type"] == "WEAPON_SYSTEM"
        for s in stmts
    )


def test_statement_builder_is_graph_only():
    """statement builder is graph-only; Qdrant is a separate function
    (Neo4j-first ordering lives in the CLI)."""
    progs = [_p("Eurofighter", branch="Luftwaffe")]
    stmts = build_procurement_statements(
        progs, OPS, approved_contractors=[], approved_subjects=[], extracted_at="t")
    assert stmts and all(
        isinstance(s, dict) and set(s) == {"statement", "parameters"} for s in stmts
    )


def test_build_no_edge_for_non_match_decision():
    """Entries with decision != 'match' or missing existing_name must not produce edges."""
    progs = [_p("Eurofighter Tranche 4", branch="Luftwaffe", contractor_raw="Airbus")]
    # decision="create" — should NOT produce CONTRACTED_TO
    approved_contractors = [
        {"name": "Airbus", "decision": "create", "existing_name": "Airbus",
         "program_title": "Eurofighter Tranche 4"},
    ]
    # decision="match" but no existing_name — should NOT produce CONCERNS_SYSTEM
    approved_subjects = [
        {"name": "Eurofighter", "decision": "match", "existing_name": "",
         "target_type": "AIRCRAFT",
         "program_title": "Eurofighter Tranche 4"},
    ]
    stmts = build_procurement_statements(
        progs, OPS, approved_contractors=approved_contractors,
        approved_subjects=approved_subjects, extracted_at="t")
    assert not any("CONTRACTED_TO" in s["statement"] for s in stmts)
    assert not any("CONCERNS_SYSTEM" in s["statement"] for s in stmts)


def test_build_gate_error_for_unknown_branch():
    """Raise ProcurementBuildGateError when the branch has no operator mapping."""
    progs = [_p("Unknown Program", branch="UnknownBranch")]
    with pytest.raises(ProcurementBuildGateError, match="UnknownBranch"):
        build_procurement_statements(
            progs, OPS, approved_contractors=[], approved_subjects=[], extracted_at="t")


def test_program_point_id_differs_from_company_namespace():
    """Program point IDs must be namespaced separately from company point IDs."""
    from suv_structured.build_companies import _point_id as _company_point_id
    prog_id = _program_point_id("Rheinmetall")
    comp_id = _company_point_id("Rheinmetall")
    assert prog_id != comp_id


def test_build_statements_edge_ordering_within_program():
    """For a single program: UPSERT first, PROCURES second, then contractor/subject edges."""
    progs = [_p("NH90 Beschaffung", branch="Heer", contractor_raw="Airbus")]
    approved_contractors = [
        {"name": "Airbus", "decision": "match", "existing_name": "Airbus",
         "program_title": "NH90 Beschaffung"},
    ]
    approved_subjects = [
        {"name": "NH90", "decision": "match", "existing_name": "NH90",
         "target_type": "AIRCRAFT",
         "program_title": "NH90 Beschaffung"},
    ]
    stmts = build_procurement_statements(
        progs, OPS, approved_contractors=approved_contractors,
        approved_subjects=approved_subjects, extracted_at="t")
    # Find positions
    upsert_idx = next(
        i for i, s in enumerate(stmts)
        if "PROCUREMENT_PROGRAM" in s["statement"] and "MERGE (p:Entity" in s["statement"]
    )
    procures_idx = next(i for i, s in enumerate(stmts) if "PROCURES" in s["statement"])
    contracted_idx = next(i for i, s in enumerate(stmts) if "CONTRACTED_TO" in s["statement"])
    concerns_idx = next(i for i, s in enumerate(stmts) if "CONCERNS_SYSTEM" in s["statement"])
    # strict ordering: upsert < procures < contractor/subject edges
    assert upsert_idx < procures_idx < contracted_idx
    assert upsert_idx < procures_idx < concerns_idx


# ---------------------------------------------------------------------------
# Word-boundary subject_candidate tests (Fix 1)
# ---------------------------------------------------------------------------

def test_subject_candidate_no_bare_substring_tiger():
    """'Tiger' must NOT match inside 'Tigerente' — bare substring old behaviour."""
    assert subject_candidate(_p("Tigerente Programm"), {"Tiger"}) is None


def test_subject_candidate_no_bare_substring_variant_suffix():
    """'H145' must NOT match inside 'H145M' — variant-suffix false positive."""
    assert subject_candidate(_p("H145M LUH SOF"), {"H145"}) is None


def test_subject_candidate_word_boundary_positive():
    """Clean word-boundary match still works: 'H145' in 'Beschaffung H145 LUH'."""
    assert subject_candidate(_p("Beschaffung H145 LUH"), {"H145"}) == "H145"


def test_subject_candidate_longest_match_still_passes():
    """Regression: existing longest-match behaviour is preserved after word-boundary fix."""
    equip = {"Puma", "Leopard 2", "Leopard"}
    assert subject_candidate(_p("Konsolidierte Nachrüstung Puma 1. Los"), equip) == "Puma"
    assert subject_candidate(_p("Leopard 2 A6A3 / A6A3M"), equip) == "Leopard 2"
    assert subject_candidate(_p("Beobachtungsausstattung III"), equip) is None
