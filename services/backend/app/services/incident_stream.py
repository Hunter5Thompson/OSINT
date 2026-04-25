"""In-memory ring buffer + live fan-out for /api/incidents/stream.

Mirrors signal_stream.py shape (ring + replay + reset). Dedup is intentionally
absent on the publish side — the `event_id` is monotonic (`<ms>-<seq>`) and
unique by construction, and the SSE generator already gates on `event_id`
ordering during replay. Re-publishing the same logical state (e.g. two
`incident.update` for the same id) MUST reach subscribers; collapsing them
would freeze the live timeline. Idempotency for the admin trigger is the
caller's concern, not the stream's.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import UTC, datetime
from typing import Literal

import structlog

from app.models.incident import Incident, IncidentEnvelope

log = structlog.get_logger(__name__)

ReplayMode = Literal["ok", "reset"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _build_event_id(ms: int, seq: int) -> str:
    return f"{ms:013d}-{seq:06d}"


def _ms_to_iso_utc(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{ms % 1000:03d}"
    return f"{base}.{millis}Z"


class IncidentStream:
    def __init__(self, window_seconds: int = 900, max_size: int = 200) -> None:
        self._window_seconds = window_seconds
        self._max_size = max_size
        self._buffer: deque[IncidentEnvelope] = deque(maxlen=max_size)
        self._seq = 0
        self._live: list[asyncio.Queue[IncidentEnvelope]] = []

    def clear(self) -> None:
        self._buffer.clear()
        self._seq = 0

    def publish(self, type_: str, incident: Incident) -> IncidentEnvelope:
        """Append an envelope and fan out to live subscribers.

        Always returns the envelope — there is no publish-side dedup; the
        `event_id` is monotonic by construction and the SSE replay window
        is the dedup boundary on the wire.
        """
        self._prune()
        ms = _now_ms()
        self._seq = (self._seq + 1) % 1_000_000
        env = IncidentEnvelope(
            event_id=_build_event_id(ms, self._seq),
            ts=_ms_to_iso_utc(ms),
            type=type_,
            payload=incident,
        )
        self._buffer.append(env)
        for queue in list(self._live):
            try:
                queue.put_nowait(env)
            except asyncio.QueueFull:
                log.warning("incident_stream_queue_full")
        return env

    def get_latest(self, limit: int) -> list[IncidentEnvelope]:
        self._prune()
        if limit <= 0:
            return []
        items = list(self._buffer)[-limit:]
        items.reverse()
        return items

    def get_replay(
        self, last_event_id: str | None
    ) -> tuple[ReplayMode, list[IncidentEnvelope]]:
        self._prune()
        if not last_event_id:
            return "ok", []
        if not self._buffer:
            return "ok", []
        oldest = self._buffer[0]
        if last_event_id < oldest.event_id:
            return "reset", []
        return "ok", [e for e in self._buffer if e.event_id > last_event_id]

    def subscribe(self) -> asyncio.Queue[IncidentEnvelope]:
        q: asyncio.Queue[IncidentEnvelope] = asyncio.Queue(maxsize=200)
        self._live.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[IncidentEnvelope]) -> None:
        try:
            self._live.remove(queue)
        except ValueError:
            pass

    def _prune(self) -> None:
        if not self._buffer:
            return
        cutoff_ms = int((datetime.now(UTC).timestamp() - self._window_seconds) * 1000)
        while self._buffer:
            oldest = self._buffer[0]
            ms_part, _, _ = oldest.event_id.partition("-")
            try:
                oldest_ms = int(ms_part)
            except ValueError:
                self._buffer.popleft()
                continue
            if oldest_ms < cutoff_ms:
                self._buffer.popleft()
            else:
                break


_singleton: IncidentStream | None = None


def get_incident_stream() -> IncidentStream:
    global _singleton
    if _singleton is None:
        _singleton = IncidentStream()
    return _singleton
