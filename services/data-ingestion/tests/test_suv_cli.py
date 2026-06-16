# tests/test_suv_cli.py
import httpx
import pytest
import yaml

from suv_structured.cli import BuildGateError, resolve_build_inputs
from suv_structured.schemas import Company


def _seed(tmp_path, companies):
    p = tmp_path / "suv_companies.yaml"
    p.write_text(yaml.safe_dump([c.model_dump() for c in companies], allow_unicode=True))
    return p


def test_build_refuses_without_approved_matches(tmp_path):
    seed = _seed(tmp_path, [Company(name="A", suv_url="ua")])
    with pytest.raises(BuildGateError, match="approved-matches"):
        resolve_build_inputs(seed_path=seed, approved_path=None)


def test_build_aborts_when_report_diverges_from_seed(tmp_path):
    seed = _seed(tmp_path, [Company(name="A", suv_url="ua")])
    report = tmp_path / "r.yaml"
    report.write_text(yaml.safe_dump([
        {"name": "GHOST", "suv_url": "uX", "decision": "new",
         "existing_name": None, "candidates": [], "approved": True}]))
    with pytest.raises(BuildGateError, match="diverge|unknown"):
        resolve_build_inputs(seed_path=seed, approved_path=report)


def test_build_returns_companies_and_approved_on_valid_gate(tmp_path):
    seed = _seed(tmp_path, [Company(name="A", suv_url="ua"), Company(name="B", suv_url="ub")])
    report = tmp_path / "r.yaml"
    report.write_text(yaml.safe_dump([
        {"name": "A", "suv_url": "ua", "decision": "new", "existing_name": None,
         "candidates": [], "approved": True},
        {"name": "B", "suv_url": "ub", "decision": "ambiguous", "existing_name": None,
         "candidates": [], "approved": False}]))
    companies, approved = resolve_build_inputs(seed_path=seed, approved_path=report)
    assert {c.name for c in companies} == {"A", "B"}
    assert {a["name"] for a in approved} == {"A"}     # only approved+unambiguous


@pytest.mark.asyncio
async def test_lookup_existing_parses_results():
    from suv_structured.cli import _lookup_existing
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        "results": [{"data": [{"row": ["rheinmetall ag", "Rheinmetall", "ORGANIZATION", "e1"]}]}],
        "errors": []}))
    async with httpx.AsyncClient(transport=transport) as client:
        out = await _lookup_existing([Company(name="Rheinmetall AG", suv_url="u")],
                                     client, "http://neo", "neo4j", "pw")
    assert out == {"rheinmetall ag": [("Rheinmetall", "ORGANIZATION", "e1")]}


@pytest.mark.asyncio
async def test_lookup_existing_raises_on_neo4j_error_body():
    from suv_structured.cli import _lookup_existing
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"results": [], "errors": [{"message": "Auth failed"}]}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="Auth failed"):
            await _lookup_existing([Company(name="X", suv_url="u")],
                                   client, "http://neo", "neo4j", "pw")
