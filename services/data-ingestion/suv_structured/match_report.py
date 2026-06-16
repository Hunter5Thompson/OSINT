# suv_structured/match_report.py
"""Dry-run match report: classify each SUV company against existing graph entities.

Pure classification (build_match_report) + YAML load/validate (load_approved).
The report is the human review artifact and the machine-checkable merge gate."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml

from suv_structured.schemas import Company


class MatchDecision(StrEnum):
    MATCH = "match"        # exactly one existing ORGANIZATION with this name
    NEW = "new"           # no existing entity with this name
    AMBIGUOUS = "ambiguous"  # multiple matches, or a single non-ORGANIZATION match


def build_match_report(
    companies: list[Company],
    lookup: dict[str, list[tuple[str, str, str]]],
) -> list[dict]:
    """lookup maps lowercased company name -> [(existing_name, type, elementId), ...]."""
    report: list[dict] = []
    for c in companies:
        rows = lookup.get(c.name.strip().lower(), [])
        orgs = [r for r in rows if r[1] == "ORGANIZATION"]
        if not rows:
            decision, existing = MatchDecision.NEW, None
        elif len(rows) == 1 and len(orgs) == 1:
            decision, existing = MatchDecision.MATCH, orgs[0][0]
        else:
            decision, existing = MatchDecision.AMBIGUOUS, None
        report.append({
            "name": c.name,
            "suv_url": c.suv_url,
            "decision": str(decision),
            "existing_name": existing,
            "candidates": [{"name": n, "type": t, "id": i} for n, t, i in rows],
            "approved": False,
        })
    return report


def dump_report(report: list[dict], path: Path) -> None:
    path.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))


def load_approved(path: Path) -> list[dict]:
    """Load report; return only approved entries. Raises if an approved entry is
    still ambiguous (a human must resolve ambiguity before approving)."""
    entries = yaml.safe_load(path.read_text()) or []
    approved = [e for e in entries if e.get("approved") is True]
    bad = [e["name"] for e in approved if e.get("decision") == str(MatchDecision.AMBIGUOUS)]
    if bad:
        raise ValueError(f"approved but still ambiguous (resolve first): {bad}")
    return approved
