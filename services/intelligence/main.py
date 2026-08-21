"""Intelligence service FastAPI app — exposes LangGraph pipeline over HTTP."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import settings
from graph.workflow import run_intelligence_query, shutdown_graph_client
from model_readiness import check_model_readiness
from rag import retriever
from spatial import RetrievalSpatialRelation
from spatial_catalog import (
    IntelligenceSpatialCatalog,
    SpatialCatalogResolutionError,
    SpatialScopeRefV1,
)

_spatial_catalog = IntelligenceSpatialCatalog(settings.spatial_catalog_path)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Global runs remain available if the shared catalog is not mounted; scoped
    # requests still fail closed in the route.
    with suppress(OSError, ValueError, SpatialCatalogResolutionError):
        await asyncio.to_thread(_spatial_catalog.load)
    yield
    try:
        await retriever.close()
    finally:
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
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., max_length=2000)
    region: str | None = None
    spatial_scope: SpatialScopeRefV1 | None = None
    spatial_relation: RetrievalSpatialRelation
    image_url: str | None = None
    use_legacy: bool = False
    grounding_context: str | None = Field(default=None, max_length=4000)
    grounding_evidence: list[GroundingEvidenceItem] | None = Field(default=None, max_length=6)

    @model_validator(mode="after")
    def reject_legacy_spatial_combinations(self) -> QueryRequest:
        if self.spatial_scope is None:
            return self
        if self.region is not None:
            raise ValueError("region and spatial_scope are mutually exclusive")
        if self.use_legacy:
            raise ValueError("SPATIAL_SCOPE_UNSUPPORTED_LEGACY")
        return self


@app.get("/health")
async def health() -> JSONResponse:
    readiness = await check_model_readiness(
        base_url=settings.llm_base_url,
        base_model=settings.llm_model,
        synthesis_model=settings.synthesis_model,
    )
    content = {
        "status": "ok" if readiness.ready else "not_ready",
        "reason": readiness.reason.value,
        "required_models": list(readiness.required_models),
        "missing_models": list(readiness.missing_models),
    }
    return JSONResponse(status_code=200 if readiness.ready else 503, content=content)


@app.post("/query", response_model=None)
async def query_intelligence(req: QueryRequest) -> dict[str, object] | JSONResponse:
    """Run intelligence pipeline and return full analysis result."""
    try:
        spatial_scope = (
            _spatial_catalog.resolve(req.spatial_scope)
            if req.spatial_scope is not None
            else None
        )
    except SpatialCatalogResolutionError:
        return JSONResponse(
            status_code=409,
            content={"detail": "spatial catalog reference is unavailable"},
        )
    return await run_intelligence_query(
        req.query,
        req.region,
        req.image_url,
        req.use_legacy,
        spatial_scope=spatial_scope,
        spatial_relation=req.spatial_relation,
        grounding_context=req.grounding_context,
        grounding_evidence=(
            [e.model_dump() for e in req.grounding_evidence] if req.grounding_evidence else None
        ),
    )
