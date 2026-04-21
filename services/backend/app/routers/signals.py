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
    # Subscribe BEFORE computing replay so that events inserted in the race
    # window between the two calls are captured in the live queue. We then
    # de-duplicate any queued items that were also covered by the replay.
    queue = stream.subscribe()
    try:
        mode, replay = stream.get_replay(last_event_id)

        # Preamble: ready or reset
        if mode == "reset":
            yield {
                "event": "reset",
                "data": json.dumps({"reason": "stale-last-event-id"}),
            }
        else:
            yield {"comment": "ready"}

        # Replay in-window events (ascending)
        replay_ids: set[str] = set()
        for envelope in replay:
            yield _frame(envelope)
            yield _frame_wildcard(envelope)
            replay_ids.add(envelope.event_id)

        # Highest id already delivered via replay — any live-queue items at
        # or below this id were already emitted and must be skipped.
        last_delivered = replay[-1].event_id if replay else last_event_id

        # Live tail with heartbeats
        while True:
            if request is not None and await request.is_disconnected():
                break
            try:
                envelope = await asyncio.wait_for(
                    queue.get(), timeout=_HEARTBEAT_SECONDS
                )
                # Drop anything already covered by the replay (exact match
                # or lex-below the highest replayed id).
                if envelope.event_id in replay_ids:
                    continue
                if last_delivered is not None and envelope.event_id <= last_delivered:
                    continue
                yield _frame(envelope)
                yield _frame_wildcard(envelope)
                last_delivered = envelope.event_id
            except TimeoutError:
                yield {"comment": "heartbeat"}
    finally:
        stream.unsubscribe(queue)


@router.get("/stream")
async def stream_signals(
    request: Request,
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
) -> EventSourceResponse:
    """Server-Sent Events endpoint for ingestion signals.

    The standard `Last-Event-ID` header is preferred; when absent (e.g. on
    explicit client reconnects — native `EventSource` cannot set custom
    headers), the `?last_event_id=` query parameter is used as a fallback.
    If both are supplied, the header wins.
    """
    last_event_id = last_event_id_header or last_event_id_query
    return EventSourceResponse(sse_generator(request, last_event_id))


def _frame(envelope: SignalEnvelope) -> dict[str, str]:
    return {
        "id": envelope.event_id,
        "event": envelope.type,
        "data": envelope.model_dump_json(),
    }


def _frame_wildcard(envelope: SignalEnvelope) -> dict[str, str]:
    """Unnamed SSE frame — triggers EventSource.onmessage in real browsers.

    Paired with _frame() so clients that register per-type addEventListener
    AND clients that rely on onmessage both receive every envelope. The
    frontend dedupes via event_id (see hooks/useSignalFeed.ts::rememberSeen)
    so the double-emit is safe.
    """
    return {
        "id": envelope.event_id,
        "data": envelope.model_dump_json(),
    }
