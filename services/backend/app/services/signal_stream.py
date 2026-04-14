"""In-memory ring buffer + Redis-stream consumer for /api/signals.

Design notes
------------
- The `SignalStream` holds a deque of `SignalEnvelope` instances keyed by
  their `event_id`, plus a set of seen Redis record-ids for dedupe.
- `event_id` is derived directly from the Redis Stream record-id
  `<ms>-<seq>` and normalized to a fixed-width zero-padded form
  `<013d ms>-<06d seq>` so lexicographic string comparison matches
  chronological (and intra-ms) ordering. Redis stream IDs are
  monotonic-by-construction on a single stream; fixed-width padding makes
  the ordering stable under `<`/`>` on Python strings.
- Pruning happens lazily on every insert AND on every replay/latest call,
  so stale entries never leak even if ingestion goes quiet.
- The Redis consumer is a best-effort asyncio task started on FastAPI
  lifespan. If Redis is unreachable it logs a warning and retries; the
  HTTP endpoints keep working on an empty buffer.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
from typing import Literal

import redis.asyncio as redis
import structlog

from app.config import settings
from app.models.signals import SignalEnvelope, SignalPayload

logger = structlog.get_logger(__name__)

ReplayMode = Literal["ok", "reset"]

_CANONICAL_FIELDS = {"title", "severity", "source", "url", "codebook_type"}


def _ms_to_iso_utc(ms: int) -> str:
    """Render a Unix ms timestamp as ISO-8601 UTC with ms precision, 'Z' suffix."""
    dt = datetime.fromtimestamp(ms / 1000, tz=UTC)
    # isoformat gives e.g. 2026-04-14T16:42:03.482000+00:00 — trim µs → ms
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{ms % 1000:03d}"
    return f"{base}.{millis}Z"


def _parse_record_id(record_id: str) -> tuple[int, int]:
    """Split a Redis Stream record-id `<ms>-<seq>` into (ms, seq)."""
    head, _, tail = record_id.partition("-")
    return int(head), int(tail) if tail else 0


def _build_event_id(ms: int, seq: int) -> str:
    """Build a fixed-width, lexicographically-monotonic event id.

    13-digit ms covers timestamps beyond year 9000; 6-digit seq covers
    up to 999,999 concurrent same-ms entries on a single Redis stream.
    """
    return f"{ms:013d}-{seq:06d}"


class SignalStream:
    """Ring buffer + replay logic for ingestion signals."""

    def __init__(
        self,
        window_seconds: int = 900,
        max_size: int = 2000,
    ) -> None:
        self._window_seconds = window_seconds
        self._max_size = max_size
        self._buffer: deque[SignalEnvelope] = deque(maxlen=max_size)
        self._seen_record_ids: set[str] = set()
        self._live_queues: list[asyncio.Queue[SignalEnvelope]] = []
        self._lock = asyncio.Lock()

    # -- Mutation ----------------------------------------------------------

    def clear(self) -> None:
        """Reset all buffered state (used in tests)."""
        self._buffer.clear()
        self._seen_record_ids.clear()
        # Note: we intentionally leave live_queues attached; tests create
        # fresh TestClient instances which establish fresh streams.

    def insert_record(
        self, record_id: str, fields: dict[str, str]
    ) -> SignalEnvelope | None:
        """Map one Redis Stream record to an envelope and append.

        Returns `None` if the record was deduped.
        """
        if record_id in self._seen_record_ids:
            return None

        self._prune()

        try:
            ms, seq = _parse_record_id(record_id)
        except (ValueError, AttributeError):
            logger.warning("signal_stream_invalid_record_id", record_id=record_id)
            return None

        ts = _ms_to_iso_utc(ms)
        event_id = _build_event_id(ms, seq)
        codebook_type = fields.get("codebook_type") or "signal.unknown"

        payload_data: dict[str, str] = {
            "title": fields.get("title", ""),
            "severity": fields.get("severity", "low"),
            "source": fields.get("source", ""),
            "url": fields.get("url", ""),
            "redis_id": record_id,
        }
        # Pass through any extra fields we didn't canonicalize
        for key, value in fields.items():
            if key not in _CANONICAL_FIELDS and key not in payload_data:
                payload_data[key] = value

        envelope = SignalEnvelope(
            event_id=event_id,
            ts=ts,
            type=codebook_type,
            payload=SignalPayload(**payload_data),
        )

        # If the buffer hit max_size, deque pops the oldest — keep seen-set
        # bounded to live entries to avoid unbounded growth.
        if len(self._buffer) == self._max_size and self._buffer:
            evicted = self._buffer[0]
            self._seen_record_ids.discard(evicted.payload.redis_id)

        self._buffer.append(envelope)
        self._seen_record_ids.add(record_id)

        # Fan out to live subscribers (best-effort, drop if queue is full).
        for queue in list(self._live_queues):
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                logger.warning("signal_stream_queue_full")

        return envelope

    # -- Read --------------------------------------------------------------

    def get_latest(self, limit: int) -> list[SignalEnvelope]:
        self._prune()
        if limit <= 0:
            return []
        items = list(self._buffer)[-limit:]
        items.reverse()  # newest first
        return items

    def get_replay(
        self, last_event_id: str | None
    ) -> tuple[ReplayMode, list[SignalEnvelope]]:
        self._prune()
        if last_event_id is None or last_event_id == "":
            return "ok", []
        if not self._buffer:
            return "ok", []
        oldest = self._buffer[0]
        if last_event_id < oldest.event_id:
            return "reset", []
        return "ok", [e for e in self._buffer if e.event_id > last_event_id]

    # -- Live subscription (SSE fan-out) -----------------------------------

    def subscribe(self) -> asyncio.Queue[SignalEnvelope]:
        queue: asyncio.Queue[SignalEnvelope] = asyncio.Queue(maxsize=1000)
        self._live_queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[SignalEnvelope]) -> None:
        try:
            self._live_queues.remove(queue)
        except ValueError:
            pass

    # -- Internal ----------------------------------------------------------

    def _prune(self) -> None:
        if not self._buffer:
            return
        cutoff_ms = int(
            (datetime.now(UTC).timestamp() - self._window_seconds) * 1000
        )
        while self._buffer:
            oldest = self._buffer[0]
            try:
                ms_part, _, _ = oldest.event_id.partition("-")
                oldest_ms = int(ms_part)
            except ValueError:
                self._buffer.popleft()
                self._seen_record_ids.discard(oldest.payload.redis_id)
                continue
            if oldest_ms < cutoff_ms:
                self._buffer.popleft()
                self._seen_record_ids.discard(oldest.payload.redis_id)
            else:
                break


# ---------------------------------------------------------------------------
# Singleton + Redis consumer
# ---------------------------------------------------------------------------


_signal_stream: SignalStream | None = None


def get_signal_stream() -> SignalStream:
    global _signal_stream
    if _signal_stream is None:
        _signal_stream = SignalStream(
            window_seconds=settings.signals_replay_window_seconds,
            max_size=settings.signals_ring_buffer_size,
        )
    return _signal_stream


async def redis_consumer_loop(
    stream: SignalStream,
    stop_event: asyncio.Event,
) -> None:
    """Background loop: XREAD from Redis stream and feed the ring buffer.

    Resilient: if Redis is down we log and retry with backoff; the buffer
    simply stays empty and the HTTP endpoints continue to serve.
    """
    last_id = "$"  # only new entries after startup
    block_ms = max(100, settings.signals_poll_interval_ms)
    stream_key = settings.redis_stream_events
    client: redis.Redis | None = None

    while not stop_event.is_set():
        try:
            if client is None:
                client = redis.from_url(settings.redis_url, decode_responses=True)
                await client.ping()
                logger.info("signal_stream_redis_connected", stream=stream_key)

            response = await client.xread(
                {stream_key: last_id}, block=block_ms, count=100
            )
            if not response:
                continue
            for _stream_name, entries in response:
                for record_id, fields in entries:
                    stream.insert_record(record_id, dict(fields))
                    last_id = record_id
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001 — resilience
            logger.warning(
                "signal_stream_consumer_error",
                error=str(exc),
            )
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
                client = None
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2.0)
            except TimeoutError:
                pass

    if client is not None:
        try:
            await client.close()
        except Exception:
            pass
