"""Severity-burst detector. DEFAULT-OFF in v1.

Cluster key is always ``severity:global``; the resulting incident is
non-spatial. ClusterStore resolves ``coords=None`` to ``(0.0, 0.0)`` and
appends ``map:no_pin`` to ``layer_hints`` — the frontend must respect this
hint or non-spatial incidents will render at Null Island.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import (
    ClusterHit,
    build_ignition_timeline_event,
    build_update_timeline_event,
)


_HIGH_SET = {"high", "critical"}


@dataclass
class _Bucket:
    signals: deque = field(default_factory=deque)
    ignited: bool = False


class SeverityBurstDetector:
    id = "severity"

    def __init__(
        self, *, config: PromoterConfig, clock: Callable[[], datetime]
    ) -> None:
        self._config = config
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {"severity:global": _Bucket()}
        self._suppressed_until: dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._config.severity_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        sev = (envelope.payload.severity or "").lower()
        if sev not in _HIGH_SET:
            return None
        cluster_key = "severity:global"
        suppress_until = self._suppressed_until.get(cluster_key)
        if suppress_until is not None:
            if self._clock() < suppress_until:
                return None
            self._suppressed_until.pop(cluster_key, None)

        bucket = self._buckets[cluster_key]
        cutoff = self._clock() - timedelta(seconds=self._config.severity_window_sec)
        while bucket.signals and bucket.signals[0][0] < cutoff:
            bucket.signals.popleft()
        bucket.signals.append((self._clock(), envelope.event_id, sev))

        if bucket.ignited:
            return self._build_update(envelope, cluster_key)
        if len(bucket.signals) >= self._config.severity_min_hits:
            bucket.ignited = True
            return self._build_ignition(envelope, cluster_key, bucket)
        return None

    def on_cluster_terminated(
        self, cluster_key: str, suppress_until: datetime | None = None
    ) -> None:
        if cluster_key != "severity:global":
            return
        self._buckets[cluster_key] = _Bucket()
        if suppress_until is None:
            self._suppressed_until.pop(cluster_key, None)
        else:
            self._suppressed_until[cluster_key] = suppress_until

    def _build_ignition(self, envelope, cluster_key, bucket: _Bucket) -> ClusterHit:
        count = len(bucket.signals)
        title = f"Severity burst · {count} high-severity signals"
        ids = [eid for _ts, eid, _sev in bucket.signals]
        surrogate = ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="", sources_to_merge=[], layer_hints_to_merge=[],
            timeline_event=None, contributing_signal_ids=[],  # type: ignore[arg-type]
        )
        return ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="",
            sources_to_merge=["severity-burst"],
            layer_hints_to_merge=[
                "events", "auto_promoter:v1", f"cluster:{cluster_key}",
            ],
            timeline_event=build_ignition_timeline_event(surrogate),
            contributing_signal_ids=ids,
        )

    def _build_update(self, envelope, cluster_key) -> ClusterHit:
        title = f"Severity hit · {envelope.payload.source}"
        surrogate = ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="", sources_to_merge=[], layer_hints_to_merge=[],
            timeline_event=None, contributing_signal_ids=[],  # type: ignore[arg-type]
        )
        return ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="",
            sources_to_merge=["severity-burst"],
            layer_hints_to_merge=[
                "events", "auto_promoter:v1", f"cluster:{cluster_key}",
            ],
            timeline_event=build_update_timeline_event(surrogate, t_offset_s=0.0),
            contributing_signal_ids=[envelope.event_id],
        )
