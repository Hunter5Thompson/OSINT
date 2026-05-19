"""Shared fixtures for incident_promoter tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.models.signals import SignalEnvelope, SignalPayload


class FakeClock:
    """Mutable clock for deterministic tests. Call ``advance`` to move time."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)

    def set(self, ts: datetime) -> None:
        self._now = ts


class FakeIncidentStore:
    """In-process incident store with the methods used by the Promoter."""

    def __init__(self) -> None:
        self._by_id: dict[str, Incident] = {}

    async def create_incident(self, req: IncidentCreateRequest) -> Incident:
        incident_id = f"inc-{uuid4().hex[:8]}"
        initial = IncidentTimelineEvent(
            t_offset_s=0.0,
            kind="trigger",
            text=req.initial_text or f"trigger · {req.kind}",
            severity=req.severity,
        )
        record = Incident(
            id=incident_id,
            kind=req.kind,
            title=req.title,
            severity=req.severity,
            coords=req.coords,
            location=req.location,
            status=IncidentStatus.OPEN,
            trigger_ts=datetime.now(UTC),
            sources=list(req.sources),
            layer_hints=list(req.layer_hints),
            timeline=[initial],
        )
        self._by_id[incident_id] = record
        return record

    async def apply_signal_update(
        self,
        incident_id: str,
        *,
        timeline_event: IncidentTimelineEvent,
        severity: str,
        sources_to_merge: list[str],
        layer_hints_to_merge: list[str],
    ) -> Incident | None:
        current = self._by_id.get(incident_id)
        if current is None:
            return None
        merged_sources = list(dict.fromkeys([*current.sources, *sources_to_merge]))
        merged_hints = list(dict.fromkeys([*current.layer_hints, *layer_hints_to_merge]))
        next_record = current.model_copy(
            update={
                "timeline": [*current.timeline, timeline_event],
                "severity": severity,  # type: ignore[arg-type]
                "sources": merged_sources,
                "layer_hints": merged_hints,
            }
        )
        self._by_id[incident_id] = next_record
        return next_record

    async def close_incident(
        self,
        incident_id: str,
        status: IncidentStatus,
        when: datetime | None = None,
    ) -> Incident | None:
        current = self._by_id.get(incident_id)
        if current is None:
            return None
        if current.status != IncidentStatus.OPEN:
            return current  # idempotent
        next_record = current.model_copy(
            update={"status": status, "closed_ts": when or datetime.now(UTC)}
        )
        self._by_id[incident_id] = next_record
        return next_record

    async def list_owned_for_rehydrate(self) -> list[Incident]:
        return [
            i
            for i in self._by_id.values()
            if i.status in (IncidentStatus.OPEN, IncidentStatus.PROMOTED)
            and "auto_promoter:v1" in i.layer_hints
        ]

    # Test helpers — direct read access
    def get(self, incident_id: str) -> Incident | None:
        return self._by_id.get(incident_id)

    def all(self) -> list[Incident]:
        return list(self._by_id.values())


class FakeIncidentEventStream:
    """Collecting stub for the SSE event stream."""

    def __init__(self) -> None:
        self.published: list[tuple[str, Incident]] = []

    def publish(self, type_: str, incident: Incident) -> None:
        self.published.append((type_, incident))

    def types(self) -> list[str]:
        return [t for t, _ in self.published]


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_incident_store() -> FakeIncidentStore:
    return FakeIncidentStore()


@pytest.fixture
def fake_incident_event_stream() -> FakeIncidentEventStream:
    return FakeIncidentEventStream()


@pytest.fixture
def signal_envelope_factory():
    counter = {"i": 0}

    def make(
        *,
        source: str = "firms",
        title: str = "Thermal anomaly detected",
        severity: str = "low",
        url: str = "",
        ts: datetime | None = None,
        codebook_type: str = "other.unclassified",
        extras: dict[str, Any] | None = None,
    ) -> SignalEnvelope:
        counter["i"] += 1
        ms = int((ts or datetime.now(UTC)).timestamp() * 1000)
        seq = counter["i"]
        event_id = f"{ms:013d}-{seq:06d}"
        record_id = f"{ms}-{seq}"
        payload_kwargs = {
            "title": title,
            "severity": severity,
            "source": source,
            "url": url,
            "redis_id": record_id,
        }
        if extras:
            payload_kwargs.update(extras)
        return SignalEnvelope(
            event_id=event_id,
            ts=(ts or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            type=codebook_type,
            payload=SignalPayload(**payload_kwargs),
        )

    return make
