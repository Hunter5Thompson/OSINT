"""Seed taxonomy for Munin query generation.

EXPAND `ENTITIES` from real ODIN sources (Neo4j country/company/leader nodes, the event
codebook) before the full harvest run — these seeds only guarantee category coverage."""
from __future__ import annotations

# German analytical templates ({e} = entity).
TEMPLATES = [
    "Aktuelle Lagebewertung zu {e}",
    "Welche Bedrohungen gehen aktuell von {e} aus?",
    "Sicherheitspolitische Entwicklung rund um {e}",
    "Militärische und industrielle Lage: {e}",
    "Welche Risiken bestehen für {e} in den nächsten Wochen?",
    "Bewerte die jüngsten Ereignisse mit Bezug zu {e}",
]

# Seed entities per category — EXPAND from ODIN's graph + codebook before the full run.
ENTITIES: dict[str, list[str]] = {
    "country": ["Iran", "China", "Russland", "Ukraine", "Israel", "Taiwan"],
    "company": ["Rheinmetall", "Hensoldt", "KNDS", "Diehl Defence"],
    "event_type": ["Drohnenangriff", "Cyberangriff", "Truppenbewegung", "Rüstungsexport"],
}
