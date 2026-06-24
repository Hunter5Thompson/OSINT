"""RAG management endpoints."""

from datetime import datetime

import httpx
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import settings
from app.services.proxy_service import ProxyService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


class IngestRequest(BaseModel):
    url: str | None = None
    content: str | None = None
    source: str = "manual"
    title: str = ""


class IngestResult(BaseModel):
    status: str
    doc_count: int
    message: str


class SourceInfo(BaseModel):
    name: str
    type: str
    doc_count: int
    last_ingested: datetime | None = None


class RAGStats(BaseModel):
    total_documents: int
    collections: list[str]
    embedding_model: str
    embedding_dimensions: int


def _shared_http_client(request: Request) -> httpx.AsyncClient | None:
    proxy = getattr(request.app.state, "proxy", None)
    return proxy.client if isinstance(proxy, ProxyService) else None


@router.post("/ingest", response_model=IngestResult)
async def ingest_document(req: IngestRequest, request: Request) -> IngestResult:
    """Ingest a document or feed URL into the RAG pipeline."""
    # Placeholder - manual ingestion not yet wired to data-ingestion service
    return IngestResult(
        status="accepted",
        doc_count=0,
        message="Document queued for ingestion.",
    )


@router.get("/sources", response_model=list[SourceInfo])
async def get_sources(request: Request) -> list[SourceInfo]:
    """List ingested data sources with document counts from Qdrant."""
    sources = [
        SourceInfo(name="RSS Feeds", type="rss", doc_count=0),
        SourceInfo(name="GDELT Events", type="gdelt", doc_count=0),
        SourceInfo(name="Manual Uploads", type="manual", doc_count=0),
    ]
    try:
        client = _shared_http_client(request)
        if client is None:
            async with httpx.AsyncClient(timeout=5.0) as fallback_client:
                await _populate_source_counts(fallback_client, sources)
        else:
            await _populate_source_counts(client, sources)
    except httpx.HTTPError as exc:
        log.warning("qdrant_sources_failed", error=str(exc))
    return sources


@router.get("/stats", response_model=RAGStats)
async def get_rag_stats(request: Request) -> RAGStats:
    """Get RAG pipeline statistics from Qdrant."""
    total = 0
    collections: list[str] = []
    try:
        client = _shared_http_client(request)
        if client is None:
            async with httpx.AsyncClient(timeout=5.0) as fallback_client:
                total, collections = await _fetch_rag_stats(fallback_client)
        else:
            total, collections = await _fetch_rag_stats(client)
    except httpx.HTTPError as exc:
        log.warning("qdrant_stats_failed", error=str(exc))

    return RAGStats(
        total_documents=total,
        collections=collections,
        embedding_model="Qwen3-Embedding-0.6B",
        embedding_dimensions=settings.embedding_dimensions,
    )


async def _populate_source_counts(
    client: httpx.AsyncClient,
    sources: list[SourceInfo],
) -> None:
    for source in sources:
        resp = await client.post(
            f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points/count",
            json={"filter": {"must": [{"key": "source", "match": {"value": source.type}}]}},
            timeout=5.0,
        )
        if resp.status_code == 200:
            source.doc_count = resp.json().get("result", {}).get("count", 0)


async def _fetch_rag_stats(client: httpx.AsyncClient) -> tuple[int, list[str]]:
    total = 0
    collections: list[str] = []
    resp = await client.get(f"{settings.qdrant_url}/collections", timeout=5.0)
    if resp.status_code == 200:
        collections = [
            c["name"] for c in resp.json().get("result", {}).get("collections", [])
        ]

    if settings.qdrant_collection in collections:
        resp = await client.get(
            f"{settings.qdrant_url}/collections/{settings.qdrant_collection}",
            timeout=5.0,
        )
        if resp.status_code == 200:
            total = resp.json().get("result", {}).get("points_count", 0)

    return total, collections
