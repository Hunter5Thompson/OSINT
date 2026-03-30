"""Graph context injection — fetch entity neighborhoods from Neo4j via GraphClient."""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

_NEIGHBORHOOD_QUERY = """
MATCH (e:Entity {name: $name})-[r*..2]-(connected)
RETURN e.name AS e_name, e.type AS e_type,
       type(last(r)) AS rel,
       connected.name AS connected_name,
       labels(connected)[0] AS connected_type
LIMIT 20
"""


async def get_graph_context(
    entity_names: list[str],
    graph_client=None,
    max_entities: int = 5,
) -> str:
    """Fetch 1-2 hop neighborhoods for entities from Neo4j.

    Uses GraphClient (Bolt driver) with read_only=True.
    Returns a compact text block for prompt injection, or "" on failure/no client.
    """
    if not entity_names or graph_client is None:
        return ""

    all_rows: list[dict] = []
    for name in entity_names[:max_entities]:
        try:
            rows = await graph_client.run_query(
                _NEIGHBORHOOD_QUERY,
                {"name": name},
                read_only=True,
            )
            all_rows.extend(rows)
        except Exception as e:
            log.warning("graph_context_query_failed", entity=name, error=str(e))

    if not all_rows:
        return ""

    lines = []
    for row in all_rows:
        e_name = row.get("e_name", "?")
        e_type = row.get("e_type", "?")
        rel = row.get("rel", "?")
        c_name = row.get("connected_name", "?")
        c_type = row.get("connected_type", "?")
        lines.append(f"  {e_name} ({e_type}) —[{rel}]→ {c_name} ({c_type})")

    return "[Knowledge Graph Context]\n" + "\n".join(lines)
