"""Signals SSE endpoint + latest-N JSON endpoint.

Implements the Hlidskjalf §6.1 Realtime-Contract for ingestion signals:
- `GET /signals/stream` — SSE with Last-Event-ID replay + reset semantics.
- `GET /signals/latest` — newest-first JSON window (default 6, max 50).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Header, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.models.signals import SignalEnvelope
from app.services.signal_stream import get_signal_stream

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/signals", tags=["signals"])

_HEARTBEAT_SECONDS = 15.0


@router.get("/latest", response_model=list[SignalEnvelope])
async def get_latest(
    limit: int = Query(default=6, ge=1, le=50),
) -> list[SignalEnvelope]:
    """Return the newest-first tail of the signal ring buffer."""
    stream = get_signal_stream()
    return stream.get_latest(limit)


async def sse_generator(
    request: Request | None,
    last_event_id: str | None,
) -> AsyncGenerator[dict[str, str], None]:
    """SSE body generator — exported for direct unit testing."""
    stream = get_signal_stream()
    mode, replay = stream.get_replay(last_event_id)
    queue = stream.subscribe()
    try:
        # Preamble: ready or reset
        if mode == "reset":
            yield {
                "event": "reset",
                "data": json.dumps({"reason": "stale-last-event-id"}),
            }
        else:
            yield {"comment": "ready"}

        # Replay in-window events (ascending)
        for envelope in replay:
            yield _frame(envelope)

        # Live tail with heartbeats
        while True:
            if request is not None and await request.is_disconnected():
                break
            try:
                envelope = await asyncio.wait_for(
                    queue.get(), timeout=_HEARTBEAT_SECONDS
                )
                yield _frame(envelope)
            except TimeoutError:
                yield {"comment": "heartbeat"}
    finally:
        stream.unsubscribe(queue)


@router.get("/stream")
async def stream_signals(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    """Server-Sent Events endpoint for ingestion signals."""
    return EventSourceResponse(sse_generator(request, last_event_id))


def _frame(envelope: SignalEnvelope) -> dict[str, str]:
    return {
        "id": envelope.event_id,
        "event": envelope.type,
        "data": envelope.model_dump_json(),
    }
