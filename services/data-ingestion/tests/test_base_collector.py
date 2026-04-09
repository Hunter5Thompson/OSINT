"""Tests for BaseCollector shared functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.base import BaseCollector


class ConcreteCollector(BaseCollector):
    """Minimal concrete implementation for testing."""

    async def collect(self) -> None:
        pass


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = ConcreteCollector(settings=mock_settings)
    return c


def test_content_hash_deterministic(collector):
    h1 = collector._content_hash("hello", "world")
    h2 = collector._content_hash("hello", "world")
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex


def test_content_hash_case_insensitive(collector):
    h1 = collector._content_hash("Hello", "World")
    h2 = collector._content_hash("hello", "world")
    assert h1 == h2


def test_point_id_from_hash(collector):
    chash = collector._content_hash("test")
    pid = collector._point_id(chash)
    assert isinstance(pid, int)
    assert pid > 0


def test_content_hash_different_inputs(collector):
    h1 = collector._content_hash("a", "b")
    h2 = collector._content_hash("c", "d")
    assert h1 != h2


@pytest.mark.asyncio
async def test_dedup_check_returns_false_for_new(collector):
    collector.qdrant.retrieve.return_value = []
    result = await collector._dedup_check(12345)
    assert result is False


@pytest.mark.asyncio
async def test_dedup_check_returns_true_for_existing(collector):
    collector.qdrant.retrieve.return_value = [MagicMock()]
    result = await collector._dedup_check(12345)
    assert result is True


@pytest.mark.asyncio
async def test_batch_upsert_empty_list_noop(collector):
    await collector._batch_upsert([])
    collector.qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_batch_upsert_calls_qdrant(collector):
    points = [MagicMock()]
    await collector._batch_upsert(points)
    collector.qdrant.upsert.assert_called_once()
