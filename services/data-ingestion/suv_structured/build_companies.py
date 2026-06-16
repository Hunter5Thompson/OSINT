# suv_structured/build_companies.py
"""Deterministic builder: approved companies -> Neo4j statements + Qdrant points.

No LLM, no GPU. Writes only companies present (and approved) in the match report."""
from __future__ import annotations

import base64

import httpx
import structlog

from canonicalize import canonicalize_entity
from suv_structured.countries import to_graph_country
from suv_structured.schemas import Company
from suv_structured.write_templates import LINK_COMPANY_COUNTRY, UPSERT_COMPANY

log = structlog.get_logger(__name__)


def _write_name(company: Company, approved_entry: dict) -> str:
    """Match -> approved existing canonical name; new -> canonicalized SUV name."""
    if approved_entry.get("decision") == "match" and approved_entry.get("existing_name"):
        return approved_entry["existing_name"]
    return canonicalize_entity(company.name, "ORGANIZATION").name


def build_statements(
    companies: list[Company], approved: list[dict], *, extracted_at: str
) -> list[dict]:
    """Build Neo4j HTTP-API statements for approved companies only.

    Companies are joined to approved entries by NAME (the unique key). The SUV
    parser assigns the same directory URL to every company, so suv_url is NOT a
    usable join key (it collides across all rows)."""
    by_name = {c.name: c for c in companies}
    statements: list[dict] = []
    for entry in approved:
        company = by_name.get(entry["name"])
        if company is None:
            log.warning("suv_build_approved_without_company", entry=entry)
            continue
        name = _write_name(company, entry)
        aliases = sorted({company.name, name, *company.aliases})
        statements.append({
            "statement": UPSERT_COMPANY,
            "parameters": {
                "name": name,
                "aliases": aliases,
                "hq_country": company.hq_country,
                "hq_city": company.hq_city,
                "employees": company.employees,
                "revenue_eur": company.revenue_eur,
                "founded": company.founded,
                "website": company.website,
                "products": company.products,
                "suv_url": company.suv_url,
                "extracted_at": extracted_at,
            },
        })
        country = to_graph_country(company.hq_country)
        if country:
            statements.append({
                "statement": LINK_COMPANY_COUNTRY,
                "parameters": {"name": name, "country": country},
            })
        else:
            log.info("suv_country_unmapped", company=name, hq=company.hq_country)
    return statements


async def write_neo4j(
    statements: list[dict], *, client: httpx.AsyncClient,
    neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> None:
    if not statements:
        return
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": statements},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        timeout=60.0,
    )
    resp.raise_for_status()
    errors = resp.json().get("errors", [])
    if errors:
        raise RuntimeError(f"Neo4j returned {len(errors)} error(s): {errors[0].get('message','')}")
    log.info("suv_neo4j_written", statements=len(statements))
