"""Shared status-SSE orchestration for the intelligence /query call.

NOTE: this is status-SSE — three status events then one JSON result — not
token streaming. Used by routers/intel.py and routers/almanac.py (briefing).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.config import settings
from app.models.intel import IntelAnalysis
from app.models.report import ReportMessageCreate
from app.services import report_store
from app.services.briefing import truncate_message

log = structlog.get_logger(__name__)


async def stream_intel_query(
    *,
    query: str,
    region: str | None = None,
    image_url: str | None = None,
    use_legacy: bool = False,
    grounding_context: str | None = None,
    grounding_evidence: list[dict[str, Any]] | None = None,
    report_id: str | None = None,
    report_message: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the intelligence /query call, yielding status → result/error SSE events.

    Shared by /intel/query (interactive) and the country-briefing endpoint. When
    `report_id` is supplied the user message and the munin synthesis (or an error
    notice) are persisted to the report-scoped chat log.
    """
    try:
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

            user_text = (report_message or query).strip()
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

        payload: dict[str, Any] = {
            "query": query,
            "region": region,
            "image_url": image_url,
            "use_legacy": use_legacy,
        }
        if grounding_context is not None:
            payload["grounding_context"] = grounding_context
        if grounding_evidence is not None:
            payload["grounding_evidence"] = grounding_evidence

        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(f"{settings.intelligence_url}/query", json=payload)
            resp.raise_for_status()
            data = resp.json()

        analysis = IntelAnalysis(
            query=query,
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

        if report_id:
            persisted_text = analysis.analysis.strip() or (
                "no synthesis produced · agent returned empty content"
            )
            try:
                await report_store.append_report_message(
                    report_id,
                    ReportMessageCreate(
                        role="munin",
                        text=truncate_message(persisted_text),
                        ts=analysis.timestamp,
                        refs=analysis.sources_used[:6],
                    ),
                )
            except Exception as persist_exc:  # noqa: BLE001
                log.warning(
                    "report_message_persist_failed",
                    report_id=report_id,
                    error=str(persist_exc),
                )

        yield {"event": "result", "data": analysis.model_dump_json()}
        yield {"event": "done", "data": ""}

    except httpx.HTTPError as exc:
        log.warning("intelligence_service_error", error=str(exc))
        if report_id:  # preserve the existing /intel/query behavior (intel.py:119-136)
            try:
                await report_store.append_report_message(
                    report_id,
                    ReportMessageCreate(
                        role="munin",
                        text="service unreachable · retry in 10s",
                    ),
                )
            except Exception as persist_exc:  # noqa: BLE001
                log.warning(
                    "report_error_message_persist_failed",
                    report_id=report_id,
                    error=str(persist_exc),
                )
        yield {
            "event": "error",
            "data": json.dumps({"error": str(exc), "code": "INTEL_SERVICE_ERROR"}),
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("intel_query_failed")
        yield {
            "event": "error",
            "data": json.dumps({"error": str(exc), "code": "INTEL_ERROR"}),
        }
