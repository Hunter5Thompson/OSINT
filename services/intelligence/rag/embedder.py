"""Embedding generation via Ollama API (nomic-embed-text)."""

import httpx
import structlog

from config import settings

logger = structlog.get_logger()


async def embed_text(text: str) -> list[float] | None:
    """Generate embedding for a single text using Ollama."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/embed",
                json={"model": settings.embedding_model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings", [])
            if embeddings:
                return embeddings[0]
    except Exception as e:
        logger.warning("embed_text_failed", error=str(e))
    return None


async def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for a batch of texts."""
    results: list[list[float] | None] = []
    for text in texts:
        embedding = await embed_text(text)
        results.append(embedding)
    return results
