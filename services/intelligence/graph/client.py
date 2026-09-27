"""Async Neo4j client wrapper with read-only enforcement."""

from __future__ import annotations

import neo4j
import structlog
from neo4j import AsyncGraphDatabase

log = structlog.get_logger(__name__)


class GraphClient:
    """Thin async wrapper around the Neo4j Bolt driver.

    Requests READ_ACCESS routing for read-only queries. This is not a server-side
    authorization boundary; the Neo4j account must carry suitable read-only rights.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        query_timeout_s: float = 15.0,
    ) -> None:
        if query_timeout_s <= 0:
            raise ValueError("query_timeout_s must be positive")
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._query_timeout_s = query_timeout_s

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
            query = neo4j.Query(cypher, timeout=self._query_timeout_s)
            result = await session.run(query, params or {})
            return [dict(record) async for record in result]
