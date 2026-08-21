"""Intelligence analysis endpoints with SSE streaming."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from starlette.responses import Response

from app.models.intel import IntelAnalysis, IntelQuery
from app.models.spatial import CatalogProblemCode, SpatialCatalogProblem
from app.routers.spatial import spatial_problem_response
from app.services.intel_stream import stream_intel_query
from app.services.proxy_service import ProxyService
from app.services.spatial_catalog import SpatialCatalogLoader
from app.services.spatial_filters import resolve_spatial_scope_token

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/intel", tags=["intelligence"])

# In-memory history (replaced by persistent storage in production)
_history: list[IntelAnalysis] = []


def _shared_http_client(request: Request) -> httpx.AsyncClient | None:
    proxy = getattr(request.app.state, "proxy", None)
    return proxy.client if isinstance(proxy, ProxyService) else None


@router.post("/query", response_model=None)
async def query_intel(query: IntelQuery, request: Request) -> EventSourceResponse | Response:
    """Run intelligence analysis via LangGraph pipeline, streaming results via SSE."""

    spatial_scope = None
    if query.spatial_scope is not None:
        candidate = getattr(request.app.state, "spatial_catalog", None)
        if not isinstance(candidate, SpatialCatalogLoader):
            return spatial_problem_response(
                SpatialCatalogProblem(
                    code=CatalogProblemCode.CATALOG_UNAVAILABLE,
                    message="Spatial catalog is unavailable",
                    recoverable=True,
                )
            )
        resolved = resolve_spatial_scope_token(candidate, query.spatial_scope)
        if isinstance(resolved, SpatialCatalogProblem):
            return spatial_problem_response(resolved)
        spatial_scope = resolved

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        async for ev in stream_intel_query(
            query=query.query,
            region=query.region,
            spatial_scope=spatial_scope,
            spatial_relation=query.spatial_relation,
            image_url=query.image_url,
            use_legacy=query.use_legacy,
            report_id=query.report_id.strip() if query.report_id else None,
            report_message=query.report_message,
            client=_shared_http_client(request),
        ):
            if ev.get("event") == "result":
                try:
                    _history.append(IntelAnalysis.model_validate_json(ev["data"]))
                except Exception:  # noqa: BLE001
                    pass
            yield ev

    return EventSourceResponse(event_generator())


@router.post("/hotspot/{hotspot_id}", response_model=None)
async def query_hotspot_intel(
    hotspot_id: str, request: Request
) -> EventSourceResponse | Response:
    """Run intelligence analysis focused on a specific hotspot."""
    query = IntelQuery(
        query=f"Intelligence analysis for hotspot: {hotspot_id}",
        hotspot_id=hotspot_id,
    )
    return await query_intel(query, request)


@router.get("/history", response_model=list[IntelAnalysis])
async def get_intel_history() -> list[IntelAnalysis]:
    return list(reversed(_history[-50:]))
