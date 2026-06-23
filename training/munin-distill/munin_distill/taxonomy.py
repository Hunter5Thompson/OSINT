"""Taxonomy for Munin query generation.

Entities are simple nouns (countries + defence companies) that fit every template cleanly —
avoids German preposition/article grammar issues. ~62 entities x 8 templates = ~496 combos,
enough for the full ~455-query harvest. Thin-coverage entities yield thinner (still valid)
training examples that the quality filter drops; well-covered ones dominate.

Expand further from real ODIN sources (Neo4j Country/Organization nodes, the event codebook)
if you want the harvest to track the corpus's actual coverage more tightly."""
from __future__ import annotations

# German analytical templates ({e} = entity). All read naturally with a bare noun entity.
TEMPLATES = [
    "Aktuelle Lagebewertung zu {e}",
    "Welche Bedrohungen gehen aktuell von {e} aus?",
    "Sicherheitspolitische Entwicklung rund um {e}",
    "Militärische und industrielle Lage: {e}",
    "Welche Risiken bestehen für {e} in den nächsten Wochen?",
    "Bewerte die jüngsten Ereignisse mit Bezug zu {e}",
    "Aktuelle Bedrohungslage im Zusammenhang mit {e}",
    "Strategische Einschätzung zu {e}",
]

_COUNTRIES = [
    "Iran", "China", "Russland", "Ukraine", "Israel", "Taiwan", "USA", "Nordkorea",
    "Syrien", "Libanon", "Jemen", "Saudi-Arabien", "Türkei", "Indien", "Pakistan",
    "Afghanistan", "Irak", "Ägypten", "Libyen", "Sudan", "Äthiopien", "Mali", "Niger",
    "Venezuela", "Nordkorea", "Südkorea", "Japan", "Deutschland", "Frankreich",
    "Polen", "Finnland", "Schweden", "Litauen", "Estland", "Rumänien", "Serbien",
    "Aserbaidschan", "Armenien", "Georgien", "Belarus", "Katar", "Vereinigte Arabische Emirate",
]

_COMPANIES = [
    "Rheinmetall", "Hensoldt", "KNDS", "Diehl Defence", "Airbus Defence and Space",
    "Thales", "Leonardo", "BAE Systems", "Lockheed Martin", "RTX (Raytheon)", "Saab",
    "Kongsberg", "MBDA", "Boeing Defense", "Northrop Grumman", "General Dynamics",
    "Anduril", "Palantir", "Babcock", "Naval Group",
]

# de-dup while preserving order (Nordkorea appears twice above intentionally caught here)
def _dedup(seq: list[str]) -> list[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


ENTITIES: dict[str, list[str]] = {
    "country": _dedup(_COUNTRIES),
    "company": _dedup(_COMPANIES),
}
