# tests/test_suv_build_neo4j.py
import json

import httpx
import pytest

from suv_structured.build_companies import build_statements, write_neo4j
from suv_structured.schemas import Company


def _co(**kw):
    kw.setdefault("suv_url", "u")
    return Company(**kw)


def test_match_uses_approved_existing_name():
    companies = [_co(name="Rheinmetall AG", hq_country="Deutschland", products=["Leopard 2"])]
    approved = [{"name": "Rheinmetall AG", "decision": "match", "existing_name": "Rheinmetall"}]
    stmts = build_statements(companies, approved, extracted_at="2026-06-14T00:00:00+00:00")
    upserts = [s for s in stmts if "MERGE (c:Entity" in s["statement"]]
    assert upserts[0]["parameters"]["name"] == "Rheinmetall"          # approved canonical
    assert upserts[0]["parameters"]["products"] == ["Leopard 2"]
    assert "Rheinmetall AG" in upserts[0]["parameters"]["aliases"]    # SUV spelling kept as alias
    links = [s for s in stmts if "HEADQUARTERED_IN" in s["statement"]]
    assert links[0]["parameters"]["country"] == "Germany"            # DE->EN mapped


def test_new_uses_canonicalized_suv_name_and_skips_unmapped_country():
    companies = [_co(name="Skyfall GmbH", hq_country="Atlantis")]
    approved = [{"name": "Skyfall GmbH", "decision": "new", "existing_name": None}]
    stmts = build_statements(companies, approved, extracted_at="t")
    assert any(s["parameters"].get("name") == "Skyfall GmbH"
               for s in stmts if "MERGE (c:Entity" in s["statement"])
    assert not [s for s in stmts if "HEADQUARTERED_IN" in s["statement"]]  # Atlantis unmapped


def test_only_approved_companies_are_written():
    companies = [_co(name="A"), _co(name="B", suv_url="ub")]
    approved = [{"name": "A", "decision": "new", "existing_name": None}]
    stmts = build_statements(companies, approved, extracted_at="t")
    names = {s["parameters"]["name"] for s in stmts if "MERGE (c:Entity" in s["statement"]}
    assert names == {"A"}


def test_companies_sharing_suv_url_resolved_by_name():
    """REGRESSION: parse.py gives every company the same directory URL → join MUST
    be by unique name, not by colliding suv_url. With a url-join, both companies
    would get the LAST company's fields."""
    url = "https://suv.report/sicherheits-und-verteidigungsindustrie/"
    companies = [
        _co(name="Rheinmetall AG", suv_url=url, employees=34000, products=["Leopard 2"]),
        _co(name="Hensoldt", suv_url=url, employees=6500, products=["TRML-4D"]),
    ]
    approved = [
        {"name": "Rheinmetall AG", "suv_url": url, "decision": "new", "existing_name": None},
        {"name": "Hensoldt", "suv_url": url, "decision": "new", "existing_name": None},
    ]
    upserts = [s for s in build_statements(companies, approved, extracted_at="t")
               if "MERGE (c:Entity" in s["statement"]]
    by = {s["parameters"]["name"]: s["parameters"] for s in upserts}
    assert by["Rheinmetall AG"]["employees"] == 34000
    assert by["Rheinmetall AG"]["products"] == ["Leopard 2"]
    assert by["Hensoldt"]["employees"] == 6500
    assert by["Hensoldt"]["products"] == ["TRML-4D"]


@pytest.mark.asyncio
async def test_write_neo4j_posts_statements_and_succeeds():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [], "errors": []})

    stmts = [{"statement": "MERGE (c:Entity {name: $name})", "parameters": {"name": "A"}}]
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await write_neo4j(stmts, client=client, neo4j_http_url="http://neo",
                          neo4j_user="neo4j", neo4j_password="pw")
    assert captured["path"] == "/db/neo4j/tx/commit"
    assert captured["body"]["statements"] == stmts


@pytest.mark.asyncio
async def test_write_neo4j_raises_on_neo4j_errors():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"results": [], "errors": [{"message": "Constraint violation"}]}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="Constraint violation"):
            await write_neo4j([{"statement": "x", "parameters": {}}],
                              client=client, neo4j_http_url="http://neo",
                              neo4j_user="neo4j", neo4j_password="pw")


@pytest.mark.asyncio
async def test_write_neo4j_noop_on_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("write_neo4j must not POST when there are no statements")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await write_neo4j([], client=client, neo4j_http_url="http://neo",
                          neo4j_user="neo4j", neo4j_password="pw")


def test_build_statements_decision_match_is_case_insensitive():
    # defense-in-depth: an approved entry whose decision was NOT lowercased
    # (a caller that bypassed load_approved) must still resolve "MATCH" to a match.
    companies = [_co(name="Rheinmetall AG")]
    approved = [{"name": "Rheinmetall AG", "decision": "MATCH", "existing_name": "Rheinmetall"}]
    upserts = [s for s in build_statements(companies, approved, extracted_at="t")
               if "MERGE (c:Entity" in s["statement"]]
    assert upserts[0]["parameters"]["name"] == "Rheinmetall"
