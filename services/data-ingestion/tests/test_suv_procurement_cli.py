from pathlib import Path
from unittest.mock import AsyncMock

import yaml
from click.testing import CliRunner

from suv_structured.cli import cli


def test_procurements_group_registered():
    res = CliRunner().invoke(cli, ["procurements", "--help"])
    assert res.exit_code == 0
    for sub in ("fetch", "parse", "build"):
        assert sub in res.output


def test_procurements_build_refuses_without_approved(tmp_path: Path, monkeypatch):
    seed = tmp_path / "suv_procurements.yaml"
    seed.write_text('- {title: "Puma 1. Los", branch: Heer, suv_url: u}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)
    res = CliRunner().invoke(cli, ["procurements", "build"])
    assert res.exit_code != 0
    assert "approved-matches" in (res.output + str(res.exception)).lower()


def test_procurements_build_dry_run_combined_report(tmp_path: Path, monkeypatch):
    """Dry-run writes a COMBINED report: one kind=contractor entry (per split party) and
    one kind=subject entry (per matched equipment candidate), each tagged with its
    program_title. Both the org lookup and the equipment-name fetch are stubbed offline."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_procurements.yaml"
    # title contains the equipment name "Leopard 2"; contractor is a single party
    seed.write_text(
        '- {title: "Leopard 2 Kampfwertsteigerung", branch: Heer, '
        'contractor_raw: "Rheinmetall AG", suv_url: u}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)

    # the new equipment-name fetch helper: stubbed to return Leopard 2 as WEAPON_SYSTEM
    monkeypatch.setattr(cli_mod, "_fetch_equipment_node_names", AsyncMock(
        return_value=({"Leopard 2"}, {"Leopard 2": "WEAPON_SYSTEM"})))
    # _lookup_existing is called twice (contractors, subjects); return both keys
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(return_value={
        "rheinmetall ag": [("Rheinmetall AG", "ORGANIZATION", "idR")],
        "leopard 2": [("Leopard 2", "WEAPON_SYSTEM", "idL")],
    }))
    # build must not touch Qdrant on a dry-run
    monkeypatch.setattr(
        cli_mod, "QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no qdrant on dry-run")),
        raising=False,
    )

    report_out = tmp_path / "report.yaml"
    res = CliRunner().invoke(
        cli, ["procurements", "build", "--dry-run", "--report-out", str(report_out)])
    assert res.exit_code == 0, (res.output, res.exception)
    report = yaml.safe_load(report_out.read_text())
    contractor = next(e for e in report if e.get("kind") == "contractor")
    subject = next(e for e in report if e.get("kind") == "subject")
    assert contractor["name"] == "Rheinmetall AG"
    assert contractor["program_title"] == "Leopard 2 Kampfwertsteigerung"
    assert subject["name"] == "Leopard 2"
    assert subject["program_title"] == "Leopard 2 Kampfwertsteigerung"
    assert subject["target_type"] == "WEAPON_SYSTEM"


def test_procurements_build_neo4j_before_qdrant(tmp_path: Path, monkeypatch):
    """Real build (approved) writes Neo4j FIRST, then Qdrant. A shared call-order list
    proves ordering; a Qdrant point exists for the program."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_procurements.yaml"
    seed.write_text(
        '- {title: "Leopard 2 Kampfwertsteigerung", branch: Heer, '
        'contractor_raw: "Rheinmetall AG", typ: Kampfpanzer, suv_url: u}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)

    approved = tmp_path / "approved.yaml"
    approved.write_text(
        '- {name: "Rheinmetall AG", suv_url: u, decision: match, '
        'existing_name: "Rheinmetall AG", approved: true, kind: contractor, '
        'program_title: "Leopard 2 Kampfwertsteigerung"}\n'
        '- {name: "Leopard 2", suv_url: u, decision: match, existing_name: "Leopard 2", '
        'target_type: WEAPON_SYSTEM, approved: true, kind: subject, '
        'program_title: "Leopard 2 Kampfwertsteigerung"}\n')

    calls: list[str] = []
    captured: dict = {}

    async def _fake_write(statements, **kw):
        calls.append("neo4j")

    class _FakeQdrant:
        def __init__(self, *a, **k):
            pass

        def upsert(self, *, collection_name, points):
            calls.append("qdrant")
            captured["points"] = points

    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write)
    monkeypatch.setattr(cli_mod, "QdrantClient", _FakeQdrant, raising=False)
    monkeypatch.setattr(cli_mod, "embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3]))
    # Live graph: "Leopard 2" is a WEAPON_SYSTEM and "Rheinmetall AG" an ORGANIZATION, both
    # matching the approved YAML exactly under their (kind, program_title, name) composite key,
    # so the composite drift + orphan check passes cleanly. Both _lookup_existing calls
    # (contractors, subjects) consult this same dict.
    monkeypatch.setattr(cli_mod, "_fetch_equipment_node_names", AsyncMock(
        return_value=({"Leopard 2"}, {"Leopard 2": "WEAPON_SYSTEM"})))
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(return_value={
        "leopard 2": [("Leopard 2", "WEAPON_SYSTEM", "idL")],
        "rheinmetall ag": [("Rheinmetall AG", "ORGANIZATION", "idR")],
    }))

    # composite drift passes (no approved entry drifted, no orphan) + the Heer operator resolves
    # to exactly one live node → both gates are satisfied and the build proceeds to write.
    monkeypatch.setattr(cli_mod, "_procurement_operator_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 1}))

    res = CliRunner().invoke(
        cli, ["procurements", "build", "--approved-matches", str(approved)])
    assert res.exit_code == 0, (res.output, res.exception)
    assert "neo4j" in calls and "qdrant" in calls
    assert calls.index("neo4j") < calls.index("qdrant")
    titles = {p.payload["title"] for p in captured["points"]}
    assert "Leopard 2 Kampfwertsteigerung" in titles


def test_procurements_build_aborts_on_contractor_drift(tmp_path: Path, monkeypatch):
    """F-Q: an approved contractor whose target moved/vanished in the live graph since the
    dry-run → the composite (kind, program_title, name) drift check aborts BEFORE any write
    (write_neo4j never called)."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_procurements.yaml"
    seed.write_text(
        '- {title: "Leopard 2 Kampfwertsteigerung", branch: Heer, '
        'contractor_raw: "Rheinmetall AG", typ: Kampfpanzer, suv_url: u}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)

    approved = tmp_path / "approved.yaml"
    approved.write_text(
        '- {name: "Rheinmetall AG", suv_url: u, decision: match, '
        'existing_name: "Rheinmetall AG", approved: true, kind: contractor, '
        'program_title: "Leopard 2 Kampfwertsteigerung"}\n')

    calls: list[str] = []

    async def _fake_write(statements, **kw):
        calls.append("neo4j")

    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write)
    monkeypatch.setattr(
        cli_mod, "QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no qdrant on abort")),
        raising=False)
    monkeypatch.setattr(cli_mod, "embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3]))
    # LIVE graph no longer has Rheinmetall AG as an ORGANIZATION → fresh report decision
    # for the contractor becomes "new" → detect_drift flags it.
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(return_value={}))
    monkeypatch.setattr(cli_mod, "_fetch_equipment_node_names", AsyncMock(
        return_value=(set(), {})))
    # operator preflight is clean (so the abort is unambiguously the drift check)
    monkeypatch.setattr(cli_mod, "_procurement_operator_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 1}))

    res = CliRunner().invoke(
        cli, ["procurements", "build", "--approved-matches", str(approved)])
    assert res.exit_code != 0
    msg = (res.output + str(res.exception)).lower()
    assert "re-run" in msg or "drift" in msg
    assert "neo4j" not in calls  # NEVER written


def test_procurements_build_aborts_on_subject_type_drift(tmp_path: Path, monkeypatch):
    """F-Q residual: approved subject has target_type=AIRCRAFT but the live graph now types
    the same node as VESSEL.  decision=match + existing_name are unchanged (a per-name/decision
    check alone would PASS), but the stale approved target_type would make LINK_CONCERNS_SYSTEM's
    $sys_type bind nothing → graph/Qdrant divergence.  The composite drift check compares
    target_type for subjects and must abort BEFORE write_neo4j is ever called.

    subject_candidate requires len(name) >= 4, so we use "XYZW" (4 chars) as the name."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_procurements.yaml"
    # "XYZW" appears in the title so subject_candidate (>= 4 chars) picks it up
    seed.write_text(
        '- {title: "XYZW Beschaffung", branch: Heer, '
        'contractor_raw: "Rheinmetall AG", typ: Kampfpanzer, suv_url: u}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)

    approved = tmp_path / "approved.yaml"
    # Approved entry says target_type=AIRCRAFT (what the dry-run saw)
    approved.write_text(
        '- {name: "XYZW", suv_url: u, decision: match, existing_name: "XYZW", '
        'target_type: AIRCRAFT, approved: true, kind: subject, '
        'program_title: "XYZW Beschaffung"}\n')

    calls: list[str] = []

    async def _fake_write(statements, **kw):
        calls.append("neo4j")

    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write)
    monkeypatch.setattr(
        cli_mod, "QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no qdrant on abort")),
        raising=False)
    monkeypatch.setattr(cli_mod, "embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3]))

    # Live graph: "XYZW" now has type VESSEL (not AIRCRAFT as approved).
    # _fetch_equipment_node_names returns (names, type_by_name) — XYZW is VESSEL now.
    monkeypatch.setattr(cli_mod, "_fetch_equipment_node_names", AsyncMock(
        return_value=({"XYZW"}, {"XYZW": "VESSEL"})))
    # _lookup_existing: XYZW still found as VESSEL (decision=match, existing_name=XYZW unchanged).
    # This is the detect_drift PASS condition — decision+existing_name unchanged, only type drifted.
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(return_value={
        "xyzw": [("XYZW", "VESSEL", "idX")],
        "rheinmetall ag": [("Rheinmetall AG", "ORGANIZATION", "idR")],
    }))
    # Operator preflight returns exactly-1 — so the abort is unambiguously GATE 1b, not GATE 2
    monkeypatch.setattr(cli_mod, "_procurement_operator_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 1}))

    res = CliRunner().invoke(
        cli, ["procurements", "build", "--approved-matches", str(approved)])
    assert res.exit_code != 0
    msg = (res.output + str(res.exception)).lower()
    # error message must reference the type change
    assert "type" in msg
    assert "neo4j" not in calls  # write_neo4j NEVER called


def test_procurements_build_aborts_on_composite_program_drift(tmp_path: Path, monkeypatch):
    """ROOT-CAUSE repro (3rd external-review finding): the same contractor name recurs across
    programs. The approved YAML carries a STALE (contractor, Program A, "Rheinmetall AG", match)
    entry, but the current seed lists Rheinmetall ONLY under Program B (Program A's contractor
    changed to Airbus). A fresh dry-run would therefore propose (contractor, Program B,
    Rheinmetall) and (contractor, Program A, Airbus) — NOT (contractor, Program A, Rheinmetall).

    The OLD per-name detect_drift keyed the fresh report by name alone, so the stale Program-A
    Rheinmetall entry was falsely validated against the fresh Program-B Rheinmetall entry and the
    build proceeded (writing a CONTRACTED_TO edge + Qdrant link for the WRONG program). The
    composite (kind, program_title, name) drift check MUST flag the vanished Program-A pair and
    abort BEFORE any write."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_procurements.yaml"
    # Program A's contractor is now Airbus; Rheinmetall now appears only under Program B.
    seed.write_text(
        '- {title: "Program A", branch: Heer, contractor_raw: "Airbus", '
        'typ: Kampfpanzer, suv_url: a}\n'
        '- {title: "Program B", branch: Heer, contractor_raw: "Rheinmetall AG", '
        'typ: Kampfpanzer, suv_url: b}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)

    approved = tmp_path / "approved.yaml"
    # STALE: an approved Program-A Rheinmetall entry (the bug) PLUS the now-valid entries.
    approved.write_text(
        '- {name: "Rheinmetall AG", suv_url: a, decision: match, '
        'existing_name: "Rheinmetall AG", approved: true, kind: contractor, '
        'program_title: "Program A"}\n'
        '- {name: "Airbus", suv_url: a, decision: match, '
        'existing_name: "Airbus", approved: true, kind: contractor, '
        'program_title: "Program A"}\n'
        '- {name: "Rheinmetall AG", suv_url: b, decision: match, '
        'existing_name: "Rheinmetall AG", approved: true, kind: contractor, '
        'program_title: "Program B"}\n')

    calls: list[str] = []

    async def _fake_write(statements, **kw):
        calls.append("neo4j")

    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write)
    monkeypatch.setattr(
        cli_mod, "QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no qdrant on abort")),
        raising=False)
    monkeypatch.setattr(cli_mod, "embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3]))
    # Both Airbus and Rheinmetall resolve as exactly-one ORGANIZATION in the live graph,
    # so each individual name matches — the per-name detect_drift would PASS this case.
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(return_value={
        "airbus": [("Airbus", "ORGANIZATION", "idA")],
        "rheinmetall ag": [("Rheinmetall AG", "ORGANIZATION", "idR")],
    }))
    monkeypatch.setattr(cli_mod, "_fetch_equipment_node_names", AsyncMock(
        return_value=(set(), {})))
    # operator preflight clean → the abort is unambiguously the composite drift check.
    monkeypatch.setattr(cli_mod, "_procurement_operator_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 1}))

    res = CliRunner().invoke(
        cli, ["procurements", "build", "--approved-matches", str(approved)])
    assert res.exit_code != 0, (res.output, res.exception)
    msg = (res.output + str(res.exception)).lower()
    assert "fresh dry-run" in msg or "diverges" in msg
    assert "neo4j" not in calls  # NEVER written


def test_procurements_build_aborts_on_orphan_program(tmp_path: Path, monkeypatch):
    """Orphan hard-abort: an approved entry references a program_title that is no longer in
    the seed. A fresh dry-run could never re-propose it, so the build MUST abort before any
    write rather than silently dropping the edge (build_procurements only logs a warning)."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_procurements.yaml"
    seed.write_text(
        '- {title: "Leopard 2 Kampfwertsteigerung", branch: Heer, '
        'contractor_raw: "Rheinmetall AG", typ: Kampfpanzer, suv_url: u}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)

    approved = tmp_path / "approved.yaml"
    # references "Ghost Program" which is NOT in the seed
    approved.write_text(
        '- {name: "Rheinmetall AG", suv_url: g, decision: match, '
        'existing_name: "Rheinmetall AG", approved: true, kind: contractor, '
        'program_title: "Ghost Program"}\n')

    calls: list[str] = []

    async def _fake_write(statements, **kw):
        calls.append("neo4j")

    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write)
    monkeypatch.setattr(
        cli_mod, "QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no qdrant on abort")),
        raising=False)
    monkeypatch.setattr(cli_mod, "embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3]))
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(return_value={
        "rheinmetall ag": [("Rheinmetall AG", "ORGANIZATION", "idR")]}))
    monkeypatch.setattr(cli_mod, "_fetch_equipment_node_names", AsyncMock(
        return_value=(set(), {})))
    monkeypatch.setattr(cli_mod, "_procurement_operator_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 1}))

    res = CliRunner().invoke(
        cli, ["procurements", "build", "--approved-matches", str(approved)])
    assert res.exit_code != 0, (res.output, res.exception)
    msg = (res.output + str(res.exception)).lower()
    assert "ghost program" in msg and "absent" in msg
    assert "neo4j" not in calls  # NEVER written


def test_procurements_build_aborts_on_operator_preflight(tmp_path: Path, monkeypatch):
    """F-OP: a used operator that does NOT resolve to exactly one live node (here 0) →
    the exactly-1 operator preflight aborts BEFORE any write (write_neo4j never called)."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_procurements.yaml"
    seed.write_text(
        '- {title: "Leopard 2 Kampfwertsteigerung", branch: Heer, '
        'contractor_raw: "Rheinmetall AG", typ: Kampfpanzer, suv_url: u}\n')
    monkeypatch.setattr("suv_structured.cli.PROCUREMENTS_SEED", seed)

    approved = tmp_path / "approved.yaml"
    approved.write_text(
        '- {name: "Rheinmetall AG", suv_url: u, decision: match, '
        'existing_name: "Rheinmetall AG", approved: true, kind: contractor, '
        'program_title: "Leopard 2 Kampfwertsteigerung"}\n')

    calls: list[str] = []

    async def _fake_write(statements, **kw):
        calls.append("neo4j")

    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write)
    monkeypatch.setattr(
        cli_mod, "QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no qdrant on abort")),
        raising=False)
    monkeypatch.setattr(cli_mod, "embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3]))
    # contractor drift passes (live graph still has Rheinmetall AG as ORGANIZATION)
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(return_value={
        "rheinmetall ag": [("Rheinmetall AG", "ORGANIZATION", "idR")]}))
    monkeypatch.setattr(cli_mod, "_fetch_equipment_node_names", AsyncMock(
        return_value=(set(), {})))
    # the Heer operator resolves to ZERO live nodes → preflight offender → abort
    monkeypatch.setattr(cli_mod, "_procurement_operator_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 0}))

    res = CliRunner().invoke(
        cli, ["procurements", "build", "--approved-matches", str(approved)])
    assert res.exit_code != 0
    msg = (res.output + str(res.exception)).lower()
    assert "preflight" in msg or "exactly-1" in msg
    assert "neo4j" not in calls  # NEVER written
