"""In-memory cluster lifecycle store for the auto-promoter.

Phase 1 deliverable: data structures and listener registration only.
``handle()``, ``mark_promoted``, ``mark_silenced``, and the sweeper hooks
are added in Phase 4 alongside the FIRMS detector that drives them.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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


@dataclass
class SweepSnapshot:
    stale_open: list[ClusterState]
    stale_promoted: list[ClusterState]
    expired_cooldown_keys: list[str]


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

    def get_by_cluster_key(self, cluster_key: str) -> ClusterState | None:
        return self._by_key.get(cluster_key)

    async def handle(
        self,
        hit,                                # ClusterHit — quoted to avoid circular import
        *,
        incident_store,
        incident_event_stream,
    ) -> None:
        """Phased locking: decide and reserve, then I/O, then finalize."""
        from app.models.incident import IncidentCreateRequest
        from app.services.incident_promoter.detectors.base import ClusterHit  # noqa: F401

        now = self._clock()

        # Phase 1: decide + reserve under lock
        async with self._lock:
            cooldown_until = self._cooldowns.get(hit.cluster_key)
            if cooldown_until is not None:
                if now < cooldown_until:
                    logger.info(
                        "promoter_cluster_silenced",
                        cluster_key=hit.cluster_key,
                        cooldown_seconds=int((cooldown_until - now).total_seconds()),
                    )
                    return
                self._cooldowns.pop(hit.cluster_key, None)

            existing = self._by_key.get(hit.cluster_key)
            if existing is None:
                if hit.cluster_key in self._reserving:
                    logger.info("promoter_race_dropped", cluster_key=hit.cluster_key)
                    return
                self._reserving.add(hit.cluster_key)
                action = "create"
            elif existing.incident_status == "promoted":
                existing.last_signal_ts = now
                logger.info(
                    "promoter_promoted_absorb",
                    cluster_key=hit.cluster_key,
                    incident_id=existing.incident_id,
                )
                return
            else:
                action = "update"

        # Phase 2: I/O outside lock
        if action == "create":
            coords, extra_hints = self._resolve_create_coords(hit)
            # `hit_count` is the count of *contributing signals* (per spec §5.1).
            # Ignition packs all accumulated event_ids into contributing_signal_ids,
            # so a 3-detection FIRMS ignition opens with hit_count=3.
            initial_count = max(1, len(hit.contributing_signal_ids))
            initial_severity = _max_severity(
                hit.severity, _apply_escalation_rule(hit.detector_id, initial_count)
            )
            request = IncidentCreateRequest(
                title=hit.title,
                kind=hit.incident_kind,
                severity=initial_severity,  # type: ignore[arg-type]
                coords=coords,
                location=hit.location,
                sources=list(hit.sources_to_merge),
                layer_hints=list(dict.fromkeys([*hit.layer_hints_to_merge, *extra_hints])),
                initial_text=hit.title,
            )
            try:
                incident = await incident_store.create_incident(request)
            except Exception as exc:  # noqa: BLE001 — resilience
                async with self._lock:
                    self._reserving.discard(hit.cluster_key)
                logger.warning(
                    "promoter_create_failed", cluster_key=hit.cluster_key, error=str(exc)
                )
                return

            # Phase 3: finalize
            async with self._lock:
                self._by_key[hit.cluster_key] = ClusterState(
                    cluster_key=hit.cluster_key,
                    incident_id=incident.id,
                    detector_id=hit.detector_id,
                    severity=initial_severity,
                    coords=coords,
                    hit_count=initial_count,
                    last_signal_ts=now,
                    created_ts=now,
                    contributing_signal_ids=list(hit.contributing_signal_ids[-50:]),
                    incident_status="open",
                )
                self._by_incident_id[incident.id] = hit.cluster_key
                self._reserving.discard(hit.cluster_key)
            incident_event_stream.publish("incident.open", incident)
            logger.info(
                "promoter_cluster_opened",
                cluster_key=hit.cluster_key,
                detector_id=hit.detector_id,
                incident_id=incident.id,
                severity=initial_severity,
            )
            return

        # action == "update"
        # Recompute the timeline event with the correct t_offset_s relative to created_ts.
        offset = (now - existing.created_ts).total_seconds()
        from app.models.incident import IncidentTimelineEvent  # local import to avoid cycles
        update_event = IncidentTimelineEvent(
            t_offset_s=max(0.0, offset),
            kind=hit.timeline_event.kind,
            text=hit.timeline_event.text,
            severity=hit.timeline_event.severity,
        )
        # Count this hit's contributing signals (==1 for normal updates) and
        # let the per-detector escalation curve speak. The detector itself
        # may also already emit a higher hit.severity (e.g. GDELT tone>=9),
        # so we take the max of all three (existing / hit / rule-based).
        next_count = existing.hit_count + max(1, len(hit.contributing_signal_ids))
        rule_based = _apply_escalation_rule(existing.detector_id, next_count)
        new_severity = _max_severity(_max_severity(existing.severity, hit.severity), rule_based)
        try:
            incident = await incident_store.apply_signal_update(
                existing.incident_id,
                timeline_event=update_event,
                severity=new_severity,
                sources_to_merge=hit.sources_to_merge,
                layer_hints_to_merge=hit.layer_hints_to_merge,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "promoter_update_failed",
                cluster_key=hit.cluster_key,
                incident_id=existing.incident_id,
                error=str(exc),
            )
            return
        if incident is None:
            return
        async with self._lock:
            existing.hit_count = next_count
            existing.last_signal_ts = now
            existing.severity = new_severity
            existing.contributing_signal_ids = (
                existing.contributing_signal_ids + list(hit.contributing_signal_ids)
            )[-50:]
        incident_event_stream.publish("incident.update", incident)
        logger.info(
            "promoter_cluster_updated",
            cluster_key=hit.cluster_key,
            incident_id=incident.id,
            hit_count=existing.hit_count,
            severity=new_severity,
        )

    async def mark_promoted(self, incident_id: str) -> None:
        """Mark a cluster as promoted. No-op if incident_id is unknown."""
        async with self._lock:
            cluster_key = self._by_incident_id.get(incident_id)
            if cluster_key is None:
                return
            state = self._by_key.get(cluster_key)
            if state is None:
                return
            state.incident_status = "promoted"
        logger.info("promoter_mark_promoted", cluster_key=cluster_key, incident_id=incident_id)

    async def mark_silenced(self, incident_id: str, *, until: datetime) -> None:
        """Mark a cluster as silenced: remove state, record cooldown, fire listeners."""
        async with self._lock:
            cluster_key = self._by_incident_id.get(incident_id)
            if cluster_key is None:
                return
            self._by_key.pop(cluster_key, None)
            self._by_incident_id.pop(incident_id, None)
            self._cooldowns[cluster_key] = until
        # Fan-out outside the lock — listeners are local + cheap.
        self._fire_terminated(cluster_key, suppress_until=until)
        logger.info(
            "promoter_mark_silenced",
            cluster_key=cluster_key,
            incident_id=incident_id,
            cooldown_seconds=int((until - self._clock()).total_seconds()),
        )

    def snapshot_for_sweep(
        self, *, quiet_window_sec: int, now: datetime
    ) -> SweepSnapshot:
        """Classify clusters and cooldowns for sweeping.

        Returns clusters stale (last_signal_ts <= cutoff) separated by status,
        and expired cooldowns (expiry_time <= now).
        """
        cutoff = now - timedelta(seconds=quiet_window_sec)
        stale_open: list[ClusterState] = []
        stale_promoted: list[ClusterState] = []
        for state in self._by_key.values():
            if state.last_signal_ts > cutoff:
                continue
            if state.incident_status == "promoted":
                stale_promoted.append(state)
            else:
                stale_open.append(state)
        expired = [k for k, t in self._cooldowns.items() if t <= now]
        return SweepSnapshot(stale_open, stale_promoted, expired)

    async def drop_cluster(self, cluster_key: str) -> None:
        """Remove a cluster (state + mapping) and fire termination listeners."""
        async with self._lock:
            state = self._by_key.pop(cluster_key, None)
            if state is not None:
                self._by_incident_id.pop(state.incident_id, None)
        if state is not None:
            self._fire_terminated(cluster_key)

    def pop_expired_cooldowns(self, expired: list[str]) -> None:
        """Remove expired cooldown keys from the store."""
        for k in expired:
            self._cooldowns.pop(k, None)

    def _fire_terminated(
        self, cluster_key: str, *, suppress_until: datetime | None = None
    ) -> None:
        """Fire all termination listeners with a copy of the list."""
        for listener in list(self._termination_listeners):
            try:
                listener(cluster_key, suppress_until=suppress_until)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "promoter_terminate_callback_failed", cluster_key=cluster_key
                )

    def _resolve_create_coords(
        self, hit
    ) -> tuple[tuple[float, float], list[str]]:
        """Pick representative coords for the new incident.

        - hit.coords is not None → use it; no extra layer hints.
        - hit.coords is None → fall back to (0.0, 0.0) and append "map:no_pin".
        """
        if hit.coords is not None:
            return hit.coords, []
        return (0.0, 0.0), ["map:no_pin"]


_SEVERITY_RANK: dict[str, int] = {
    "low": 0,
    "elevated": 1,
    "high": 2,
    "critical": 3,
}


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK[a] >= _SEVERITY_RANK[b] else b


# Per-detector escalation curves (spec §4.3). Entries are ordered
# high-threshold-first; the first matching threshold wins.
_ESCALATION_RULES: dict[str, list[tuple[int, str]]] = {
    "firms":    [(10, "critical"), (0, "high")],
    "severity": [(10, "critical"), (0, "high")],
    "telegram": [(10, "critical"), (5, "high"), (0, "elevated")],
    "gdelt":    [(15, "critical"), (10, "high"), (0, "elevated")],
}


def _apply_escalation_rule(detector_id: str, hit_count: int) -> str:
    """Return the rule-based severity floor for a (detector_id, hit_count)."""
    rules = _ESCALATION_RULES.get(detector_id, [(0, "low")])
    for threshold, sev in rules:                          # already sorted high→low
        if hit_count >= threshold:
            return sev
    return "low"
