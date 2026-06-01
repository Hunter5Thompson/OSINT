"""Retriever schema-preflight and GraphClient lifecycle tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

import rag.retriever as retriever


@pytest.fixture(autouse=True)
def _reset_retriever_globals():
    graph_client, validated = retriever._graph_client, retriever._schema_validated
    retriever._graph_client, retriever._schema_validated = None, False
    yield
    retriever._graph_client, retriever._schema_validated = graph_client, validated


@pytest.mark.asyncio
async def test_schema_preflight_closes_temporary_qdrant_client() -> None:
    qdrant = MagicMock(
        get_collections=AsyncMock(
            return_value=MagicMock(collections=[]),
        ),
        close=AsyncMock(),
    )
    with patch("rag.retriever.AsyncQdrantClient", return_value=qdrant):
        await retriever._ensure_schema_validated()

    qdrant.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_transient_schema_error_keeps_guard_retryable_and_closes_client() -> None:
    qdrant = MagicMock(
        get_collections=AsyncMock(side_effect=ConnectionError("boom")),
        close=AsyncMock(),
    )
    with patch("rag.retriever.AsyncQdrantClient", return_value=qdrant):
        await retriever._ensure_schema_validated()
        await retriever._ensure_schema_validated()

    assert retriever._schema_validated is False
    assert qdrant.get_collections.await_count == 2
    assert qdrant.close.await_count == 2


@pytest.mark.asyncio
async def test_close_releases_graph_client_and_resets_guard() -> None:
    graph_client = MagicMock(close=AsyncMock())
    retriever._graph_client = graph_client
    retriever._schema_validated = True

    await retriever.close()

    graph_client.close.assert_awaited_once()
    assert retriever._graph_client is None
    assert retriever._schema_validated is False


@pytest.mark.asyncio
async def test_intelligence_lifespan_closes_both_graph_clients() -> None:
    import main

    with (
        patch("main.retriever.close", new=AsyncMock()) as close_retriever,
        patch("main.shutdown_graph_client", new=AsyncMock()) as close_workflow,
    ):
        async with main.lifespan(FastAPI()):
            pass

    close_retriever.assert_awaited_once()
    close_workflow.assert_awaited_once()
