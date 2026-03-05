"""Intelligence analysis endpoints with SSE streaming."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.models.intel import APIError, IntelAnalysis, IntelQuery

router = APIRouter(prefix="/intel", tags=["intelligence"])

# In-memory history (replaced by persistent storage in production)
_history: list[IntelAnalysis] = []


@router.post("/query")
async def query_intel(query: IntelQuery, request: Request) -> EventSourceResponse:
    """Run intelligence analysis via LangGraph pipeline, streaming results via SSE."""

    async def event_generator():  # type: ignore[no-untyped-def]
        try:
            # Import intelligence pipeline
            # In production, this calls the intelligence service
            yield {"event": "status", "data": json.dumps({"agent": "osint_agent", "status": "started"})}

            yield {
                "event": "status",
                "data": json.dumps({"agent": "analyst_agent", "status": "analyzing"}),
            }

            yield {
                "event": "status",
                "data": json.dumps({"agent": "synthesis_agent", "status": "synthesizing"}),
            }

            # Placeholder analysis result
            analysis = IntelAnalysis(
                query=query.query,
                agent_chain=["osint_agent", "analyst_agent", "synthesis_agent"],
                sources_used=["qdrant_search", "gdelt_query"],
                analysis=f"Intelligence analysis for: {query.query}. This is a placeholder response. Connect the LangGraph intelligence service for real analysis.",
                confidence=0.0,
                threat_assessment="MODERATE",
                timestamp=datetime.now(timezone.utc),
            )

            _history.append(analysis)

            yield {
                "event": "result",
                "data": analysis.model_dump_json(),
            }

            yield {"event": "done", "data": ""}
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e), "code": "INTEL_ERROR"}),
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
