"""FIRMS Geo-Cluster Detector.

Watches FIRMS signals (``payload.source == "firms"``), buckets them by
rounded lat/lon, and ignites a cluster once ``firms_min_hits`` detections
accumulate inside the configured window.
"""
from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import ClusterHit

_COORD_RE = re.compile(
    r"@(?P<lat>-?\d+(?:\.\d+)?),(?P<lon>-?\d+(?:\.\d+)?),"
)


def _parse_firms_coords(url: str | None) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` extracted from a FIRMS map URL, or ``None``."""
    if not url:
        return None
    match = _COORD_RE.search(url)
    if not match:
        return None
    try:
        return float(match.group("lat")), float(match.group("lon"))
    except ValueError:
        return None


def _bucket_key(lat: float, lon: float, *, deg: float) -> str:
    """Snap coords to a ``deg``-degree grid for cluster membership.

    Rounding uses ``round(x, 1)`` when ``deg == 0.1``; this matches the
    "~11 km cell" sizing described in the spec. For other ``deg`` values
    we fall back to integer-multiple rounding.
    """
    if deg == 0.1:
        lat_b = round(lat, 1)
        lon_b = round(lon, 1)
    else:
        lat_b = round(lat / deg) * deg
        lon_b = round(lon / deg) * deg
        # avoid -0.0 in keys
        lat_b = lat_b + 0.0
        lon_b = lon_b + 0.0

    # Format with proper decimal places: preserve .0 for whole numbers
    def fmt(x: float) -> str:
        s = f"{x:.1f}" if deg == 0.1 else str(x)
        return s

    return f"firms:geo:{fmt(lat_b)}:{fmt(lon_b)}"


@dataclass
class _BucketWindow:
    signals: deque = field(default_factory=deque)  # entries: (ts: datetime, event_id: str)
    ignited: bool = False


class FIRMSGeoClusterDetector:
    """Geo-cluster detector for FIRMS thermal detections."""

    id = "firms"

    def __init__(
        self,
        *,
        config: PromoterConfig,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._clock = clock
        self._buckets: dict[str, _BucketWindow] = {}
        self._suppressed_until: dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._config.firms_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        if (envelope.payload.source or "").lower() != "firms":
            return None
        coords = _parse_firms_coords(envelope.payload.url)
        if coords is None:
            return None
        cluster_key = _bucket_key(*coords, deg=self._config.firms_bucket_deg)

        # Suppression first — Task 3.5 adds the body.
        suppress_until = self._suppressed_until.get(cluster_key)
        if suppress_until is not None:
            if self._clock() < suppress_until:
                return None
            self._suppressed_until.pop(cluster_key, None)

        bucket = self._buckets.setdefault(cluster_key, _BucketWindow())
        self._prune(bucket)
        bucket.signals.append((self._clock(), envelope.event_id))

        if bucket.ignited:
            return self._build_update_hit(envelope, cluster_key, coords)

        if len(bucket.signals) >= self._config.firms_min_hits:
            bucket.ignited = True
            return self._build_ignition_hit(envelope, cluster_key, coords, bucket)

        return None

    # -- builders -------------------------------------------------------

    def _build_ignition_hit(
        self,
        envelope: SignalEnvelope,
        cluster_key: str,
        coords: tuple[float, float],
        bucket: _BucketWindow,
    ) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_ignition_timeline_event,
        )

        count = len(bucket.signals)
        title = f"FIRMS cluster ignited · {count} detections in {cluster_key}"
        ids = [eid for _ts, eid in bucket.signals]
        hit = ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="firms.cluster",
            title=title,
            severity=self._initial_severity(),
            coords=coords,
            location="",
            sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
            layer_hints_to_merge=[
                "firms",
                "events",
                "auto_promoter:v1",
                f"cluster:{cluster_key}",
            ],
            timeline_event=build_ignition_timeline_event(
                # Build event from a temporary surrogate; we need title+severity.
                ClusterHit(
                    cluster_key=cluster_key,
                    detector_id=self.id,
                    incident_kind="firms.cluster",
                    title=title,
                    severity=self._initial_severity(),
                    coords=coords,
                    location="",
                    sources_to_merge=[],
                    layer_hints_to_merge=[],
                    timeline_event=None,  # type: ignore[arg-type]
                    contributing_signal_ids=[],
                )
            ),
            contributing_signal_ids=ids,
        )
        return hit

    def _build_update_hit(
        self,
        envelope: SignalEnvelope,
        cluster_key: str,
        coords: tuple[float, float],
    ) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_update_timeline_event,
        )

        title = f"FIRMS hit · {cluster_key}"
        # t_offset is filled in by ClusterStore relative to the incident's trigger_ts;
        # detector emits 0.0 as a sentinel that the store will overwrite.
        surrogate = ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="firms.cluster",
            title=title,
            severity="high",  # never escalates downward
            coords=coords,
            location="",
            sources_to_merge=[],
            layer_hints_to_merge=[],
            timeline_event=None,  # type: ignore[arg-type]
            contributing_signal_ids=[],
        )
        return ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="firms.cluster",
            title=title,
            severity="high",
            coords=coords,
            location="",
            sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
            layer_hints_to_merge=[
                "firms",
                "events",
                "auto_promoter:v1",
                f"cluster:{cluster_key}",
            ],
            timeline_event=build_update_timeline_event(surrogate, t_offset_s=0.0),
            contributing_signal_ids=[envelope.event_id],
        )

    def _initial_severity(self) -> str:
        # FIRMS: high on open, escalates to critical at hit_count >= 10 — escalation
        # is applied in ClusterStore.apply_signal_update, not here.
        return "high"

    def _prune(self, bucket: _BucketWindow) -> None:
        cutoff = self._clock() - timedelta(seconds=self._config.firms_window_sec)
        while bucket.signals and bucket.signals[0][0] < cutoff:
            bucket.signals.popleft()

    def on_cluster_terminated(
        self,
        cluster_key: str,
        suppress_until: datetime | None = None,
    ) -> None:
        """Reset cluster state on termination; optionally suppress future signals.

        Args:
            cluster_key: The cluster key to reset.
            suppress_until: If provided, suppress signals until this time.
        """
        # Only respond to keys we own.
        if not cluster_key.startswith("firms:geo:"):
            return
        self._buckets.pop(cluster_key, None)
        if suppress_until is None:
            self._suppressed_until.pop(cluster_key, None)
        else:
            self._suppressed_until[cluster_key] = suppress_until
