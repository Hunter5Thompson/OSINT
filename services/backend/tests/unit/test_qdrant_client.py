"""Tests for the lazy Qdrant client getter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import qdrant_client as qc


@pytest.fixture(autouse=True)
def _reset_globals():
    client, validated = qc._client, qc._schema_validated
    qc._client, qc._schema_validated = None, False
    yield
    qc._client, qc._schema_validated = client, validated


@pytest.mark.asyncio
async def test_get_qdrant_client_returns_singleton() -> None:
    """Second call returns the same instance — module-level cache."""
    with patch("app.services.qdrant_client.AsyncQdrantClient") as mock_cls:
        mock_cls.return_value = MagicMock(
            get_collections=AsyncMock(
                return_value=MagicMock(collections=[]),
            ),
        )
        first = await qc.get_qdrant_client()
        second = await qc.get_qdrant_client()
        assert first is second
        assert mock_cls.call_count == 1


@pytest.mark.asyncio
async def test_transient_error_keeps_guard_retryable() -> None:
    client = MagicMock(
        get_collections=AsyncMock(side_effect=ConnectionError("boom")),
    )
    with patch("app.services.qdrant_client.AsyncQdrantClient", return_value=client):
        await qc.get_qdrant_client()
        assert qc._schema_validated is False
        await qc.get_qdrant_client()

    assert client.get_collections.await_count == 2


@pytest.mark.asyncio
async def test_close_qdrant_client_releases_and_resets_singleton() -> None:
    client = MagicMock(close=AsyncMock())
    qc._client = client
    qc._schema_validated = True

    await qc.close_qdrant_client()

    client.close.assert_awaited_once()
    assert qc._client is None
    assert qc._schema_validated is False
