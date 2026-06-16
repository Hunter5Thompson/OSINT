# suv_structured/parse.py
"""Deterministic parser: rendered SUV directory markdown -> list[Company].
No LLM, no GPU, fully reproducible. The committed YAML seed (human-reviewed) is
the quality gate; this parser is its producer. Numeric German formats are
best-effort normalized with raw-string fallback (None when ambiguous)."""
from __future__ import annotations

import re

import structlog

from suv_structured.schemas import Company

log = structlog.get_logger(__name__)

_BLOCK_RE = re.compile(r"(?m)^### ")
_FIELDS = ("Gründung", "Hauptsitz", "Geschäftsführung", "Mitarbeiterzahl",
           "Umsatz", "Beschreibung", "Produktportfolio")
_DIRECTORY_URL = "https://suv.report/sicherheits-und-verteidigungsindustrie/"

# German federal states -> Germany (HQ tail is often a Bundesland or a city/ZIP)
_DE_STATES = {"Bayern", "Rheinland-Pfalz", "Baden-Württemberg", "Hessen",
              "Nordrhein-Westfalen", "Niedersachsen", "Sachsen", "Sachsen-Anhalt",
              "Berlin", "Brandenburg", "Schleswig-Holstein", "Bremen", "Hamburg",
              "Thüringen", "Mecklenburg-Vorpommern", "Saarland"}


def _field(block: str, label: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(label)}\s*:?\s*\*\*\s*:?\s*(.+)", block)
    return m.group(1).strip() if m else None


def parse_employees(raw: str | None) -> int | None:
    """'>75' -> 75 ; '34000' -> 34000 ; '32.000 Weltweit ...' -> 32000.
    German thousands-dot; takes the FIRST integer found. None if none."""
    if not raw:
        return None
    m = re.search(r"\d[\d.]*", raw)
    if not m:
        return None
    try:
        return int(m.group(0).replace(".", ""))
    except ValueError:
        return None


def parse_revenue_eur(raw: str | None) -> float | None:
    """'4,4 Milliarden Euro (2025)' -> 4.4e9 ; '35,3 Millionen Euro (2023), 50+ ...'
    -> 35.3e6 (first figure). German comma-decimal + Millionen/Milliarden scale."""
    if not raw:
        return None
    m = re.search(r"([\d.]+(?:,\d+)?)\s*(Milliarde|Million)", raw, re.IGNORECASE)
    if not m:
        return None
    num = float(m.group(1).replace(".", "").replace(",", "."))
    scale = 1_000_000_000 if m.group(2).lower().startswith("milliard") else 1_000_000
    return num * scale


def parse_founded(raw: str | None) -> int | None:
    """'2003' / '2015 durch die Fusion ...' -> first 4-digit year."""
    if not raw:
        return None
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", raw)
    return int(m.group(1)) if m else None


def parse_products(raw: str | None) -> list[str]:
    if not raw:
        return []
    # split on commas/semicolons; trim; drop empties and trailing parenthetical notes-only
    items = [p.strip(" .") for p in re.split(r"[;,]", raw)]
    return [p for p in items if p]


def derive_hq(hauptsitz: str | None) -> tuple[str | None, str | None]:
    """(hq_city, hq_country) from a full German/foreign address tail.
    Heuristic: take the segment before the first '/'; its last comma-part is a
    Bundesland (=> Deutschland) or 'ZIP City' / a foreign country. City = the
    second-to-last comma part when present."""
    if not hauptsitz:
        return None, None
    head = hauptsitz.split("/")[0].strip()
    parts = [p.strip() for p in head.split(",") if p.strip()]
    tail = parts[-1] if parts else ""
    city = None
    country = None
    if tail in _DE_STATES:
        country = "Deutschland"
        # 'ZIP City' usually the prior part
        if len(parts) >= 2:
            city = re.sub(r"^\d{4,5}\s*", "", parts[-2]).strip() or None
    elif re.match(r"^\d{4,5}\s+\S", tail):  # 'ZIP City' as the last part -> German
        country = "Deutschland"
        city = re.sub(r"^\d{4,5}\s*", "", tail).strip() or None
    else:
        country = tail or None  # explicit foreign country, e.g. 'Niederlande'
        if len(parts) >= 2:
            city = re.sub(r"^\d{4,5}\s*", "", parts[-2]).strip() or None
    return city, country


def parse_companies(markdown: str, *, directory_url: str = _DIRECTORY_URL) -> list[Company]:
    blocks = _BLOCK_RE.split(markdown)[1:]
    out: list[Company] = []
    for b in blocks:
        name = b.split("\n", 1)[0].strip()
        if not name:
            log.warning("suv_parse_empty_name_skipped")
            continue
        hauptsitz = _field(b, "Hauptsitz")
        city, country = derive_hq(hauptsitz)
        out.append(Company(
            name=name,
            suv_url=directory_url,  # all rows on one page; anchor not exposed in fit-md
            hq_country=country,
            hq_city=city,
            employees=parse_employees(_field(b, "Mitarbeiterzahl")),
            revenue_eur=parse_revenue_eur(_field(b, "Umsatz")),
            founded=parse_founded(_field(b, "Gründung")),
            products=parse_products(_field(b, "Produktportfolio")),
            description=_field(b, "Beschreibung"),
        ))
    log.info("suv_parse_done", count=len(out))
    return out
