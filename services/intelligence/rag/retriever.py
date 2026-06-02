"""Qdrant retriever for hybrid search with payload filtering."""

import contextlib

import httpx
import structlog
from qdrant_client import AsyncQdrantClient

from config import settings
from graph.client import GraphClient
from rag.embedder import embed_text
from rag.graph_context import get_graph_context as _graph_context_fn
from rag.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema
from rag.reranker import rerank as _rerank_fn

# Lazy singleton GraphClient for graph context injection
_graph_client: GraphClient | None = None

# One-time preflight flag — schema validated before first search
_schema_validated: bool = False


def _get_graph_client() -> GraphClient | None:
    """Get or create a shared GraphClient from config settings."""
    global _graph_client
    if _graph_client is None and settings.neo4j_uri:
        with contextlib.suppress(Exception):
            _graph_client = GraphClient(
                settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password,
            )
    return _graph_client

logger = structlog.get_logger()


async def close() -> None:
    """Release retriever-owned resources and reset the schema preflight."""
    global _graph_client, _schema_validated
    graph_client, _graph_client = _graph_client, None
    _schema_validated = False
    if graph_client is not None:
        await graph_client.close()


async def _ensure_schema_validated() -> None:
    """Validate the Qdrant collection schema once before the first search.

    Raises QdrantSchemaMismatch if the collection exists but has the wrong schema.
    Network errors are swallowed — let the search call surface them naturally.
    """
    global _schema_validated
    if _schema_validated:
        return
    client = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        collections = await client.get_collections()
        names = {c.name for c in collections.collections}
        if settings.qdrant_collection in names:
            info = await client.get_collection(settings.qdrant_collection)
            validate_collection_schema(info, enable_hybrid=settings.enable_hybrid)
        _schema_validated = True
    except QdrantSchemaMismatch:
        raise
    except Exception:
        # Network / connection errors — don't block startup
        pass
    finally:
        await client.close()


async def search(
    query: str,
    limit: int = 5,
    region: str | None = None,
    source: str | None = None,
    score_threshold: float = 0.3,
    query_filter: dict | None = None,
) -> list[dict]:
    """Search the knowledge base with optional filters.

    Args:
        query: Search query text.
        limit: Maximum number of results.
        region: Optional region filter.
        source: Optional source filter.
        score_threshold: Minimum similarity score.

    Returns:
        List of matching documents with scores.
    """
    # Preflight: validate schema before the first Qdrant search call
    await _ensure_schema_validated()

    embedding = await embed_text(query)
    if not embedding:
        return []

    search_body: dict = {
        "vector": embedding,
        "limit": limit,
        "with_payload": True,
        "score_threshold": score_threshold,
    }

    # Build filter conditions
    must_conditions: list[dict] = []
    if region:
        must_conditions.append({"key": "region", "match": {"value": region}})
    if source:
        must_conditions.append({"key": "source", "match": {"value": source}})

    filt: dict = {}
    if must_conditions:
        filt["must"] = must_conditions
    if query_filter:
        for k, v in query_filter.items():
            if k == "must":
                filt["must"] = filt.get("must", []) + v
            else:
                filt[k] = v
    if filt:
        search_body["filter"] = filt

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points/search",
                json=search_body,
            )
            if resp.status_code == 404:
                logger.warning("collection_not_found")
                return []
            resp.raise_for_status()
            data = resp.json()

        results: list[dict] = []
        for r in data.get("result", []):
            results.append({
                "score": r.get("score", 0),
                **r.get("payload", {}),
            })

        return results
    except Exception as e:
        logger.warning("retriever_search_failed", error=str(e))
        return []


async def enhanced_search(
    query: str,
    limit: int = 5,
    region: str | None = None,
    source: str | None = None,
    score_threshold: float = 0.3,
    query_filter: dict | None = None,
    pool: int | None = None,
    post_rerank=None,
    *,
    enable_hybrid: bool | None = None,
    enable_rerank: bool | None = None,
    enable_graph_context: bool | None = None,
    graph_client=None,
) -> list[dict]:
    """Enhanced retrieval: dense search → optional rerank → optional graph context.

    Feature flags default to config.py settings if not explicitly passed.
    Hybrid search (dense + sparse) is Phase 2 — raises NotImplementedError if enabled.
    """
    # Use config defaults if not explicitly set
    if enable_hybrid is None:
        enable_hybrid = settings.enable_hybrid
    if enable_rerank is None:
        enable_rerank = settings.enable_rerank
    if enable_graph_context is None:
        enable_graph_context = settings.enable_graph_context

    # Phase 2: Hybrid search requires sparse vectors in Qdrant
    if enable_hybrid:
        logger.warning(
            "hybrid_search_not_available",
            reason=(
                "Requires odin_v2 collection with sparse vectors (Phase 2). "
                "Falling back to dense-only."
            ),
        )
        enable_hybrid = False  # graceful fallback to dense

    # Stage 1: Dense search (baseline). pool overrides the rerank overfetch.
    overfetch = pool if pool is not None else (limit * 2 if enable_rerank else limit)
    results = await search(
        query, limit=overfetch, region=region,
        source=source, score_threshold=score_threshold, query_filter=query_filter,
    )

    if not results:
        return []

    # Stage 2: Rerank (optional). When a post_rerank hook is set we rerank the
    # whole pool so the hook can re-order across all candidates before the cut.
    if enable_rerank:
        rerank_top_k = overfetch if post_rerank is not None else limit
        results = await _rerank_fn(query, results, top_k=rerank_top_k)

    # Stage 2b: Optional post-rerank hook (e.g. tier-boost). Keeps the primitive
    # neutral when None — no corpus policy leaks into the generic retriever.
    if post_rerank is not None:
        results = post_rerank(results)

    results = results[:limit]

    # Stage 3: Graph Context Injection (optional) — only for the final items.
    if enable_graph_context:
        entity_names = set()
        for r in results:
            for e in r.get("entities", []):
                if isinstance(e, dict) and "name" in e:
                    entity_names.add(e["name"])
        if entity_names:
            gc = graph_client or _get_graph_client()
            graph_ctx = await _graph_context_fn(list(entity_names), graph_client=gc)
            if graph_ctx:
                for r in results:
                    r["graph_context"] = graph_ctx

    return results
