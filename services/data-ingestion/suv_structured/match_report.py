# suv_structured/match_report.py
"""Dry-run match report: classify each SUV entity against existing graph entities.

Pure classification (build_match_report) + YAML load/validate (load_approved).
The report is the human review artifact and the machine-checkable merge gate."""
from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

import yaml

from canonicalize import canonicalize_entity


class MatchDecision(StrEnum):
    MATCH = "match"        # exactly one existing entity of target_type with this name
    NEW = "new"           # no existing entity with this name
    AMBIGUOUS = "ambiguous"  # multiple matches, or a single non-target_type match


def build_match_report(
    items: list,
    lookup: dict[str, list[tuple[str, str, str]]],
    *,
    target_type: str = "ORGANIZATION",
    gate_new_creation: bool = False,
    target_type_of: Callable[[object], str] | None = None,
) -> list[dict]:
    """Classify each item against existing graph entities of its target type.

    ``target_type_of`` overrides the single ``target_type`` per item (returns the
    expected EntityType for that item) — used for type-aware equipment matching.
    When it is None the single ``target_type`` str applies to all items (companies
    path, byte-identical). ``items`` expose ``.name`` and ``.suv_url``."""
    report: list[dict] = []
    for c in items:
        tt = target_type_of(c) if target_type_of is not None else target_type
        key = c.name.strip().lower()
        rows = lookup.get(key, [])
        if not rows:
            canon = canonicalize_entity(c.name, tt).name.strip().lower()
            if canon != key:
                rows = lookup.get(canon, [])
        targets = [r for r in rows if r[1] == tt]
        if not rows:
            decision, existing = MatchDecision.NEW, None
        elif len(rows) == 1 and len(targets) == 1:
            decision, existing = MatchDecision.MATCH, targets[0][0]
        else:
            decision, existing = MatchDecision.AMBIGUOUS, None
        entry = {
            "name": c.name,
            "suv_url": c.suv_url,
            "decision": str(decision),
            "existing_name": existing,
            "candidates": [{"name": n, "type": t, "id": i} for n, t, i in rows],
            "approved": False,
        }
        if target_type_of is not None:
            entry["target_type"] = tt
        if gate_new_creation:
            entry["approved_new"] = False
            entry["evidence"] = ""
        report.append(entry)
    return report


def detect_drift(approved: list[dict], fresh_report: list[dict]) -> list[str]:
    """Names of approved entries whose freshly re-derived decision/target no longer
    matches the approved report — the graph changed since the dry-run, so writing
    them could create a wrong merge. Caller must abort and re-curate.

    Compares decision (case-insensitively) and, for matches, the existing_name target.
    An approved name missing from the fresh report is also flagged."""
    fresh_by_name = {r["name"]: r for r in fresh_report}
    drifted: list[str] = []
    for e in approved:
        fr = fresh_by_name.get(e["name"])
        if fr is None:
            drifted.append(e["name"])
            continue
        decision = (e.get("decision") or "").lower()
        target_moved = (
            fr["decision"] == str(MatchDecision.MATCH)
            and fr.get("existing_name") != e.get("existing_name")
        )
        if fr["decision"] != decision or target_moved:
            drifted.append(e["name"])
    return drifted


def dump_report(report: list[dict], path: Path) -> None:
    path.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))


def load_approved(path: Path, *, gate_new_creation: bool = False) -> list[dict]:
    """Load report; return only entries with ``approved is True``.

    Validates each approved entry defensively (see below) and raises ValueError
    listing every offender. With ``gate_new_creation`` set, an approved ``new``
    entry additionally requires ``approved_new is True`` + a non-empty ``evidence``
    string — link-existing is the default; node creation is the deliberate exception."""
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
        e["decision"] = norm
        if norm == str(MatchDecision.AMBIGUOUS):
            errors.append(f"{name}: approved but still ambiguous (resolve first)")
        elif norm == str(MatchDecision.MATCH) and not e.get("existing_name"):
            errors.append(f"{name}: approved match missing existing_name")
        elif (
            norm == str(MatchDecision.NEW)
            and gate_new_creation
            and (e.get("approved_new") is not True or not (e.get("evidence") or "").strip())
        ):
            errors.append(
                f"{name}: approved 'new' WEAPON_SYSTEM requires approved_new: true "
                "+ non-empty evidence (prefer alias curation to creating a node)"
            )
    if errors:
        raise ValueError("unsafe approved entries: " + "; ".join(errors))
    return approved
