"""Read-only graph-integrity metrics. Baseline for before/after acceptance."""
from __future__ import annotations

from typing import Any

# Actor-relation allowlist — the ONLY rel types eligible for dedup.
_ACTOR_RELS = [
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

GEO_COVERAGE = """
UNWIND ['Event', 'Incident'] AS lbl
CALL (lbl) {
  MATCH (n) WHERE lbl IN labels(n)
  RETURN count(n) AS total,
         count(CASE WHEN (n)-[:OCCURRED_AT]->(:Location) THEN 1 END) AS located
}
RETURN lbl AS label, located, total
"""

DUP_ACTOR_EDGES = f"""
MATCH (a)-[r]->(b)
WHERE type(r) IN {_ACTOR_RELS!r}
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
) -> dict[str, Any]:
    """Combine raw query rows into one report dict (pure)."""
    return {"orphans": orphans, "geo": geo, "dup_edges": dup_edges}
