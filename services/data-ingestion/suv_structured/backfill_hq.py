"""Backfill HEADQUARTERED_IN edges for already-written suv.report companies onto the
existing Entity{type:"LOCATION"} nodes. A SEPARATE migration — NOT a `build` re-run
(the hardened detect_drift gate would correctly abort, since the once-`new` companies
now exist). Reversible tactical bridge; see the design spec.

Reversal: MATCH ()-[r:HEADQUARTERED_IN {data_source:"suv.report"}]->() DELETE r
"""
from __future__ import annotations

import base64

import httpx
import structlog

from suv_structured.countries import to_graph_country
from suv_structured.write_templates import LINK_COMPANY_COUNTRY

log = structlog.get_logger(__name__)


def build_hq_link_statements(
    org_rows: list[tuple[str, str]],
) -> tuple[list[dict], list[tuple[str, str]]]:
    """(statements, skipped) for org rows (name, german_hq_country).
    Maps the country via to_graph_country; unmapped rows are skipped (not written)."""
    statements: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for name, hq_country in org_rows:
        loc = to_graph_country(hq_country)
        if loc:
            statements.append(
                {"statement": LINK_COMPANY_COUNTRY, "parameters": {"name": name, "country": loc}})
        else:
            skipped.append((name, hq_country))
            log.info("suv_backfill_country_unmapped", company=name, hq=hq_country)
    return statements, skipped


def unmapped_or_ambiguous_targets(counts: dict[str, int]) -> list[str]:
    """Preflight: country names whose Entity{type:"LOCATION"} target count != 1
    (0 = missing, >1 = a toLower MATCH would fan out into multiple edges)."""
    return sorted(name for name, n in counts.items() if n != 1)


async def _run_read(
    client: httpx.AsyncClient, cypher: str, params: dict,
    *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> list[dict]:
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [{"statement": cypher, "parameters": params}]},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(
            f"Neo4j read error: {data['errors'][0].get('message', data['errors'])}")
    return data["results"][0]["data"] if data.get("results") else []


async def fetch_suv_orgs(
    client: httpx.AsyncClient, *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> list[tuple[str, str]]:
    """All suv.report ORGANIZATION nodes that carry an hq_country (read-only)."""
    cypher = ('MATCH (c:Entity {type:"ORGANIZATION"}) '
              'WHERE c.data_source = "suv.report" AND c.hq_country IS NOT NULL '
              'RETURN c.name AS name, c.hq_country AS hq_country ORDER BY name')
    rows = await _run_read(client, cypher, {}, neo4j_http_url=neo4j_http_url,
                           neo4j_user=neo4j_user, neo4j_password=neo4j_password)
    return [(r["row"][0], r["row"][1]) for r in rows]


async def count_location_targets(
    client: httpx.AsyncClient, country_names: list[str],
    *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> dict[str, int]:
    """Per requested name, how many Entity{type:"LOCATION"} nodes match (case-insensitive).
    OPTIONAL MATCH guarantees a row per requested name (count 0 when none)."""
    cypher = ('UNWIND $names AS nm '
              'OPTIONAL MATCH (l:Entity {type:"LOCATION"}) WHERE toLower(l.name) = toLower(nm) '
              'RETURN nm AS name, count(l) AS n')
    rows = await _run_read(client, cypher, {"names": country_names},
                           neo4j_http_url=neo4j_http_url, neo4j_user=neo4j_user,
                           neo4j_password=neo4j_password)
    return {r["row"][0]: r["row"][1] for r in rows}
