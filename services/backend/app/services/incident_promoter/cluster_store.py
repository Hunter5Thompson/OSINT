"""In-memory cluster lifecycle store for the auto-promoter.

Phase 1 deliverable: data structures and listener registration only.
``handle()``, ``mark_promoted``, ``mark_silenced``, and the sweeper hooks
are added in Phase 4 alongside the FIRMS detector that drives them.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

ClusterIncidentStatus = Literal["open", "promoted"]
TerminationListener = Callable[..., None]
"""Signature: ``listener(cluster_key: str, suppress_until: datetime | None = None) -> None``."""


@dataclass
class ClusterState:
    cluster_key: str
    incident_id: str
    detector_id: str
    severity: str
    coords: tuple[float, float]
    hit_count: int
    last_signal_ts: datetime
    created_ts: datetime
    contributing_signal_ids: list[str] = field(default_factory=list)
    incident_status: ClusterIncidentStatus = "open"


class ClusterStore:
    """In-memory cluster lifecycle. All mutations are guarded by an asyncio lock."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._by_key: dict[str, ClusterState] = {}
        self._by_incident_id: dict[str, str] = {}
        self._reserving: set[str] = set()
        self._cooldowns: dict[str, datetime] = {}
        self._termination_listeners: list[TerminationListener] = []
        self._lock = asyncio.Lock()

    # -- registration ----------------------------------------------------

    def add_termination_listener(self, listener: TerminationListener) -> None:
        """Detectors register here at Promoter init (before any signal arrives)."""
        self._termination_listeners.append(listener)

    # -- read-only snapshots ---------------------------------------------

    def is_empty(self) -> bool:
        return not self._by_key and not self._cooldowns and not self._reserving

    def active_clusters(self) -> list[ClusterState]:
        """Snapshot copy — safe to read without the lock for inspector / debug."""
        return list(self._by_key.values())

    def cooldowns(self) -> dict[str, datetime]:
        return dict(self._cooldowns)

    def get_by_incident_id(self, incident_id: str) -> ClusterState | None:
        cluster_key = self._by_incident_id.get(incident_id)
        if cluster_key is None:
            return None
        return self._by_key.get(cluster_key)
