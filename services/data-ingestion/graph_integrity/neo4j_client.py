"""Async bolt client for graph-integrity jobs. Read + parametrised writes only."""
from __future__ import annotations

from typing import Any

from neo4j import AsyncGraphDatabase


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def run(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run(cypher, params or {})
            return await result.data()

    async def close(self) -> None:
        await self._driver.close()
