"""Deterministic builder: parsed programs + curated contractor/subject matches -> Neo4j statements
+ Qdrant points. Programs are always written (PROCUREMENT_PROGRAM, MERGE on title). PROCURES uses
the branch operator. CONTRACTED_TO / CONCERNS_SYSTEM are emitted only for approved match entries
(link-only; no node creation). Endpoint upserts precede the relationship links in tx order."""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from collections.abc import Callable

import structlog
from qdrant_client.models import PointStruct

from feeds.provenance import provenance_fields
from suv_structured.build_companies import SUV_QDRANT_NAMESPACE
from suv_structured.operators import OperatorEntry, operator_for_branch
from suv_structured.procurement_schemas import ProcurementProgram, profile_text
from suv_structured.write_templates import (
    LINK_CONCERNS_SYSTEM,
    LINK_CONTRACTED_TO,
    LINK_PROCURES,
    UPSERT_PROCUREMENT_PROGRAM,
)

log = structlog.get_logger(__name__)


class ProcurementBuildGateError(RuntimeError):
    """Raised when the procurement --approved-matches gate is not satisfied."""


def subject_candidate(program: ProcurementProgram, equip_names: set[str]) -> str | None:
    """Longest existing equipment node name (original case in equip_names) matching
    on word boundaries (case-insensitive) in title+typ; None if no name of length >= 4 matches.
    Word-boundary match prevents 'Tiger' matching inside 'Tigerente' or 'H145' inside 'H145M'."""
    text = f"{program.title} {program.typ or ''}"
    best: str | None = None
    for name in equip_names:
        if len(name) < 4:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE) and (
            best is None or len(name) > len(best)
        ):
            best = name
    return best


def _program_point_id(title: str) -> str:
    """uuid5 namespaced under SUV_QDRANT_NAMESPACE with a procurement-specific key prefix,
    so program IDs are always distinct from company point IDs (which use 'suv_structured|...')."""
    norm = unicodedata.normalize("NFC", title.strip().lower())
    if not norm:
        raise ValueError(f"program title normalized to empty string: {title!r}")
    return str(uuid.uuid5(SUV_QDRANT_NAMESPACE, f"suv_procurement_program|{norm}"))


def build_procurement_statements(
    programs: list[ProcurementProgram],
    operators: list[OperatorEntry],
    *,
    approved_contractors: list[dict],
    approved_subjects: list[dict],
    extracted_at: str,
) -> list[dict]:
    """Program upserts + PROCURES (operator) for every program, then CONTRACTED_TO /
    CONCERNS_SYSTEM for approved match entries (keyed to their program by 'program_title').

    Statement ordering per program (invariant — CLI relies on it for Neo4j-first execution):
      1. UPSERT_PROCUREMENT_PROGRAM
      2. LINK_PROCURES  (always present; gate error if no operator)
      3. LINK_CONTRACTED_TO  (one per approved match contractor entry)
      4. LINK_CONCERNS_SYSTEM  (one per approved match subject entry)

    Approved = decision == "match" AND existing_name non-empty. All other entries are silently
    skipped (create / skip / missing existing_name produce no edge).
    """
    # Index approved entries by program_title, filtering to match-only
    contractors_by_prog: dict[str, list[dict]] = {}
    for e in approved_contractors:
        if (e.get("decision") or "").lower() == "match" and e.get("existing_name"):
            contractors_by_prog.setdefault(e["program_title"], []).append(e)

    subjects_by_prog: dict[str, list[dict]] = {}
    for e in approved_subjects:
        if (e.get("decision") or "").lower() == "match" and e.get("existing_name"):
            subjects_by_prog.setdefault(e["program_title"], []).append(e)

    # Warn on approved match entries whose program_title has no corresponding program
    program_titles = {p.title for p in programs}
    for prog_title in set(contractors_by_prog) | set(subjects_by_prog):
        if prog_title not in program_titles:
            log.warning(
                "suv_procurement_approved_orphan",
                program_title=prog_title,
                msg="approved match entry references unknown program — no edge will be written",
            )

    statements: list[dict] = []
    for p in programs:
        # 1. UPSERT — always first (endpoint must exist before relationships)
        statements.append({
            "statement": UPSERT_PROCUREMENT_PROGRAM,
            "parameters": {
                "title": p.title,
                "branch": p.branch,
                "typ": p.typ,
                "status": p.status,
                "quantity": p.quantity,
                "quantity_raw": p.quantity_raw,
                "cost_eur": p.cost_eur,
                "cost_raw": p.cost_raw,
                "financing": p.financing,
                "delivery_start": p.delivery_start,
                "delivery_end": p.delivery_end,
                "delivery_raw": p.delivery_raw,
                "description": p.description,
                "contractor_raw": p.contractor_raw,
                "suv_url": p.suv_url,
                "extracted_at": extracted_at,
            },
        })

        # 2. PROCURES — always present (gate error if branch unmapped)
        op = operator_for_branch(p.branch, operators)
        if op is None:
            raise ProcurementBuildGateError(
                f"no operator for branch {p.branch!r} (program {p.title!r})"
            )
        statements.append({
            "statement": LINK_PROCURES,
            "parameters": {
                "op_name": op.target_name,
                "op_type": op.target_type,
                "title": p.title,
            },
        })

        # 3. CONTRACTED_TO — approved matches only
        for e in contractors_by_prog.get(p.title, []):
            statements.append({
                "statement": LINK_CONTRACTED_TO,
                "parameters": {
                    "title": p.title,
                    "company": e["existing_name"],
                },
            })

        # 4. CONCERNS_SYSTEM — approved matches only
        for e in subjects_by_prog.get(p.title, []):
            statements.append({
                "statement": LINK_CONCERNS_SYSTEM,
                "parameters": {
                    "title": p.title,
                    "sys_name": e["existing_name"],
                    "sys_type": e["target_type"],
                },
            })

    log.info("suv_procurement_statements_built", statements=len(statements))
    return statements


def build_qdrant_points(
    programs: list[ProcurementProgram],
    *,
    contractor_links: dict[str, list[str]],
    system_links: dict[str, list[str]],
    embed: Callable[[str], list[float]],
    now_iso: str,
) -> list[PointStruct]:
    """One profile point per program. Neo4j-first ordering is enforced by the CALLER (CLI).

    contractor_links: program_title -> [approved company name, ...]
    system_links:     program_title -> [approved system name, ...]
    embed:            callable(text: str) -> list[float]
    """
    points: list[PointStruct] = []
    for p in programs:
        content = profile_text(p)
        ents = [p.title, *contractor_links.get(p.title, []), *system_links.get(p.title, [])]
        payload = {
            "source": "suv_structured",
            **provenance_fields(source_type="dataset", provider="suv.report"),
            "title": p.title,
            "content": content,
            "url": p.suv_url,
            "entities": [{"name": e} for e in ents],
            "program_status": p.status,
            "program_type": p.typ,
            "quantity": p.quantity,
            "cost_eur": p.cost_eur,
            "financing": p.financing,
            "delivery": p.delivery_raw,
            "content_hash": hashlib.sha256(content.encode()).hexdigest()[:24],
            "ingested_at": now_iso,
        }
        points.append(
            PointStruct(
                id=_program_point_id(p.title),
                vector=embed(content),
                payload=payload,
            )
        )
    return points
