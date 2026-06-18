from pathlib import Path
from unittest.mock import AsyncMock

from click.testing import CliRunner

from suv_structured.cli import cli


def test_equipment_build_refuses_without_approved_matches(tmp_path: Path, monkeypatch):
    # point the seed at a tmp file so the command reaches the gate, not the missing-seed error
    seed = tmp_path / "suv_equipment.yaml"
    seed.write_text("- {muster: Leopard 2, page_slug: hauptwaffensysteme-des-heeres, suv_url: u}\n")
    monkeypatch.setattr("suv_structured.cli.EQUIPMENT_SEED", seed)
    res = CliRunner().invoke(cli, ["equipment", "build"])
    assert res.exit_code != 0
    # EquipmentBuildGateError is raised (not echoed) → check output AND exception
    assert "approved-matches" in (res.output + str(res.exception)).lower()


def test_equipment_group_registered():
    res = CliRunner().invoke(cli, ["equipment", "--help"])
    assert res.exit_code == 0
    for sub in ("fetch", "parse", "build"):
        assert sub in res.output


def test_equipment_build_happy_path_writes_no_qdrant(tmp_path: Path, monkeypatch):
    """AC6 regression: a full real build traverses the write path WITHOUT instantiating
    a QdrantClient. QdrantClient is patched to explode if touched."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_equipment.yaml"
    seed.write_text("- {muster: Leopard 2, page_slug: hauptwaffensysteme-des-heeres, suv_url: u}\n")
    approved = tmp_path / "approved.yaml"
    approved.write_text(
        '- {name: "Leopard 2", decision: match, existing_name: "Leopard 2", '
        "approved: true, approved_new: false, evidence: \"\"}\n")
    monkeypatch.setattr("suv_structured.cli.EQUIPMENT_SEED", seed)

    def _boom(*a, **k):
        raise AssertionError("QdrantClient must not be instantiated in the equipment path")
    monkeypatch.setattr(cli_mod, "QdrantClient", _boom, raising=False)

    # stub the live-graph calls so the test needs no Neo4j
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(
        return_value={"leopard 2": [("Leopard 2", "WEAPON_SYSTEM", "id1")]}))
    monkeypatch.setattr(cli_mod, "match_target_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 1}))
    captured = {}
    async def _fake_write_neo4j(statements, **kw):
        captured["stmts"] = statements
    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write_neo4j)

    res = CliRunner().invoke(cli, ["equipment", "build", "--approved-matches", str(approved)])
    assert res.exit_code == 0, (res.output, res.exception)
    assert "qdrant=0" in res.output
    # the write path produced an OPERATES link statement
    assert any("MERGE (op)-[r:OPERATES]" in s["statement"] for s in captured["stmts"])
