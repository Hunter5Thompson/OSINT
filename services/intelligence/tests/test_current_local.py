"""Temporal local retrieval uses publication time and original-content provenance."""

from datetime import timedelta
from unittest.mock import AsyncMock

from tests.test_current_research import AS_OF, BODY


async def test_local_current_filter_excludes_freshly_ingested_old_articles(monkeypatch):
    from rag.local_current import search_current_corpus

    search = AsyncMock(
        return_value=[
            {
                "source_type": "rss",
                "source": "rss_fulltext",
                "provider": "fixture",
                "url": "https://news.example.org/article",
                "title": "Iran talks",
                "content": BODY,
                "published_at": (AS_OF - timedelta(days=60)).isoformat(),
                "ingested_at": AS_OF.isoformat(),
                "score": 0.8,
            }
        ]
    )
    monkeypatch.setattr("rag.local_current.enhanced_search", search)
    result = await search_current_corpus("Iran", AS_OF - timedelta(hours=72), AS_OF)
    assert result == []
    query_filter = search.call_args.kwargs["query_filter"].model_dump(mode="json")
    assert "published_at" in str(query_filter)
    assert "ingested_at" not in str(query_filter)
    assert search.call_args.kwargs["enable_graph_context"] is False


async def test_local_current_original_retains_publication_and_ingestion_separately(monkeypatch):
    from rag.local_current import search_current_corpus
    body = "Iran's government announced negotiations with regional mediators on Friday. " * 8
    search = AsyncMock(return_value=[{
        "source_type": "rss", "source": "rss_fulltext", "provider": "fixture",
        "url": "https://news.example.org/article", "title": "Iran talks", "content": body,
        "published_at": (AS_OF - timedelta(hours=2)).isoformat(),
        "ingested_at": AS_OF.isoformat(), "score": 0.8,
    }])
    monkeypatch.setattr("rag.local_current.enhanced_search", search)
    result = await search_current_corpus("Iran", AS_OF - timedelta(hours=72), AS_OF)
    assert len(result) == 1
    assert result[0].source.published_at == AS_OF - timedelta(hours=2)
    assert result[0].ingested_at == AS_OF
    assert result[0].retrieval.content_kind == "fulltext_chunk"
    assert result[0].observed_at is None
