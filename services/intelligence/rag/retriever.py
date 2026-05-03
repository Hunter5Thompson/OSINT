"""Qdrant retriever for hybrid search with payload filtering."""

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
        try:
            _graph_client = GraphClient(
                settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password,
            )
        except Exception:
            pass
    return _graph_client

logger = structlog.get_logger()


async def _ensure_schema_validated() -> None:
    """Validate the Qdrant collection schema once before the first search.

    Raises QdrantSchemaMismatch if the collection exists but has the wrong schema.
    Network errors are swallowed — let the search call surface them naturally.
    """
    global _schema_validated
    if _schema_validated:
        return
    try:
        client = AsyncQdrantClient(url=settings.qdrant_url)
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


async def search(
    query: str,
    limit: int = 5,
    region: str | None = None,
    source: str | None = None,
    score_threshold: float = 0.3,
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

    if must_conditions:
        search_body["filter"] = {"must": must_conditions}

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
            reason="Requires odin_v2 collection with sparse vectors (Phase 2). Falling back to dense-only.",
        )
        enable_hybrid = False  # graceful fallback to dense

    # Stage 1: Dense search (baseline)
    overfetch = limit * 2 if enable_rerank else limit
    results = await search(
        query, limit=overfetch, region=region,
        source=source, score_threshold=score_threshold,
    )

    if not results:
        return []

    # Stage 2: Rerank (optional)
    if enable_rerank:
        results = await _rerank_fn(query, results, top_k=limit)

    # Stage 3: Graph Context Injection (optional)
    if enable_graph_context:
        entity_names = set()
        for r in results:
            for e in r.get("entities", []):
                if isinstance(e, dict) and "name" in e:
                    entity_names.add(e["name"])
        if entity_names:
            # Use provided client or fall back to lazy singleton from config
            gc = graph_client or _get_graph_client()
            graph_ctx = await _graph_context_fn(
                list(entity_names), graph_client=gc,
            )
            if graph_ctx:
                for r in results:
                    r["graph_context"] = graph_ctx

    return results
