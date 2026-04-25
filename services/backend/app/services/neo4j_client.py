"""Shared Neo4j async driver + read/write query helpers."""

from typing import Any

import neo4j
from neo4j import AsyncGraphDatabase

from app.config import settings

_driver: neo4j.AsyncDriver | None = None


async def get_graph_client() -> neo4j.AsyncDriver:
    """Lazy-init async Neo4j driver."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_url,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def read_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute a read-only Cypher query."""
    driver = await get_graph_client()
    async with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
        result = await session.run(cypher, params)
        return [dict(record) async for record in result]


async def write_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute a parametrised write Cypher query and return any RETURNed rows."""
    driver = await get_graph_client()
    async with driver.session(default_access_mode=neo4j.WRITE_ACCESS) as session:
        result = await session.run(cypher, params)
        return [dict(record) async for record in result]
