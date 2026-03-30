"""Tests for TEI-based reranker."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from rag.reranker import rerank


class TestReranker:
    async def test_reranks_results_by_score(self):
        """TEI reranker should reorder results by relevance score."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"index": 0, "score": 0.3},
            {"index": 1, "score": 0.9},
            {"index": 2, "score": 0.6},
        ]

        documents = [
            {"title": "Low relevance", "content": "text A", "score": 0.5},
            {"title": "High relevance", "content": "text B", "score": 0.4},
            {"title": "Mid relevance", "content": "text C", "score": 0.45},
        ]

        with patch("rag.reranker.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await rerank("military drone", documents, top_k=2)

        assert len(result) == 2
        assert result[0]["title"] == "High relevance"
        assert result[1]["title"] == "Mid relevance"

    async def test_returns_originals_on_failure(self):
        """If TEI is down, return original results unranked."""
        documents = [
            {"title": "A", "content": "text", "score": 0.5},
            {"title": "B", "content": "text", "score": 0.4},
        ]

        with patch("rag.reranker.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("TEI down")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await rerank("query", documents, top_k=2)

        assert len(result) == 2
        assert result[0]["title"] == "A"

    async def test_respects_top_k(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"index": 0, "score": 0.9},
            {"index": 1, "score": 0.8},
            {"index": 2, "score": 0.7},
        ]

        documents = [
            {"title": "A", "content": "t", "score": 0.5},
            {"title": "B", "content": "t", "score": 0.4},
            {"title": "C", "content": "t", "score": 0.3},
        ]

        with patch("rag.reranker.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await rerank("query", documents, top_k=1)

        assert len(result) == 1

    async def test_empty_input_returns_empty(self):
        result = await rerank("query", [], top_k=5)
        assert result == []
