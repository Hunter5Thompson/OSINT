"""Tests for enhanced retriever pipeline: dense → rerank → graph context."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


class TestEnhancedSearch:
    async def test_dense_only_when_all_flags_disabled(self):
        """With all flags off, enhanced_search behaves like basic search."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "Result 1", "content": "text 1", "score": 0.9},
            {"title": "Result 2", "content": "text 2", "score": 0.7},
        ])

        with patch("rag.retriever.search", mock_search):
            results = await enhanced_search(
                "test query",
                enable_hybrid=False,
                enable_rerank=False,
                enable_graph_context=False,
            )

        assert len(results) == 2
        assert results[0]["title"] == "Result 1"
        mock_search.assert_called_once()

    async def test_rerank_reorders_results(self):
        """With rerank enabled, results should be reordered by TEI scores."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "Dense top", "content": "text A", "score": 0.9},
            {"title": "Dense second", "content": "text B", "score": 0.7},
        ])

        mock_rerank = AsyncMock(return_value=[
            {"title": "Dense second", "content": "text B", "score": 0.7, "rerank_score": 0.95},
            {"title": "Dense top", "content": "text A", "score": 0.9, "rerank_score": 0.4},
        ])

        with patch("rag.retriever.search", mock_search), \
             patch("rag.retriever._rerank_fn", mock_rerank):
            results = await enhanced_search(
                "test query",
                enable_hybrid=False,
                enable_rerank=True,
                enable_graph_context=False,
            )

        assert results[0]["title"] == "Dense second"  # reranked to top
        mock_rerank.assert_called_once()

    async def test_graph_context_appended(self):
        """With graph context enabled, results include graph_context field."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "NATO expansion", "content": "NATO text", "score": 0.9,
             "entities": [{"name": "NATO", "type": "organization"}]},
        ])

        mock_graph_ctx = AsyncMock(
            return_value="[Knowledge Graph Context]\n  NATO (organization) —[INVOLVES]→ Ukraine (Event)"
        )

        with patch("rag.retriever.search", mock_search), \
             patch("rag.retriever._graph_context_fn", mock_graph_ctx):
            results = await enhanced_search(
                "NATO",
                enable_hybrid=False,
                enable_rerank=False,
                enable_graph_context=True,
            )

        assert "graph_context" in results[0]
        assert "NATO" in results[0]["graph_context"]
        mock_graph_ctx.assert_called_once()

    async def test_enable_hybrid_degrades_to_dense(self):
        """enable_hybrid=True should log warning and fall back to dense search."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "A", "content": "text", "score": 0.9},
        ])

        with patch("rag.retriever.search", mock_search):
            results = await enhanced_search(
                "test",
                enable_hybrid=True,
                enable_rerank=False,
                enable_graph_context=False,
            )

        # Should still return results (fell back to dense)
        assert len(results) == 1
        mock_search.assert_called_once()

    async def test_full_pipeline_e2e(self):
        """E2E: dense → rerank → graph context."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "Drone strike", "content": "text", "score": 0.8,
             "entities": [{"name": "Russia", "type": "organization"}]},
            {"title": "Peace talks", "content": "text", "score": 0.6, "entities": []},
        ])

        mock_rerank = AsyncMock(side_effect=lambda q, docs, top_k: docs[:top_k])
        mock_graph_ctx = AsyncMock(
            return_value="[Knowledge Graph Context]\n  Russia —[INVOLVES]→ Ukraine"
        )

        with patch("rag.retriever.search", mock_search), \
             patch("rag.retriever._rerank_fn", mock_rerank), \
             patch("rag.retriever._graph_context_fn", mock_graph_ctx):
            results = await enhanced_search(
                "drone attack Ukraine",
                limit=5,
                enable_hybrid=False,
                enable_rerank=True,
                enable_graph_context=True,
            )

        assert len(results) >= 1
        assert "graph_context" in results[0]
        assert "Russia" in results[0]["graph_context"]

    async def test_defaults_from_config(self):
        """When flags not passed, enhanced_search reads from settings."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "A", "content": "t", "score": 0.9},
        ])

        # config defaults: enable_hybrid=False, enable_rerank=True, enable_graph_context=True
        mock_rerank = AsyncMock(side_effect=lambda q, docs, top_k: docs[:top_k])
        mock_graph_ctx = AsyncMock(return_value="")

        with patch("rag.retriever.search", mock_search), \
             patch("rag.retriever._rerank_fn", mock_rerank), \
             patch("rag.retriever._graph_context_fn", mock_graph_ctx):
            results = await enhanced_search("test")

        # Rerank should have been called (enable_rerank defaults True)
        mock_rerank.assert_called_once()

    async def test_graph_context_uses_lazy_client_when_none_passed(self):
        """When no graph_client passed, enhanced_search uses _get_graph_client() singleton."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "NATO", "content": "text", "score": 0.9,
             "entities": [{"name": "NATO", "type": "organization"}]},
        ])

        mock_gc = AsyncMock()  # mock GraphClient
        mock_graph_ctx = AsyncMock(return_value="[Graph Context]\n  NATO → EU")

        with patch("rag.retriever.search", mock_search), \
             patch("rag.retriever._get_graph_client", return_value=mock_gc), \
             patch("rag.retriever._graph_context_fn", mock_graph_ctx):
            results = await enhanced_search(
                "NATO",
                enable_hybrid=False,
                enable_rerank=False,
                enable_graph_context=True,
                # Note: NO graph_client passed — should use lazy singleton
            )

        # Verify _graph_context_fn was called with the lazy singleton client
        mock_graph_ctx.assert_called_once()
        call_kwargs = mock_graph_ctx.call_args.kwargs
        assert call_kwargs["graph_client"] is mock_gc

    async def test_graph_context_with_explicit_client(self):
        """When graph_client is explicitly passed, it takes precedence over singleton."""
        from rag.retriever import enhanced_search

        mock_search = AsyncMock(return_value=[
            {"title": "NATO", "content": "text", "score": 0.9,
             "entities": [{"name": "NATO", "type": "organization"}]},
        ])

        explicit_gc = AsyncMock()
        mock_graph_ctx = AsyncMock(return_value="[Graph Context]")

        with patch("rag.retriever.search", mock_search), \
             patch("rag.retriever._graph_context_fn", mock_graph_ctx):
            await enhanced_search(
                "NATO",
                enable_hybrid=False,
                enable_rerank=False,
                enable_graph_context=True,
                graph_client=explicit_gc,
            )

        call_kwargs = mock_graph_ctx.call_args.kwargs
        assert call_kwargs["graph_client"] is explicit_gc
