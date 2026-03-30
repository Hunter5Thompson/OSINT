"""Async Neo4j client wrapper with read-only enforcement."""

from __future__ import annotations

import neo4j
from neo4j import AsyncGraphDatabase
import structlog

log = structlog.get_logger(__name__)


class GraphClient:
    """Thin async wrapper around the Neo4j Bolt driver.

    Enforces READ_ACCESS at the Neo4j session level for read-only queries
    (defense-in-depth layer 2, complementing validate_cypher_readonly).
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self) -> None:
        await self._driver.close()

    async def run_query(
        self,
        cypher: str,
        params: dict | None = None,
        read_only: bool = False,
    ) -> list[dict]:
        session_kwargs = {}
        if read_only:
            session_kwargs["default_access_mode"] = neo4j.READ_ACCESS

        async with self._driver.session(**session_kwargs) as session:
            result = await session.run(cypher, params or {})
            return [dict(record) async for record in result]
