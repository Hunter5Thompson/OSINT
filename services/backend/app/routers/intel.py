"""Intelligence analysis endpoints with SSE streaming."""

import json
from datetime import UTC, datetime

import httpx
import structlog
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.models.intel import IntelAnalysis, IntelQuery
from app.models.report import ReportMessageCreate
from app.services import report_store

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/intel", tags=["intelligence"])

# In-memory history (replaced by persistent storage in production)
_history: list[IntelAnalysis] = []


@router.post("/query")
async def query_intel(query: IntelQuery, request: Request) -> EventSourceResponse:
    """Run intelligence analysis via LangGraph pipeline, streaming results via SSE."""

    async def event_generator():  # type: ignore[no-untyped-def]
        try:
            report_id = query.report_id.strip() if query.report_id else None
            if report_id:
                report = await report_store.get_report(report_id)
                if report is None:
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {
                                "error": f"report not found: {report_id}",
                                "code": "REPORT_NOT_FOUND",
                            }
                        ),
                    }
                    yield {"event": "done", "data": ""}
                    return

                user_text = (query.report_message or query.query).strip()
                if user_text:
                    await report_store.append_report_message(
                        report_id,
                        ReportMessageCreate(role="user", text=user_text),
                    )

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
                    json={
                        "query": query.query,
                        "region": query.region,
                        "image_url": query.image_url,
                        "use_legacy": query.use_legacy,
                    },
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
                tool_trace=data.get("tool_trace", []),
                mode=data.get("mode", "react"),
                timestamp=datetime.fromisoformat(data["timestamp"])
                if "timestamp" in data
                else datetime.now(UTC),
            )

            _history.append(analysis)

            if report_id:
                persisted_text = analysis.analysis.strip() or (
                    "no synthesis produced · agent returned empty content"
                )
                try:
                    await report_store.append_report_message(
                        report_id,
                        ReportMessageCreate(
                            role="munin",
                            text=persisted_text,
                            ts=analysis.timestamp,
                            refs=analysis.sources_used[:6],
                        ),
                    )
                except Exception as persist_exc:
                    log.warning(
                        "report_message_persist_failed",
                        report_id=report_id,
                        error=str(persist_exc),
                    )

            yield {"event": "result", "data": analysis.model_dump_json()}
            yield {"event": "done", "data": ""}

        except httpx.HTTPError as exc:
            log.warning("intelligence_service_error", error=str(exc))
            report_id = query.report_id.strip() if query.report_id else None
            if report_id:
                try:
                    await report_store.append_report_message(
                        report_id,
                        ReportMessageCreate(
                            role="munin",
                            text="service unreachable · retry in 10s",
                        ),
                    )
                except Exception as persist_exc:
                    log.warning(
                        "report_error_message_persist_failed",
                        report_id=report_id,
                        error=str(persist_exc),
                    )
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
    query = IntelQuery(
        query=f"Intelligence analysis for hotspot: {hotspot_id}",
        hotspot_id=hotspot_id,
    )
    return await query_intel(query, request)


@router.get("/history", response_model=list[IntelAnalysis])
async def get_intel_history() -> list[IntelAnalysis]:
    return list(reversed(_history[-50:]))
