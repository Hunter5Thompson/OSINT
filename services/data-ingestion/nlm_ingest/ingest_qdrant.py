from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from feeds.provenance import provenance_fields
from nlm_ingest.schemas import Extraction, claim_hash
from qdrant_doctor.schema import validate_collection_schema

log = structlog.get_logger()

# Project-fixed namespace UUID (deterministic from the URL namespace).
NLM_QDRANT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "odin/nlm/odin_intel")


def _point_id(notebook_id: str, source_kind: str, source_id: str, statement_hash: str) -> str:
    name = f"{notebook_id}|{source_kind}|{source_id}|{statement_hash}"
    return str(uuid.uuid5(NLM_QDRANT_NAMESPACE, name))


def build_claim_points(
    extraction: Extraction,
    notebook_title: str,
    embed: Callable[[str], list[float]],
    *,
    source_name: str = "unknown",
    now_iso: str | None = None,
) -> list[PointStruct]:
    """One point per non-rejected claim. `embed` maps text -> vector."""
    ts = now_iso or datetime.now(UTC).isoformat()
    points: list[PointStruct] = []
    for claim in extraction.claims:
        if claim.confidence <= 0.0:
            continue
        chash = claim_hash(claim.statement)
        payload = {
            **provenance_fields(
                source_type="notebooklm",
                provider=f"notebooklm:{extraction.notebook_id}",
            ),
            "display_name": source_name,
            "title": notebook_title,
            "source": source_name,
            "region": "N/A",
            "content": claim.statement,
            "entities": [{"name": n} for n in claim.entities_involved],
            "notebook_id": extraction.notebook_id,
            "source_kind": extraction.source_kind,
            "source_id": extraction.source_id,
            "claim_type": str(claim.type),
            "claim_hash": chash,
            "content_hash": chash,
            "ingested_at": ts,
            "ingested_epoch": datetime.fromisoformat(ts).timestamp(),
        }
        points.append(PointStruct(
            id=_point_id(
                extraction.notebook_id, extraction.source_kind, extraction.source_id, chash
            ),
            vector=embed(claim.statement),
            payload=payload,
        ))
    return points


async def ensure_collection(
    qdrant: QdrantClient, collection: str, dim: int, *, enable_hybrid: bool = False
) -> None:
    """Create collection if missing, else validate schema before write.

    NLM writes dense vectors only. In hybrid mode (enable_hybrid=True) this aborts
    clearly — a hybrid (sparse/BM25) write is out of scope for this story (P2#4)."""
    if enable_hybrid:
        raise NotImplementedError(
            "NLM Qdrant write is dense-only; hybrid mode is out of scope for this story")
    collections = await asyncio.to_thread(lambda: qdrant.get_collections().collections)
    if not any(c.name == collection for c in collections):
        await asyncio.to_thread(lambda: qdrant.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        ))
        log.info("nlm_qdrant_collection_created", collection=collection)
    else:
        info = await asyncio.to_thread(lambda: qdrant.get_collection(collection))
        validate_collection_schema(info, enable_hybrid=enable_hybrid)


async def ingest_to_qdrant(
    qdrant: QdrantClient, collection: str, points: list[PointStruct]
) -> None:
    if not points:
        return
    await asyncio.to_thread(qdrant.upsert, collection_name=collection, points=points)
    log.info("nlm_qdrant_upserted", count=len(points))
