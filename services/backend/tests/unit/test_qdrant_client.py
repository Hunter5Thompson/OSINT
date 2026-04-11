"""Tests for the lazy Qdrant client getter."""

from unittest.mock import patch

import pytest

from app.services import qdrant_client as qc


@pytest.mark.asyncio
async def test_get_qdrant_client_returns_singleton() -> None:
    """Second call returns the same instance — module-level cache."""
    qc._client = None  # reset module state
    with patch("app.services.qdrant_client.AsyncQdrantClient") as mock_cls:
        mock_cls.return_value = object()
        first = await qc.get_qdrant_client()
        second = await qc.get_qdrant_client()
        assert first is second
        assert mock_cls.call_count == 1
