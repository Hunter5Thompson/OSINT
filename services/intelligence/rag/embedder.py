"""Embedding generation via TEI (Text Embeddings Inference)."""

import httpx
import structlog

from config import settings

logger = structlog.get_logger()


async def embed_text(text: str) -> list[float] | None:
    """Generate embedding for a single text using TEI."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.tei_embed_url}/embed",
                json={"inputs": text},
            )
            resp.raise_for_status()
            result = resp.json()
            # TEI returns [[...floats...]] for single input
            return result[0] if isinstance(result[0], list) else result
    except Exception as e:
        logger.warning("embed_text_failed", error=str(e))
    return None


async def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for a batch of texts via TEI batch endpoint."""
    if not texts:
        return []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.tei_embed_url}/embed",
                json={"inputs": texts},
            )
            resp.raise_for_status()
            return resp.json()  # TEI returns [[...], [...], ...] for batch
    except Exception as e:
        logger.warning("embed_batch_failed", error=str(e), count=len(texts))
        # Fallback: embed one by one
        return [await embed_text(t) for t in texts]
