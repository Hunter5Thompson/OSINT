"""REST + SSE + admin trigger for /api/incidents.

The admin trigger is a deliberate stub for v1 — real pattern detection is
deferred to services/incident-detector (spec §8). All operations publish
an envelope to IncidentStream so connected War Rooms react in real time.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentStatus,
)
from app.services import incident_store
from app.services.incident_stream import IncidentEnvelope, get_incident_stream

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])

_HEARTBEAT_SECONDS = 15.0


def _require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    expected = settings.incidents_admin_token
    if not expected:
        log.warning("incident_admin_unsecured", note="set INCIDENTS_ADMIN_TOKEN")
        return
    if x_admin_token != expected:
        raise HTTPException(status_code=401, detail="invalid admin token")


@router.get("", response_model=list[Incident])
async def list_incidents(limit: int = Query(default=50, ge=1, le=200)) -> list[Incident]:
    try:
        return await incident_store.list_open_incidents(limit=limit)
    except Exception as exc:
        log.warning("incidents_list_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="incidents backend unavailable") from exc


# IMPORTANT: `/stream` MUST be declared BEFORE `/{incident_id}` — FastAPI
# matches routes in declaration order, so a dynamic-id route declared first
# will swallow the literal `/stream`. Same rule for `/_admin/trigger`.
@router.get("/stream")
async def stream_incidents(
    request: Request,
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
) -> EventSourceResponse:
    last_event_id = last_event_id_header or last_event_id_query
    return EventSourceResponse(_sse_generator(request, last_event_id))


@router.post(
    "/_admin/trigger",
    response_model=Incident,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_admin)],
)
async def admin_trigger(payload: IncidentCreateRequest) -> Incident:
    """Admin-only stub for incident creation. Detection service deferred (spec §8)."""
    try:
        record = await incident_store.create_incident(payload)
    except Exception as exc:
        log.warning("incident_create_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="incident create failed") from exc
    get_incident_stream().publish("incident.open", record)
    return record


@router.get("/{incident_id}", response_model=Incident)
async def get_incident(incident_id: str) -> Incident:
    try:
        record = await incident_store.get_incident(incident_id)
    except Exception as exc:
        log.warning("incident_get_failed", incident_id=incident_id, error=str(exc))
        raise HTTPException(status_code=503, detail="incidents backend unavailable") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return record


@router.post(
    "/{incident_id}/silence",
    response_model=Incident,
    dependencies=[Depends(_require_admin)],
)
async def silence(incident_id: str) -> Incident:
    record = await incident_store.close_incident(incident_id, IncidentStatus.SILENCED)
    if record is None:
        raise HTTPException(status_code=404, detail="incident not found")
    get_incident_stream().publish("incident.silence", record)
    return record


@router.post(
    "/{incident_id}/promote",
    response_model=Incident,
    dependencies=[Depends(_require_admin)],
)
async def promote(incident_id: str) -> Incident:
    record = await incident_store.close_incident(incident_id, IncidentStatus.PROMOTED)
    if record is None:
        raise HTTPException(status_code=404, detail="incident not found")
    get_incident_stream().publish("incident.promote", record)
    return record


async def _sse_generator(
    request: Request | None,
    last_event_id: str | None,
) -> AsyncGenerator[dict[str, str], None]:
    stream = get_incident_stream()
    queue = stream.subscribe()
    try:
        mode, replay = stream.get_replay(last_event_id)
        if mode == "reset":
            yield {"event": "reset", "data": json.dumps({"reason": "stale-last-event-id"})}
        else:
            yield {"comment": "ready"}
        replay_ids: set[str] = set()
        for env in replay:
            yield _frame(env)
            yield _frame_wildcard(env)
            replay_ids.add(env.event_id)
        last_delivered = replay[-1].event_id if replay else last_event_id
        while True:
            if request is not None and await request.is_disconnected():
                break
            try:
                env = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                if env.event_id in replay_ids:
                    continue
                if last_delivered is not None and env.event_id <= last_delivered:
                    continue
                yield _frame(env)
                yield _frame_wildcard(env)
                last_delivered = env.event_id
            except TimeoutError:
                yield {"comment": "heartbeat"}
    finally:
        stream.unsubscribe(queue)


def _frame(env: IncidentEnvelope) -> dict[str, str]:
    return {"id": env.event_id, "event": env.type, "data": env.model_dump_json()}


def _frame_wildcard(env: IncidentEnvelope) -> dict[str, str]:
    return {"id": env.event_id, "data": env.model_dump_json()}
