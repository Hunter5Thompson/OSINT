"""Cypher query templates for the graph_query tool.

Template-first approach: 8 predefined queries cover ~90% of use cases.
Each template has parameterized Cypher ($name, $limit etc.) — no string interpolation.
"""

from __future__ import annotations

import re

TEMPLATES: dict[str, dict] = {
    "entity_lookup": {
        "description": "Find an entity by name — returns properties and type",
        "cypher": (
            "MATCH (e:Entity {name: $name}) "
            "RETURN e.name AS name, e.type AS type, e.aliases AS aliases, "
            "e.confidence AS confidence, e.first_seen AS first_seen, e.last_seen AS last_seen"
        ),
        "params": ["name"],
        "defaults": {},
    },
    "one_hop": {
        "description": "Find all entities and events directly connected to an entity",
        "cypher": (
            "MATCH (e:Entity {name: $name})-[r]-(n) "
            "RETURN e.name AS source, type(r) AS relationship, "
            "n.name AS target, labels(n)[0] AS target_type "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 50},
    },
    "two_hop_network": {
        "description": "Find the 2-hop connection network around an entity",
        "cypher": (
            "MATCH path = (e:Entity {name: $name})-[*1..2]-(n) "
            "UNWIND relationships(path) AS r "
            "WITH startNode(r) AS s, type(r) AS rel, endNode(r) AS t "
            "RETURN DISTINCT s.name AS source, rel AS relationship, "
            "t.name AS target, labels(t)[0] AS target_type "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 50},
    },
    "events_by_entity": {
        "description": "Find events involving a specific entity, ordered by time",
        "cypher": (
            "MATCH (e:Entity {name: $name})<-[:INVOLVES]-(ev:Event) "
            "RETURN ev.title AS title, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp, "
            "ev.confidence AS confidence "
            "ORDER BY ev.timestamp DESC "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 20},
    },
    "event_timeline": {
        "description": "Find events at a location or in a region, ordered by time",
        "cypher": (
            "MATCH (ev:Event)-[:OCCURRED_AT]->(l:Location) "
            "WHERE l.name CONTAINS $location OR l.country CONTAINS $location "
            "RETURN ev.title AS title, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp, "
            "l.name AS location, l.country AS country "
            "ORDER BY ev.timestamp DESC "
            "LIMIT $limit"
        ),
        "params": ["location"],
        "defaults": {"limit": 30},
    },
    "co_occurring": {
        "description": "Find entities that co-occur with a given entity in the same events",
        "cypher": (
            "MATCH (e:Entity {name: $name})<-[:INVOLVES]-(ev:Event)-[:INVOLVES]->(other:Entity) "
            "WHERE other.name <> $name "
            "RETURN other.name AS entity, other.type AS type, "
            "count(ev) AS shared_events "
            "ORDER BY shared_events DESC "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 20},
    },
    "source_backed": {
        "description": "Find sources that reported on events involving an entity",
        "cypher": (
            "MATCH (e:Entity {name: $name})<-[:INVOLVES]-(ev:Event)-[:REPORTED_BY]->(s:Source) "
            "RETURN ev.title AS event, s.name AS source, s.url AS url, "
            "ev.timestamp AS timestamp "
            "ORDER BY ev.timestamp DESC "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 20},
    },
    "top_connected": {
        "description": "Find the most connected entities by relationship count",
        "cypher": (
            "MATCH (e:Entity)-[r]-() "
            "RETURN e.name AS entity, e.type AS type, count(r) AS connections "
            "ORDER BY connections DESC "
            "LIMIT $limit"
        ),
        "params": [],
        "defaults": {"limit": 20},
    },
}


def select_template(
    template_id: str, params: dict
) -> tuple[str, dict] | None:
    """Select a template by ID and merge params with defaults.

    Returns (cypher, merged_params) or None if template_id not found.
    """
    template = TEMPLATES.get(template_id)
    if template is None:
        return None

    merged = dict(template["defaults"])
    merged.update(params)
    return template["cypher"], merged


def build_cypher_from_template(template_id: str, params: dict) -> tuple[str, dict]:
    """Build Cypher from a template. Raises KeyError if template not found."""
    result = select_template(template_id, params)
    if result is None:
        raise KeyError(f"Unknown template: {template_id}")
    return result


def inject_limit(cypher: str, default_limit: int = 100) -> str:
    """Add LIMIT clause if the query doesn't already have one."""
    if re.search(r"\bLIMIT\b", cypher, re.IGNORECASE):
        return cypher
    return f"{cypher.rstrip().rstrip(';')} LIMIT {default_limit}"
