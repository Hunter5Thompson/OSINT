"""Detector protocol and shared dataclasses.

Detectors observe :class:`SignalEnvelope`s and emit a :class:`ClusterHit`
only when an action is required on the ``ClusterStore`` (an ignition or
an update against an already-ignited cluster). All threshold logic lives
inside detectors; the store decides only "create vs. update vs. drop".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models.incident import IncidentTimelineEvent
from app.models.signals import SignalEnvelope


@dataclass(frozen=True)
class ClusterHit:
    """Actionable detector output. See §4.1 of the design spec."""

    cluster_key: str
    detector_id: str
    incident_kind: str
    title: str
    severity: str  # Severity literal
    coords: tuple[float, float] | None
    location: str
    sources_to_merge: list[str]
    layer_hints_to_merge: list[str]
    timeline_event: IncidentTimelineEvent
    contributing_signal_ids: list[str]


class Detector(Protocol):
    """Behavioural protocol for all detectors.

    Concrete detectors keep per-bucket state internally and never mutate
    ``ClusterStore`` or Neo4j. ``detect`` returns ``None`` for signals that
    do not yet qualify (pre-trigger accumulation) or that fall inside a
    suppression cooldown for their cluster key.
    """

    id: str
    enabled: bool

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None: ...

    def on_cluster_terminated(
        self,
        cluster_key: str,
        suppress_until: datetime | None = None,
    ) -> None: ...


def build_ignition_timeline_event(hit: ClusterHit) -> IncidentTimelineEvent:
    """Trigger event for ``create_incident`` — exactly one entry."""
    return IncidentTimelineEvent(
        t_offset_s=0.0,
        kind="trigger",
        text=hit.title,
        severity=hit.severity,  # type: ignore[arg-type]
    )


def build_update_timeline_event(
    hit: ClusterHit, *, t_offset_s: float
) -> IncidentTimelineEvent:
    """One timeline entry appended via ``apply_signal_update``."""
    return IncidentTimelineEvent(
        t_offset_s=t_offset_s,
        kind="observation",
        text=hit.title,
        severity=hit.severity,  # type: ignore[arg-type]
    )
