"""Deterministic parser: rendered Modernisierungsvorhaben markdown -> list[ProcurementProgram].
No LLM. Tracks the current Teilstreitkraft branch (## heading) and assigns it to each ### program
block. Numeric fields best-effort normalized with raw-string fallback."""
from __future__ import annotations

import re

import structlog

from suv_structured.procurement_schemas import ProcurementProgram

log = structlog.get_logger(__name__)

_FIELDS = ("Typ", "Projektstatus", "Auftragnehmer", "Stückzahl", "Kosten",
           "Finanzierung", "Auslieferung", "Beschreibung")


def parse_quantity(raw: str | None) -> int | None:
    """First integer, German thousands-dot stripped. None if absent."""
    if not raw:
        return None
    m = re.search(r"\d[\d.]*", raw)
    if not m:
        return None
    try:
        return int(m.group(0).replace(".", ""))
    except ValueError:
        return None


def parse_cost_eur(raw: str | None) -> float | None:
    """'1,85 Mrd. Euro'->1.85e9 ; '35,3 Millionen Euro'->35.3e6.

    German comma-decimal + scale word."""
    if not raw:
        return None
    m = re.search(r"([\d.]+(?:,\d+)?)\s*(Mrd|Milliarde|Mio|Million)", raw, re.IGNORECASE)
    if not m:
        return None
    num = float(m.group(1).replace(".", "").replace(",", "."))
    scale = 1_000_000_000 if m.group(2).lower().startswith(("mrd", "milliard")) else 1_000_000
    return num * scale


def parse_delivery(raw: str | None) -> tuple[int | None, int | None]:
    """'2024 – 2029'->(2024,2029) ; '2025'->(2025,2025) ; 'N/A'/None->(None,None). 4-digit years."""
    if not raw:
        return None, None
    years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|20\d{2})\b", raw)]
    if not years:
        return None, None
    return years[0], years[-1]


def _field(block: str, label: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(label)}\s*:?\s*\*\*\s*:?\s*(.+)", block)
    return m.group(1).strip() if m else None


def _description(block: str) -> str | None:
    # Beschreibung label is followed by the prose on the next line(s)
    m = re.search(r"\*\*Beschreibung\s*:?\s*\*\*\s*\n+(.+)", block, re.DOTALL)
    if not m:
        return _field(block, "Beschreibung")
    return m.group(1).strip().split("\n##")[0].strip() or None


def parse_procurements(
    markdown: str, *, suv_url: str
) -> list[ProcurementProgram]:
    out: list[ProcurementProgram] = []
    branch: str | None = None
    # split on ## (branch) and ### (program) headings, keeping order
    parts = re.split(r"(?m)^(#{2,3}) (.+)$", markdown)
    # re.split with one capture group of the level + one of the title; iterate in triples
    i = 1
    while i < len(parts):
        level, title, body = parts[i], parts[i + 1].strip(), parts[i + 2]
        if level == "##":
            branch = title
        elif level == "###" and branch is not None:
            delivery_raw = _field(body, "Auslieferung")
            ds, de = parse_delivery(delivery_raw)
            try:
                out.append(ProcurementProgram(
                    title=title, branch=branch,
                    typ=_field(body, "Typ"),
                    status=_field(body, "Projektstatus"),
                    contractor_raw=_field(body, "Auftragnehmer"),
                    quantity=parse_quantity(_field(body, "Stückzahl")),
                    quantity_raw=_field(body, "Stückzahl"),
                    cost_eur=parse_cost_eur(_field(body, "Kosten")),
                    cost_raw=_field(body, "Kosten"),
                    financing=_field(body, "Finanzierung"),
                    delivery_start=ds, delivery_end=de, delivery_raw=delivery_raw,
                    description=_description(body),
                    suv_url=suv_url,
                ))
            except ValueError:
                log.warning("suv_procurement_row_skipped", title=title)
        i += 3
    log.info("suv_procurements_parsed", count=len(out))
    return out
