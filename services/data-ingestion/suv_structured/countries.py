# suv_structured/countries.py
"""Map SUV's German HQ-country strings onto the English names used by the graph's
geo nodes. Unknown/empty/None -> None (relation skipped + reported).

BRIDGE NOTE (2026-06-16): the mapped names (Germany/Netherlands) target the existing
dominant Entity{type:"LOCATION"} nodes via LINK_COMPANY_COUNTRY — a reversible bridge
pending the canonical-country model from graph-integrity-geo. See spec
docs/superpowers/specs/2026-06-16-suv-hq-location-bridge-backfill-design.md."""
from __future__ import annotations

import unicodedata

_DE_EN: dict[str, str] = {
    "deutschland": "Germany",
    "frankreich": "France",
    "usa": "United States",
    "vereinigte staaten": "United States",
    "vereinigtes königreich": "United Kingdom",
    "großbritannien": "United Kingdom",
    "italien": "Italy",
    "spanien": "Spain",
    "schweden": "Sweden",
    "norwegen": "Norway",
    "niederlande": "Netherlands",
    "schweiz": "Switzerland",
    "österreich": "Austria",
    "polen": "Poland",
    "israel": "Israel",
    "türkei": "Türkiye",
    "finnland": "Finland",
    "belgien": "Belgium",
    "tschechien": "Czechia",
}


def to_graph_country(name: str | None) -> str | None:
    if not name:
        return None
    return _DE_EN.get(unicodedata.normalize("NFC", name).strip().lower())
