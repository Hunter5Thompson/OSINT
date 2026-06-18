"""Deterministic parser: a rendered Hauptwaffensysteme sub-page (Markdown table)
-> list[WeaponSystemRow]. No LLM, no GPU. Numeric fields are best-effort
normalized with a raw-string fallback (None when no integer/year is present)."""
from __future__ import annotations

import re

import structlog
from pydantic import ValidationError

from suv_structured.equipment_schemas import WeaponSystemRow

log = structlog.get_logger(__name__)


def parse_count(raw: str | None) -> int | None:
    """'310'->310 ; '1+'->1 ; '939 in über 30 …'->939 ; '337 (189 …)'->337 ;
    '32.000'->32000 (German thousands-dot). First integer found; None if none."""
    if not raw:
        return None
    m = re.search(r"\d[\d.]*", raw)  # integers + German thousands-dot only; "320.5" → 3205 (not a concern: suv.report Anzahl are always integers)
    if not m:
        return None
    try:
        return int(m.group(0).replace(".", ""))
    except ValueError:
        return None


def parse_service_end(raw: str | None) -> int | None:
    """'2050'->2050 ; '2046 (20 Jahre)'->2046 ; 'N/A'/empty -> None. First 4-digit year."""
    if not raw:
        return None
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", raw)
    return int(m.group(1)) if m else None


def _clean(cell: str) -> str:
    """Trim whitespace and surrounding markdown bold markers from a table cell."""
    return cell.strip().strip("*").strip()


def _split_row(line: str) -> list[str]:
    """Split a markdown table line into cells, dropping the cells the surrounding
    pipes create. Returns [] for non-table lines."""
    if "|" not in line:
        return []
    cells = [c.strip() for c in line.split("|")]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def parse_weapon_systems(
    markdown: str, *, page_slug: str, suv_url: str
) -> list[WeaponSystemRow]:
    rows: list[WeaponSystemRow] = []
    for line in markdown.splitlines():
        cells = _split_row(line)
        if len(cells) < 5:
            continue
        first = _clean(cells[0])
        # skip the header row and the '| --- | --- |' separator row
        if first.lower() == "muster" or not first:
            continue
        if set(first) <= {"-", ":"}:
            continue
        try:
            rows.append(WeaponSystemRow(
                muster=first,
                type_raw=_clean(cells[1]) or None,
                count=parse_count(_clean(cells[2]) or None),
                count_raw=_clean(cells[2]) or None,
                service_end=parse_service_end(_clean(cells[3]) or None),
                note=_clean(cells[4]) or None,
                page_slug=page_slug,
                suv_url=suv_url,
            ))
        except (ValueError, ValidationError):
            log.warning("suv_equipment_row_skipped", cells=cells)
    log.info("suv_equipment_parsed", page=page_slug, count=len(rows))
    return rows
