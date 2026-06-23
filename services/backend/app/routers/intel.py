"""Intelligence analysis endpoints with SSE streaming."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.models.intel import IntelAnalysis, IntelQuery
from app.services.intel_stream import stream_intel_query
from app.services.proxy_service import ProxyService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/intel", tags=["intelligence"])

# In-memory history (replaced by persistent storage in production)
_history: list[IntelAnalysis] = []


def _shared_http_client(request: Request) -> httpx.AsyncClient | None:
    proxy = getattr(request.app.state, "proxy", None)
    return proxy.client if isinstance(proxy, ProxyService) else None


@router.post("/query")
async def query_intel(query: IntelQuery, request: Request) -> EventSourceResponse:
    """Run intelligence analysis via LangGraph pipeline, streaming results via SSE."""

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        async for ev in stream_intel_query(
            query=query.query,
            region=query.region,
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


@router.post("/hotspot/{hotspot_id}")
async def query_hotspot_intel(
    hotspot_id: str, request: Request
) -> EventSourceResponse:
    """Run intelligence analysis focused on a specific hotspot."""
    query = IntelQuery(
        query=f"Intelligence analysis for hotspot: {hotspot_id}",
        hotspot_id=hotspot_id,
    )
    return await query_intel(query, request)


@router.get("/history", response_model=list[IntelAnalysis])
async def get_intel_history() -> list[IntelAnalysis]:
    return list(reversed(_history[-50:]))
