"""RAG management endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

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


@router.post("/ingest", response_model=IngestResult)
async def ingest_document(req: IngestRequest, request: Request) -> IngestResult:
    """Ingest a document or feed URL into the RAG pipeline."""
    # Placeholder - connects to intelligence service for real ingestion
    return IngestResult(
        status="accepted",
        doc_count=0,
        message="Document queued for ingestion. Connect intelligence service for processing.",
    )


@router.get("/sources", response_model=list[SourceInfo])
async def get_sources() -> list[SourceInfo]:
    """List all ingested data sources."""
    return [
        SourceInfo(name="RSS Feeds", type="rss", doc_count=0),
        SourceInfo(name="GDELT Events", type="gdelt", doc_count=0),
        SourceInfo(name="Manual Uploads", type="manual", doc_count=0),
    ]


@router.get("/stats", response_model=RAGStats)
async def get_rag_stats() -> RAGStats:
    """Get RAG pipeline statistics."""
    return RAGStats(
        total_documents=0,
        collections=["worldview_intel"],
        embedding_model="nomic-embed-text",
        embedding_dimensions=768,
    )
