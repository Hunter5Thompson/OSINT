from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.models.incident import Incident, IncidentStatus
from app.services.incident_stream import IncidentStream


def _incident(ordinal: int) -> Incident:
    return Incident(
        id=f"inc-{ordinal:03d}",
        kind="firms.cluster",
        title=f"x{ordinal}",
        severity="elevated",
        coords=(0.0, 0.0),
        location="-",
        status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
        sources=[],
        timeline=[],
    )


def test_publish_returns_distinct_envelopes_for_repeat_publishes() -> None:
    """Each publish() call MUST return a distinct envelope so successive
    incident.update events on the same incident reach subscribers — the
    SSE replay window is the only dedupe layer (event_id is monotonic).
    """
    stream = IncidentStream(window_seconds=60, max_size=10)
    inc = _incident(1)
    a = stream.publish("incident.open", inc)
    b = stream.publish("incident.update", inc)
    c = stream.publish("incident.update", inc)
    assert a is not None and b is not None and c is not None
    assert {a.event_id, b.event_id, c.event_id} == {a.event_id, b.event_id, c.event_id}
    assert len({a.event_id, b.event_id, c.event_id}) == 3
    assert len(stream.get_latest(10)) == 3


def test_get_replay_returns_events_after_marker() -> None:
    stream = IncidentStream(window_seconds=60, max_size=10)
    e1 = stream.publish("incident.open", _incident(1))
    e2 = stream.publish("incident.update", _incident(2))
    assert e1 is not None and e2 is not None
    mode, replay = stream.get_replay(e1.event_id)
    assert mode == "ok"
    assert [e.event_id for e in replay] == [e2.event_id]


def test_get_replay_resets_when_marker_too_old() -> None:
    stream = IncidentStream(window_seconds=60, max_size=2)
    stream.publish("incident.open", _incident(1))
    stream.publish("incident.open", _incident(2))
    stream.publish("incident.open", _incident(3))  # evicts incident-001
    mode, _ = stream.get_replay("0000000000000-000000")
    assert mode == "reset"


@pytest.mark.asyncio
async def test_subscribe_receives_live_events() -> None:
    stream = IncidentStream(window_seconds=60, max_size=10)
    queue = stream.subscribe()
    try:
        env = stream.publish("incident.open", _incident(1))
        received = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert env is not None and received.event_id == env.event_id
    finally:
        stream.unsubscribe(queue)
