"""Graph exploration REST endpoints — reads from Neo4j via GraphClient."""

from __future__ import annotations

import neo4j
import structlog
from fastapi import APIRouter, Query
from neo4j import AsyncGraphDatabase

from app.config import settings
from app.models.events import GeoEvent, GeoEventsResponse
from app.models.graph import GraphEdge, GraphNode, GraphResponse

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

_driver = None


async def _get_graph_client():
    """Lazy-init async Neo4j driver."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_url,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def _read_query(cypher: str, params: dict) -> list[dict]:
    """Execute a read-only Cypher query."""
    driver = await _get_graph_client()
    async with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
        result = await session.run(cypher, params)
        return [dict(record) async for record in result]


def _cap_limit(limit: int) -> int:
    return min(max(limit, 1), 200)


@router.get("/entity/{name}", response_model=GraphResponse)
async def get_entity(name: str, limit: int = Query(default=50, le=200)) -> GraphResponse:
    """Get entity details by name."""
    limit = _cap_limit(limit)
    rows = await _read_query(
        "MATCH (e:Entity {name: $name}) "
        "RETURN e.id AS id, e.name AS name, e.type AS type, "
        "e.aliases AS aliases, e.confidence AS confidence "
        "LIMIT $limit",
        {"name": name, "limit": limit},
    )
    nodes = [
        GraphNode(
            id=r.get("id", r.get("name", "")),
            name=r.get("name", ""),
            type=r.get("type", "unknown"),
            properties={k: v for k, v in r.items() if k not in ("id", "name", "type") and v is not None},
        )
        for r in rows
    ]
    return GraphResponse(nodes=nodes, total_count=len(nodes))


@router.get("/neighbors/{name}", response_model=GraphResponse)
async def get_neighbors(
    name: str,
    limit: int = Query(default=50, le=200),
    entity_type: str | None = None,
) -> GraphResponse:
    """Get 1-hop neighbors of an entity."""
    limit = _cap_limit(limit)
    type_filter = "AND n.type = $entity_type" if entity_type else ""
    rows = await _read_query(
        f"MATCH (e:Entity {{name: $name}})-[r]-(n) "
        f"WHERE true {type_filter} "
        f"RETURN e.name AS source, type(r) AS relationship, "
        f"n.name AS target, labels(n)[0] AS target_type, "
        f"n.type AS target_subtype "
        f"LIMIT $limit",
        {"name": name, "limit": limit, "entity_type": entity_type},
    )
    nodes_map: dict[str, GraphNode] = {}
    edges = []
    nodes_map[name] = GraphNode(id=name, name=name, type="Entity")
    for r in rows:
        target = r.get("target", "")
        if target and target not in nodes_map:
            nodes_map[target] = GraphNode(
                id=target, name=target,
                type=r.get("target_subtype") or r.get("target_type", "unknown"),
            )
        edges.append(GraphEdge(
            source=name, target=target,
            relationship=r.get("relationship", "RELATED"),
        ))
    return GraphResponse(nodes=list(nodes_map.values()), edges=edges, total_count=len(rows))


@router.get("/network/{name}", response_model=GraphResponse)
async def get_network(
    name: str,
    limit: int = Query(default=50, le=200),
    entity_type: str | None = None,
) -> GraphResponse:
    """Get 2-hop network around an entity."""
    limit = _cap_limit(limit)
    type_filter = "AND t.type = $entity_type" if entity_type else ""
    rows = await _read_query(
        f"MATCH path = (e:Entity {{name: $name}})-[*1..2]-(n) "
        f"UNWIND relationships(path) AS r "
        f"WITH startNode(r) AS s, type(r) AS rel, endNode(r) AS t "
        f"WHERE true {type_filter} "
        f"RETURN DISTINCT s.name AS source, rel AS relationship, "
        f"t.name AS target, labels(t)[0] AS target_type, "
        f"t.type AS target_subtype "
        f"LIMIT $limit",
        {"name": name, "limit": limit, "entity_type": entity_type},
    )
    nodes_map: dict[str, GraphNode] = {}
    edges = []
    for r in rows:
        src = r.get("source", "")
        tgt = r.get("target", "")
        if src and src not in nodes_map:
            nodes_map[src] = GraphNode(id=src, name=src, type="Entity")
        if tgt and tgt not in nodes_map:
            nodes_map[tgt] = GraphNode(
                id=tgt, name=tgt,
                type=r.get("target_subtype") or r.get("target_type", "unknown"),
            )
        edges.append(GraphEdge(
            source=src, target=tgt,
            relationship=r.get("relationship", "RELATED"),
        ))
    return GraphResponse(nodes=list(nodes_map.values()), edges=edges, total_count=len(rows))


@router.get("/events", response_model=GraphResponse)
async def get_events(
    entity: str | None = None,
    limit: int = Query(default=30, le=200),
) -> GraphResponse:
    """Get events, optionally filtered by entity."""
    limit = _cap_limit(limit)
    if entity:
        rows = await _read_query(
            "MATCH (e:Entity {name: $entity})<-[:INVOLVES]-(ev:Event) "
            "RETURN ev.id AS id, ev.title AS name, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp "
            "ORDER BY ev.timestamp DESC LIMIT $limit",
            {"entity": entity, "limit": limit},
        )
    else:
        rows = await _read_query(
            "MATCH (ev:Event) "
            "RETURN ev.id AS id, ev.title AS name, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp "
            "ORDER BY ev.timestamp DESC LIMIT $limit",
            {"limit": limit},
        )
    nodes = [
        GraphNode(
            id=r.get("id", ""),
            name=r.get("name", ""),
            type=r.get("type", "event"),
            properties={k: v for k, v in r.items() if k not in ("id", "name", "type") and v is not None},
        )
        for r in rows
    ]
    return GraphResponse(nodes=nodes, total_count=len(nodes))


@router.get("/events/geo", response_model=GeoEventsResponse)
async def get_geo_events(
    entity: str | None = None,
    codebook_type: str | None = None,
    limit: int = Query(default=100, le=200),
) -> GeoEventsResponse:
    """Get events with resolved lat/lon from Location nodes."""
    limit = _cap_limit(limit)

    if entity:
        entity_match = "MATCH (e:Entity {name: $entity})<-[:INVOLVES]-(ev:Event) "
        params: dict = {"entity": entity, "limit": limit}
    else:
        entity_match = "MATCH (ev:Event) "
        params = {"limit": limit}

    type_filter = ""
    if codebook_type:
        type_filter = "WHERE ev.codebook_type STARTS WITH $codebook_type "
        params["codebook_type"] = codebook_type

    cypher = (
        f"{entity_match}"
        f"OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location) "
        f"{type_filter}"
        f"RETURN ev.id AS id, ev.title AS title, ev.codebook_type AS codebook_type, "
        f"ev.severity AS severity, ev.timestamp AS timestamp, "
        f"l.name AS location_name, l.country AS country, "
        f"l.lat AS lat, l.lon AS lon "
        f"ORDER BY ev.timestamp DESC LIMIT $limit"
    )

    rows = await _read_query(cypher, params)
    events = [
        GeoEvent(
            id=str(r.get("id") or ""),
            title=str(r.get("title") or ""),
            codebook_type=str(r.get("codebook_type") or ""),
            severity=str(r.get("severity") or ""),
            timestamp=str(r["timestamp"]) if r.get("timestamp") else None,
            location_name=str(r["location_name"]) if r.get("location_name") else None,
            country=str(r["country"]) if r.get("country") else None,
            lat=float(r["lat"]) if r.get("lat") is not None else None,
            lon=float(r["lon"]) if r.get("lon") is not None else None,
        )
        for r in rows
    ]
    return GeoEventsResponse(events=events, total_count=len(events))


@router.get("/search", response_model=GraphResponse)
async def search_entities(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=200),
) -> GraphResponse:
    """Search entities by name (case-insensitive contains)."""
    limit = _cap_limit(limit)
    rows = await _read_query(
        "MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($q) "
        "RETURN e.id AS id, e.name AS name, e.type AS type "
        "ORDER BY e.name LIMIT $limit",
        {"q": q, "limit": limit},
    )
    nodes = [
        GraphNode(id=r.get("id", r.get("name", "")), name=r.get("name", ""), type=r.get("type", "unknown"))
        for r in rows
    ]
    return GraphResponse(nodes=nodes, total_count=len(nodes))
