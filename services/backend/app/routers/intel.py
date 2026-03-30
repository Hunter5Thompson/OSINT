"""Intelligence analysis endpoints with SSE streaming."""

import json
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.models.intel import APIError, IntelAnalysis, IntelQuery

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/intel", tags=["intelligence"])

# In-memory history (replaced by persistent storage in production)
_history: list[IntelAnalysis] = []


@router.post("/query")
async def query_intel(query: IntelQuery, request: Request) -> EventSourceResponse:
    """Run intelligence analysis via LangGraph pipeline, streaming results via SSE."""

    async def event_generator():  # type: ignore[no-untyped-def]
        try:
            yield {
                "event": "status",
                "data": json.dumps({"agent": "osint_agent", "status": "started"}),
            }
            yield {
                "event": "status",
                "data": json.dumps({"agent": "analyst_agent", "status": "analyzing"}),
            }
            yield {
                "event": "status",
                "data": json.dumps({"agent": "synthesis_agent", "status": "synthesizing"}),
            }

            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{settings.intelligence_url}/query",
                    json={"query": query.query, "region": query.region},
                )
                resp.raise_for_status()
                data = resp.json()

            analysis = IntelAnalysis(
                query=query.query,
                agent_chain=data.get("agent_chain", []),
                sources_used=data.get("sources_used", []),
                analysis=data.get("analysis", ""),
                confidence=data.get("confidence", 0.0),
                threat_assessment=data.get("threat_assessment", "MODERATE"),
                timestamp=datetime.fromisoformat(data["timestamp"])
                if "timestamp" in data
                else datetime.now(timezone.utc),
            )

            _history.append(analysis)

            yield {"event": "result", "data": analysis.model_dump_json()}
            yield {"event": "done", "data": ""}

        except httpx.HTTPError as exc:
            log.warning("intelligence_service_error", error=str(exc))
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc), "code": "INTEL_SERVICE_ERROR"}),
            }
        except Exception as exc:
            log.exception("intel_query_failed")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc), "code": "INTEL_ERROR"}),
            }

    return EventSourceResponse(event_generator())


@router.post("/hotspot/{hotspot_id}")
async def query_hotspot_intel(
    hotspot_id: str, request: Request
) -> EventSourceResponse:
    """Run intelligence analysis focused on a specific hotspot."""
    query = IntelQuery(query=f"Intelligence analysis for hotspot: {hotspot_id}", hotspot_id=hotspot_id)
    return await query_intel(query, request)


@router.get("/history", response_model=list[IntelAnalysis])
async def get_intel_history() -> list[IntelAnalysis]:
    return list(reversed(_history[-50:]))
