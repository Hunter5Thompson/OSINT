"""RAG management endpoints."""

import asyncio
from datetime import datetime
from typing import Literal

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
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
    doc_count: int | None = None
    availability: Literal["available", "unavailable"] = "unavailable"
    last_ingested: datetime | None = None


class RAGStats(BaseModel):
    total_documents: int | None
    collections: list[str] | None
    availability: Literal["available", "unavailable"]
    embedding_model: str
    embedding_dimensions: int


def _shared_http_client(request: Request) -> httpx.AsyncClient | None:
    proxy = getattr(request.app.state, "proxy", None)
    return proxy.client if isinstance(proxy, ProxyService) else None


@router.post("/ingest", response_model=IngestResult)
async def ingest_document(req: IngestRequest, request: Request) -> IngestResult:
    """Ingest a document or feed URL into the RAG pipeline."""
    raise HTTPException(501, "Manual ingestion is not implemented; no job was created.")


@router.get("/sources", response_model=list[SourceInfo])
async def get_sources(request: Request) -> list[SourceInfo]:
    """Count known source families; unavailable counts stay unknown."""
    sources = [
        SourceInfo(name="RSS Feeds", type="rss"),
        SourceInfo(name="GDELT GKG", type="gdelt_gkg"),
        SourceInfo(name="GDELT Legacy", type="gdelt"),
        SourceInfo(name="NotebookLM", type="notebooklm"),
        SourceInfo(name="Telegram", type="telegram"),
        SourceInfo(name="Manual Uploads (historical)", type="manual"),
    ]
    try:
        client = _shared_http_client(request)
        if client is None:
            async with httpx.AsyncClient(timeout=5.0) as fallback_client:
                await _populate_source_counts(fallback_client, sources)
        else:
            await _populate_source_counts(client, sources)
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        log.warning("qdrant_sources_failed")
    return sources


@router.get("/stats", response_model=RAGStats)
async def get_rag_stats(request: Request) -> RAGStats:
    """Get RAG pipeline statistics from Qdrant."""
    total: int | None = None
    collections: list[str] | None = None
    try:
        client = _shared_http_client(request)
        if client is None:
            async with httpx.AsyncClient(timeout=5.0) as fallback_client:
                total, collections = await _fetch_rag_stats(fallback_client)
        else:
            total, collections = await _fetch_rag_stats(client)
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        log.warning("qdrant_stats_failed")

    return RAGStats(
        total_documents=total,
        collections=collections,
        availability="available" if total is not None else "unavailable",
        embedding_model="Qwen3-Embedding-0.6B",
        embedding_dimensions=settings.embedding_dimensions,
    )


async def _populate_source_counts(
    client: httpx.AsyncClient,
    sources: list[SourceInfo],
) -> None:
    async def count(source: SourceInfo) -> None:
        try:
            resp = await client.post(
                f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points/count",
                json={"exact": True, "filter": {
                    "must": [{"key": "source", "match": {"value": source.type}}],
                }}, timeout=5.0,
            )
            source.doc_count = _read_count(resp)
            source.availability = "available"
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            log.warning("qdrant_source_count_unavailable", source=source.type)
    await asyncio.gather(*(count(source) for source in sources))


def _read_count(resp: httpx.Response) -> int:
    resp.raise_for_status()
    value = resp.json()["result"]["count"]
    if type(value) is not int or value < 0:
        raise ValueError("Invalid Qdrant count")
    return value


async def _fetch_rag_stats(client: httpx.AsyncClient) -> tuple[int, list[str]]:
    resp = await client.get(f"{settings.qdrant_url}/collections", timeout=5.0)
    resp.raise_for_status()
    rows = resp.json()["result"]["collections"]
    if not isinstance(rows, list):
        raise ValueError("Invalid Qdrant collection list")
    collections = [row["name"] for row in rows]
    if not all(isinstance(name, str) for name in collections):
        raise ValueError("Invalid Qdrant collection name")
    if settings.qdrant_collection not in collections:
        raise ValueError("Configured Qdrant collection missing")
    resp = await client.post(
        f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points/count",
        json={"exact": True}, timeout=5.0,
    )
    return _read_count(resp), collections
