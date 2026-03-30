"""Reranker via TEI (Text Embeddings Inference) on Port 8002."""

import httpx
import structlog

from config import settings

log = structlog.get_logger(__name__)


async def rerank(
    query: str,
    documents: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """Rerank documents using TEI rerank endpoint.

    Falls back to returning original documents (truncated to top_k) on failure.
    """
    if not documents:
        return []

    texts = [d.get("content", d.get("title", "")) for d in documents]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.tei_rerank_url}/rerank",
                json={"query": query, "texts": texts},
            )
            resp.raise_for_status()
            scores = resp.json()

        ranked = sorted(scores, key=lambda x: x["score"], reverse=True)
        result = []
        for item in ranked[:top_k]:
            doc = documents[item["index"]].copy()
            doc["rerank_score"] = item["score"]
            result.append(doc)
        return result

    except Exception as e:
        log.warning("rerank_failed_using_original_order", error=str(e))
        return documents[:top_k]
