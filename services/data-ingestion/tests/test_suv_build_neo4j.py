# tests/test_suv_build_neo4j.py
from suv_structured.build_companies import build_statements
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
