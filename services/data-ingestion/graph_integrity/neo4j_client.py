"""Async bolt client for graph-integrity jobs. Read + parametrised writes only."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from neo4j import AsyncGraphDatabase


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def run(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run(cypher, params or {})
            return await result.data()

    async def explain(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an EXPLAIN-only query and return a JSON-safe logical plan."""

        if not cypher.lstrip().upper().startswith("EXPLAIN "):
            raise ValueError("explain requires an EXPLAIN query")
        async with self._driver.session() as session:
            result = await session.run(cypher, params or {})
            summary = await result.consume()
        if summary.plan is None:
            raise RuntimeError("Neo4j returned no EXPLAIN plan")
        serialized = _serialize_plan(summary.plan)
        if not isinstance(serialized, dict):
            raise RuntimeError("Neo4j returned an invalid EXPLAIN plan")
        return serialized

    async def close(self) -> None:
        await self._driver.close()


def _serialize_plan(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _serialize_plan(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_serialize_plan(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value

    operator_type = getattr(value, "operator_type", None)
    arguments = getattr(value, "arguments", None)
    identifiers = getattr(value, "identifiers", None)
    children = getattr(value, "children", None)
    if operator_type is not None:
        return {
            "operator_type": str(operator_type),
            "arguments": _serialize_plan(arguments or {}),
            "identifiers": _serialize_plan(identifiers or []),
            "children": _serialize_plan(children or []),
        }
    return str(value)
