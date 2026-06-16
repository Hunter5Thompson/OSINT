"""Read-only graph-integrity metrics. Baseline for before/after acceptance."""
from __future__ import annotations

from typing import Any

# Actor-relation allowlist — the ONLY rel types eligible for dedup.
ACTOR_RELS = [
    "ALLIED_WITH",
    "SUPPLIES_TO",
    "COMPETES_WITH",
    "MEMBER_OF",
    "OPERATES_IN",
    "TARGETS",
    "COMMANDS",
    "NEGOTIATES_WITH",
    "SANCTIONS",
]

ORPHAN_BY_LABEL = """
UNWIND $labels AS lbl
CALL (lbl) {
  MATCH (n) WHERE lbl IN labels(n)
  RETURN count(n) AS total,
         count(CASE WHEN NOT (n)--() THEN 1 END) AS orphan
}
RETURN lbl AS label, orphan, total
"""

# Labels are intentionally hardcoded to the geo-semantic labels (Event, Incident).
# located = nodes with an OCCURRED_AT to a REAL Location; (0,0) null-island
# Locations are excluded so the acceptance metric stops crediting WP-11 nodes.
GEO_COVERAGE = """
UNWIND ['Event', 'Incident'] AS lbl
CALL (lbl) {
  MATCH (n) WHERE lbl IN labels(n)
  RETURN count(n) AS total,
         count(CASE WHEN EXISTS {
           MATCH (n)-[:OCCURRED_AT]->(l:Location)
           WHERE NOT (l.lat = 0.0 AND l.lon = 0.0)
         } THEN 1 END) AS located
}
RETURN lbl AS label, located, total
"""

# Incidents whose own lat/lon disagree with the :Location they MERGEd onto —
# the WP-07 collision symptom (a name-keyed Location froze the first incident's
# coords). Read-only audit; expects 0 after the loc_key rekey repair.
COORD_DISAGREEMENT = """
MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE i.lat IS NOT NULL AND i.lon IS NOT NULL
  AND (abs(i.lat - l.lat) > 0.01 OR abs(i.lon - l.lon) > 0.01)
RETURN count(*) AS coord_disagreements
"""

# (0,0) null-island Locations and how many nodes still hang off them (WP-11).
NULL_ISLAND = """
MATCH (l:Location) WHERE l.lat = 0.0 AND l.lon = 0.0
OPTIONAL MATCH (n)-[:OCCURRED_AT]->(l)
RETURN count(DISTINCT l) AS null_island_locations, count(n) AS attached_nodes
"""

DUP_ACTOR_EDGES = """
MATCH (a)-[r]->(b)
WHERE type(r) IN $actor_rels
WITH type(r) AS rel, startNode(r) AS s, endNode(r) AS e, count(r) AS c
WHERE c > 1
RETURN rel, count(*) AS groups, sum(c - 1) AS extra
ORDER BY extra DESC
"""

REPORT_LABELS = [
    "Document",
    "GDELTDocument",
    "Event",
    "GDELTEvent",
    "Entity",
    "Theme",
    "Source",
    "Incident",
    "MilitaryAircraft",
    "Location",
]


def shape_report(
    orphans: list[dict[str, Any]],
    geo: list[dict[str, Any]],
    dup_edges: list[dict[str, Any]],
    coord_disagreements: list[dict[str, Any]] | None = None,
    null_island: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine raw query rows into one report dict (pure)."""
    return {
        "orphans": orphans,
        "geo": geo,
        "dup_edges": dup_edges,
        "coord_disagreements": coord_disagreements or [],
        "null_island": null_island or [],
    }
