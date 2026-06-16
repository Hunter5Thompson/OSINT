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
    """Load report; return only entries with ``approved is True``.

    The report is HUMAN-EDITED YAML, so the gate validates each approved entry
    defensively and raises ValueError (listing every offender) if any approved
    entry is unsafe to write:
      - missing a 'name' or 'decision' key,
      - has a 'decision' (case-insensitive) not in MatchDecision (operator typo),
      - is still 'ambiguous' — must be resolved (re-run dry-run) before approval,
      - is a 'match' without 'existing_name' (no merge target).
    The returned entries have their 'decision' normalized to the canonical
    lowercase value so downstream comparisons are case-robust.
    """
    entries = yaml.safe_load(path.read_text()) or []
    approved = [e for e in entries if e.get("approved") is True]
    valid = {str(d) for d in MatchDecision}
    errors: list[str] = []
    for e in approved:
        name = e.get("name", "<unnamed>")
        decision = e.get("decision")
        norm = decision.lower() if isinstance(decision, str) else None
        if "name" not in e or decision is None:
            errors.append(f"{name}: missing 'name'/'decision' key")
            continue
        if norm not in valid:
            errors.append(f"{name}: unrecognized decision {decision!r}")
            continue
        e["decision"] = norm  # canonicalize for case-robust downstream use
        if norm == str(MatchDecision.AMBIGUOUS):
            errors.append(f"{name}: approved but still ambiguous (resolve first)")
        elif norm == str(MatchDecision.MATCH) and not e.get("existing_name"):
            errors.append(f"{name}: approved match missing existing_name")
    if errors:
        raise ValueError("unsafe approved entries: " + "; ".join(errors))
    return approved
