"""Lifecycle tests for GDELT raw CLI clients."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_close_clients_releases_neo4j_qdrant_and_redis() -> None:
    from gdelt_raw.cli import _close_clients

    state = MagicMock()
    state.r = MagicMock(aclose=AsyncMock())
    neo4j = MagicMock(close=AsyncMock())
    qdrant = MagicMock(close=AsyncMock())

    await _close_clients(state, neo4j, qdrant)

    neo4j.close.assert_awaited_once()
    qdrant.close.assert_awaited_once()
    state.r.aclose.assert_awaited_once()
