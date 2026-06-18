"""Deterministic builder: approved weapon systems + operator seed -> Neo4j statements.

No LLM, no GPU, graph-only (Track 2a). Endpoint upserts (operator + weapon-system)
are emitted before the OPERATES link in the same transaction so the relationship
template's MATCH-ed endpoints exist."""
from __future__ import annotations

import base64

import httpx
import structlog

from canonicalize import canonicalize_entity
from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.operators import OperatorEntry
from suv_structured.system_types import classify_system_type
from suv_structured.write_templates import (
    LINK_OPERATES,
    UPSERT_OPERATOR,
    UPSERT_SYSTEM,
)

log = structlog.get_logger(__name__)


class EquipmentBuildGateError(RuntimeError):
    """Raised when the equipment --approved-matches merge gate is not satisfied."""


def dedup_systems(rows: list[WeaponSystemRow]) -> list[WeaponSystemRow]:
    """Unique weapon systems by muster (entity resolution is per system, not per
    operator-holding row). First occurrence wins."""
    seen: dict[str, WeaponSystemRow] = {}
    for r in rows:
        seen.setdefault(r.muster, r)
    return list(seen.values())


def ws_write_name(row: WeaponSystemRow, entry: dict) -> str:
    """Match -> approved existing canonical name; new -> canonicalized SUV muster."""
    if (entry.get("decision") or "").lower() == "match" and entry.get("existing_name"):
        return entry["existing_name"]
    return canonicalize_entity(row.muster, "WEAPON_SYSTEM").name


def build_equipment_statements(
    rows: list[WeaponSystemRow],
    approved: list[dict],
    operators: dict[str, OperatorEntry],
    *,
    extracted_at: str,
) -> list[dict]:
    """Build Neo4j HTTP-API statements for approved systems only. Joined by NAME
    (muster). One OPERATES edge per operator-holding row; operator + weapon-system
    upserts emitted once each, before the first link that references them."""
    approved_by_name = {e["name"]: e for e in approved}
    statements: list[dict] = []
    created_ops: set[tuple[str, str]] = set()
    upserted_ws: set[str] = set()
    for row in rows:
        entry = approved_by_name.get(row.muster)
        if entry is None:
            continue
        op = operators.get(row.page_slug)
        if op is None:
            # fail-closed: never silently drop an approved holding (the gate already
            # checks this, but the builder must not depend on the gate having run)
            raise EquipmentBuildGateError(
                f"no operator seed row for page {row.page_slug!r} (system {row.muster!r})")
        if op.decision == "create" and (op.target_name, op.target_type) not in created_ops:
            created_ops.add((op.target_name, op.target_type))
            statements.append({"statement": UPSERT_OPERATOR, "parameters": {
                "name": op.target_name, "type": op.target_type,
                "aliases": sorted(set(op.create_properties.get("aliases", []))),
                "extracted_at": extracted_at,
            }})
        ws_name = ws_write_name(row, entry)
        ws_type = classify_system_type(row.type_raw, row.muster)
        if ws_name not in upserted_ws:
            upserted_ws.add(ws_name)
            statements.append({"statement": UPSERT_SYSTEM, "parameters": {
                "name": ws_name,
                "type": ws_type,
                "aliases": sorted({row.muster, ws_name}),
                "weapon_type": row.type_raw,
                "data_source": "suv.report",
                "suv_url": row.suv_url,
                "extracted_at": extracted_at,
            }})
        statements.append({"statement": LINK_OPERATES, "parameters": {
            "op_name": op.target_name, "op_type": op.target_type,
            "ws_name": ws_name, "ws_type": ws_type,
            "count": row.count, "count_raw": row.count_raw,
            "service_end": row.service_end, "note": row.note,
            "suv_url": row.suv_url,
        }})
    log.info("suv_equipment_statements_built", statements=len(statements))
    return statements


def resolve_equipment_build_inputs(
    *, rows: list[WeaponSystemRow], operators: dict[str, OperatorEntry],
    approved: list[dict],
) -> list[dict]:
    """Enforce the gate: approved names must exist in the parsed rows, every
    referenced page must have an operator, and no two approved entries may resolve
    to the same canonical weapon-system write-name (silent merge)."""
    musters = {r.muster for r in rows}
    unknown = [e["name"] for e in approved if e["name"] not in musters]
    if unknown:
        raise EquipmentBuildGateError(f"approved report diverges from seed (unknown: {unknown})")
    # check EVERY approved-row occurrence: a system can appear on multiple pages, so a
    # one-page-per-muster map could hide a page that lacks an operator seed row.
    approved_names = {e["name"] for e in approved}
    missing_ops = sorted({r.page_slug for r in rows
                          if r.muster in approved_names and r.page_slug not in operators})
    if missing_ops:
        raise EquipmentBuildGateError(f"no operator seed row for page(s): {missing_ops}")
    by_name = {r.muster: r for r in rows}
    seen: dict[tuple[str, str], str] = {}
    collisions: list[str] = []
    for e in approved:
        row = by_name.get(e["name"])
        if row is None:
            continue
        wn = ws_write_name(row, e)
        key = (wn, classify_system_type(row.type_raw, row.muster))
        if key in seen:
            collisions.append(f"{seen[key]!r} + {e['name']!r} -> {key!r}")
        else:
            seen[key] = e["name"]
    if collisions:
        raise EquipmentBuildGateError(
            f"multiple approved entries resolve to the same canonical system: {collisions}")
    return approved


async def match_target_counts(
    operators: dict[str, OperatorEntry], client: httpx.AsyncClient,
    *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> dict[tuple[str, str], int]:
    """Live node-count per (name, type) for each `match` operator (exactly-1 preflight input)."""
    targets = sorted({(o.target_name, o.target_type)
                      for o in operators.values() if o.decision == "match"})
    if not targets:
        return {}
    cypher = ("UNWIND $pairs AS p "
              "MATCH (e:Entity {name: p.name, type: p.type}) "
              "RETURN p.name AS name, p.type AS type, count(e) AS c")
    pairs = [{"name": n, "type": t} for n, t in targets]
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [{"statement": cypher, "parameters": {"pairs": pairs}}]},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        msg = data['errors'][0].get('message', data['errors'])
        raise RuntimeError(f"Neo4j preflight error: {msg}")
    counts = {(n, t): 0 for n, t in targets}
    for row in (data["results"][0]["data"] if data.get("results") else []):
        name, etype, c = row["row"]
        counts[(name, etype)] = c
    return counts
