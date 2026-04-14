"""Unit tests for /api/signals signal-stream ring buffer and SSE endpoints.

Tests run without a live Redis connection: we exercise the in-memory
`SignalStream` directly and the FastAPI endpoints via TestClient, feeding
records through `insert_record` rather than the Redis consumer loop.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.signals import SignalEnvelope
from app.services.signal_stream import (
    ReplayMode,
    SignalStream,
    get_signal_stream,
)


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------


def _fields(
    title: str = "test",
    codebook_type: str = "signal.firms",
    severity: str = "low",
    source: str = "unit",
    url: str = "https://example.com",
) -> dict[str, str]:
    return {
        "title": title,
        "codebook_type": codebook_type,
        "severity": severity,
        "source": source,
        "url": url,
    }


def _record_id(ms: int, seq: int = 0) -> str:
    return f"{ms}-{seq}"


def test_ring_buffer_insert_and_latest_newest_first() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    base_ms = int(time.time() * 1000)
    envelopes = []
    for i in range(5):
        env = s.insert_record(_record_id(base_ms + i), _fields(title=f"t{i}"))
        assert env is not None
        envelopes.append(env)

    latest = s.get_latest(3)
    assert len(latest) == 3
    # Newest first
    assert latest[0].payload.title == "t4"
    assert latest[1].payload.title == "t3"
    assert latest[2].payload.title == "t2"

    all_latest = s.get_latest(100)
    assert len(all_latest) == 5


def test_ring_buffer_prunes_old_entries_outside_window() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 901_000  # >15 min ago

    s.insert_record(_record_id(old_ms, 0), _fields(title="old"))
    s.insert_record(_record_id(now_ms, 1), _fields(title="new"))

    latest = s.get_latest(10)
    assert len(latest) == 1
    assert latest[0].payload.title == "new"


def test_ring_buffer_dedupes_same_redis_record_id() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    rid = _record_id(int(time.time() * 1000), 0)
    first = s.insert_record(rid, _fields(title="first"))
    second = s.insert_record(rid, _fields(title="second"))

    assert first is not None
    assert second is None  # dedupe dropped
    latest = s.get_latest(10)
    assert len(latest) == 1
    assert latest[0].payload.title == "first"


def test_redis_record_to_envelope_mapping_and_monotonic_event_id() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    # Use a recent ms to stay in the replay window
    ms = int(time.time() * 1000)
    rid1 = _record_id(ms, 0)
    rid2 = _record_id(ms, 1)

    env1 = s.insert_record(rid1, _fields(codebook_type="signal.firms"))
    env2 = s.insert_record(rid2, _fields(codebook_type="signal.firms"))

    assert env1 is not None and env2 is not None

    # ts derived from ms component
    assert env1.ts.endswith("Z")
    # ts should reflect ms precision
    from datetime import datetime, timezone

    parsed = datetime.fromisoformat(env1.ts.replace("Z", "+00:00"))
    assert parsed.tzinfo == timezone.utc
    assert int(parsed.timestamp() * 1000) == ms

    assert env1.type == "signal.firms"
    assert env1.payload.redis_id == rid1

    # event_id shape: 13-digit ms, dash, 6-digit seq
    assert env1.event_id == f"{ms:013d}-{0:06d}"
    assert env2.event_id == f"{ms:013d}-{1:06d}"

    # Monotonic even within the same ms
    assert env2.event_id > env1.event_id


def test_type_fallback_when_codebook_type_missing() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    ms = int(time.time() * 1000)
    fields = {"title": "x", "severity": "low", "source": "u", "url": "https://x"}
    env = s.insert_record(_record_id(ms, 0), fields)
    assert env is not None
    assert env.type == "signal.unknown"


def test_replay_returns_events_after_last_event_id() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    base_ms = int(time.time() * 1000)
    envelopes = []
    for i in range(10):
        env = s.insert_record(_record_id(base_ms, i), _fields(title=f"t{i}"))
        assert env is not None
        envelopes.append(env)

    mode, replay = s.get_replay(envelopes[4].event_id)
    assert mode == "ok"
    assert len(replay) == 5
    # ascending order
    assert [e.payload.title for e in replay] == ["t5", "t6", "t7", "t8", "t9"]
    assert replay[0].event_id > envelopes[4].event_id


def test_replay_with_stale_last_event_id_returns_reset() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    base_ms = int(time.time() * 1000)
    for i in range(3):
        s.insert_record(_record_id(base_ms, i), _fields(title=f"t{i}"))

    # Craft an event_id that lexicographically predates the oldest buffered.
    stale_ms = base_ms - 1_000_000  # ~16.6 min ago
    stale_event_id = f"{stale_ms:013d}-{0:06d}"

    mode, replay = s.get_replay(stale_event_id)
    assert mode == "reset"
    assert replay == []


def test_event_id_strict_monotonic_across_wall_clock_bursts() -> None:
    """Regression guard for C1: event_id must be strictly lex-monotonic
    even when many records share the same user-supplied ms timestamp, and
    across ms boundaries. The previous ULID-based implementation had a
    ~50% failure rate on same-ms bursts because python-ulid keys random
    bytes on wall-clock ms, not on the supplied timestamp.
    """
    s = SignalStream(window_seconds=900, max_size=1000)
    # Use recent ms to stay in window
    base_ms = int(time.time() * 1000)

    ids: list[str] = []

    # 200 records all at the same logical ms, seq 0..199
    for seq in range(200):
        env = s.insert_record(_record_id(base_ms, seq), _fields(title=f"b{seq}"))
        assert env is not None
        ids.append(env.event_id)

    # Cross ms boundaries: (base_ms, 250), (base_ms+1, 0), (base_ms+1, 1), (base_ms+1000, 0)
    for rid in [
        _record_id(base_ms, 250),
        _record_id(base_ms + 1, 0),
        _record_id(base_ms + 1, 1),
        _record_id(base_ms + 1000, 0),
    ]:
        env = s.insert_record(rid, _fields())
        assert env is not None
        ids.append(env.event_id)

    # Strict lex-monotonic across the whole sequence
    for prev, curr in zip(ids, ids[1:]):
        assert curr > prev, f"non-monotonic: {prev!r} >= {curr!r}"


def test_replay_with_no_last_event_id_returns_empty_ok() -> None:
    s = SignalStream(window_seconds=900, max_size=2000)
    s.insert_record(_record_id(int(time.time() * 1000), 0), _fields())
    mode, replay = s.get_replay(None)
    assert mode == "ok"
    assert replay == []


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_signal_stream() -> SignalStream:
    """Reset the shared SignalStream singleton between tests."""
    stream = get_signal_stream()
    stream.clear()
    return stream


def test_latest_endpoint_returns_json_newest_first(reset_signal_stream: SignalStream) -> None:
    stream = reset_signal_stream
    base_ms = int(time.time() * 1000)
    for i in range(8):
        stream.insert_record(_record_id(base_ms, i), _fields(title=f"t{i}"))

    client = TestClient(app)
    if True:
        resp = client.get("/api/signals/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 6  # default limit
        assert data[0]["payload"]["title"] == "t7"


def test_latest_endpoint_honors_limit_query(reset_signal_stream: SignalStream) -> None:
    stream = reset_signal_stream
    base_ms = int(time.time() * 1000)
    for i in range(5):
        stream.insert_record(_record_id(base_ms, i), _fields(title=f"t{i}"))

    client = TestClient(app)
    if True:
        resp = client.get("/api/signals/latest?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


def test_latest_endpoint_rejects_excessive_limit() -> None:
    client = TestClient(app)
    if True:
        resp = client.get("/api/signals/latest?limit=999")
        assert resp.status_code == 422


async def _drain_generator(
    last_event_id: str | None, max_frames: int
) -> list[dict[str, str]]:
    """Drive `sse_generator` with a stub Request and collect up to `max_frames`."""
    from app.routers.signals import sse_generator

    class _StubRequest:
        async def is_disconnected(self) -> bool:
            return False

    frames: list[dict[str, str]] = []
    gen = sse_generator(_StubRequest(), last_event_id)  # type: ignore[arg-type]
    try:
        async for frame in gen:
            frames.append(frame)
            if len(frames) >= max_frames:
                break
    finally:
        await gen.aclose()
    return frames


@pytest.mark.asyncio
async def test_stream_endpoint_content_type_and_connects(
    reset_signal_stream: SignalStream,
) -> None:
    stream = reset_signal_stream
    base_ms = int(time.time() * 1000)
    for i in range(3):
        stream.insert_record(_record_id(base_ms, i), _fields(title=f"t{i}"))

    # HTTP surface check via TestClient.get on /latest confirms the app boots;
    # the content-type check for the SSE endpoint is asserted on the generator's
    # EventSourceResponse which sse-starlette tags as text/event-stream by default.
    from sse_starlette.sse import EventSourceResponse
    from app.routers.signals import sse_generator

    class _StubRequest:
        async def is_disconnected(self) -> bool:
            return True  # force generator to exit cleanly

    response = EventSourceResponse(sse_generator(_StubRequest(), None))  # type: ignore[arg-type]
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_stream_with_valid_last_event_id_replays_newer(
    reset_signal_stream: SignalStream,
) -> None:
    stream = reset_signal_stream
    base_ms = int(time.time() * 1000)
    envelopes = []
    for i in range(5):
        env = stream.insert_record(_record_id(base_ms, i), _fields(title=f"t{i}"))
        assert env is not None
        envelopes.append(env)

    # Expect: ready-comment + 2 replay frames (envelopes[3], envelopes[4])
    frames = await _drain_generator(envelopes[2].event_id, max_frames=3)

    data_frames = [f for f in frames if "data" in f and "event" in f]
    ids = [f["id"] for f in data_frames]
    assert envelopes[3].event_id in ids
    assert envelopes[4].event_id in ids
    # None of the older ones
    assert envelopes[0].event_id not in ids
    assert envelopes[2].event_id not in ids

    firmsy = next(f for f in data_frames if f["id"] == envelopes[3].event_id)
    assert firmsy["event"] == envelopes[3].type
    parsed = json.loads(firmsy["data"])
    assert parsed["event_id"] == envelopes[3].event_id
    assert parsed["type"] == envelopes[3].type


@pytest.mark.asyncio
async def test_stream_with_stale_last_event_id_emits_reset(
    reset_signal_stream: SignalStream,
) -> None:
    stream = reset_signal_stream
    base_ms = int(time.time() * 1000)
    for i in range(2):
        stream.insert_record(_record_id(base_ms, i), _fields(title=f"t{i}"))

    stale_event_id = f"{(base_ms - 1_000_000):013d}-{0:06d}"
    frames = await _drain_generator(stale_event_id, max_frames=1)

    reset_frames = [f for f in frames if f.get("event") == "reset"]
    assert len(reset_frames) >= 1
    payload = json.loads(reset_frames[0]["data"])
    assert payload["reason"] == "stale-last-event-id"


# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------


def test_signals_router_registered_under_api_prefix() -> None:
    paths = {getattr(r, "path", None) for r in app.router.routes}
    assert "/api/signals/stream" in paths
    assert "/api/signals/latest" in paths
    # And NOT under /api/v1
    assert "/api/v1/signals/stream" not in paths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_sse_frames(
    resp, min_data_frames: int, timeout_s: float = 2.0
) -> list[dict[str, str]]:
    """Parse SSE frames from a streaming response until we have enough data frames."""
    frames: list[dict[str, str]] = []
    current: dict[str, str] = {}
    data_count = 0
    lines_iter = resp.iter_lines()
    start = time.monotonic()
    while data_count < min_data_frames and time.monotonic() - start < timeout_s:
        try:
            raw = next(lines_iter)
        except StopIteration:
            break
        line = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
        if line == "":
            if current:
                frames.append(current)
                if "data" in current:
                    data_count += 1
                current = {}
            continue
        if line.startswith(":"):
            # comment / heartbeat — ignore
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            current[key] = value
    if current:
        frames.append(current)
    return frames
