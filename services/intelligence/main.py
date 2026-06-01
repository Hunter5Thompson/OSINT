"""Intelligence service FastAPI app — exposes LangGraph pipeline over HTTP."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from graph.workflow import run_intelligence_query, shutdown_graph_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    await shutdown_graph_client()


app = FastAPI(title="WorldView Intelligence Service", version="0.2.0", lifespan=lifespan)


class GroundingEvidenceItem(BaseModel):
    source_type: Literal["dataset"]
    provider: Literal["odin-country-almanac", "odin-live-signal"]
    doc_id: str = Field(max_length=200)
    title: str = Field(max_length=300)
    content: str = Field(max_length=2000)
    url: str | None = Field(default=None, max_length=500)
    score: float = 0.0


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    region: str | None = None
    image_url: str | None = None
    use_legacy: bool = False
    grounding_context: str | None = Field(default=None, max_length=4000)
    grounding_evidence: list[GroundingEvidenceItem] | None = Field(default=None, max_length=6)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/query")
async def query_intelligence(req: QueryRequest) -> dict:
    """Run intelligence pipeline and return full analysis result."""
    return await run_intelligence_query(
        req.query,
        req.region,
        req.image_url,
        req.use_legacy,
        grounding_context=req.grounding_context,
        grounding_evidence=(
            [e.model_dump() for e in req.grounding_evidence] if req.grounding_evidence else None
        ),
    )
