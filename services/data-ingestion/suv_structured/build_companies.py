# suv_structured/build_companies.py
"""Deterministic builder: approved companies -> Neo4j statements + Qdrant points.

No LLM, no GPU. Writes only companies present (and approved) in the match report."""
from __future__ import annotations

import base64
import hashlib
import unicodedata
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import structlog
from qdrant_client.models import PointStruct

from canonicalize import canonicalize_entity
from feeds.provenance import provenance_fields
from suv_structured.countries import to_graph_country
from suv_structured.schemas import Company, profile_text
from suv_structured.write_templates import LINK_COMPANY_COUNTRY, UPSERT_COMPANY

log = structlog.get_logger(__name__)


def _write_name(company: Company, approved_entry: dict) -> str:
    """Match -> approved existing canonical name; new -> canonicalized SUV name."""
    decision_lc = (approved_entry.get("decision") or "").lower()
    if decision_lc == "match" and approved_entry.get("existing_name"):
        return approved_entry["existing_name"]
    # surface-form normalization only; node type is always overridden to ORGANIZATION
    # by UPSERT_COMPANY's MERGE key
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
        timeout=60.0,  # a full SUV batch is ~150 statements in one tx
    )
    resp.raise_for_status()
    errors = resp.json().get("errors", [])
    if errors:
        raise RuntimeError(f"Neo4j returned {len(errors)} error(s): {errors[0].get('message','')}")
    log.info("suv_neo4j_written", statements=len(statements))


SUV_QDRANT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "odin/suv_structured/odin_intel")


def _point_id(name: str) -> str:
    """Deterministic Qdrant point id keyed on the full normalized company NAME.

    Keyed on the name (not suv_url, which the SUV parser shares across all
    companies). The NFC-normalized lowercased full name preserves every
    distinguishing character (umlauts, '&', hyphens) — a lossy slug could
    collide two distinct companies onto one id and silently overwrite a point."""
    norm = unicodedata.normalize("NFC", name.strip().lower())
    if not norm:
        raise ValueError(f"company name normalized to empty string: {name!r}")
    return str(uuid.uuid5(SUV_QDRANT_NAMESPACE, f"suv_structured|{norm}"))


def build_qdrant_points(
    companies: list[Company], approved: list[dict],
    *, embed: Callable[[str], list[float]], now_iso: str | None = None,
) -> list[PointStruct]:
    """One Qdrant profile point per approved company. Joined by NAME (suv_url collides)."""
    ts = now_iso or datetime.now(UTC).isoformat()
    by_name = {c.name: c for c in companies}
    points: list[PointStruct] = []
    for entry in approved:
        company = by_name.get(entry["name"])
        if company is None:
            continue
        content = profile_text(company)
        payload = {
            "source": "suv_structured",
            **provenance_fields(source_type="dataset", provider="suv.report"),
            "ingested_at": ts,
            "title": company.name,
            "content": content,
            "entities": [{"name": company.name}],
            "url": company.suv_url,
            "content_hash": hashlib.sha256(content.encode()).hexdigest()[:24],
        }
        points.append(PointStruct(
            id=_point_id(company.name), vector=embed(content), payload=payload))
    return points


async def embed_text(text: str, *, client: httpx.AsyncClient, tei_embed_url: str) -> list[float]:
    """TEI /embed returns a list of vectors; a single string input -> one vector.
    Guards both response shapes (nested [[...]] and flat [...]) like the RSS/fulltext embed."""
    resp = await client.post(f"{tei_embed_url.rstrip('/')}/embed", json={"inputs": text})
    resp.raise_for_status()
    result = resp.json()
    return result[0] if isinstance(result[0], list) else result
