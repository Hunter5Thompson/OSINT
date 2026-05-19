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
        # Phase 3.2: pure accumulation, no emit yet — emit logic in Task 3.3.
        bucket = self._buckets.setdefault(cluster_key, _BucketWindow())
        self._prune(bucket)
        bucket.signals.append((self._clock(), envelope.event_id))
        return None

    def _prune(self, bucket: _BucketWindow) -> None:
        cutoff = self._clock() - timedelta(seconds=self._config.firms_window_sec)
        while bucket.signals and bucket.signals[0][0] < cutoff:
            bucket.signals.popleft()

    def on_cluster_terminated(
        self,
        cluster_key: str,
        suppress_until: datetime | None = None,
    ) -> None:
        """Handle cluster termination (Task 3.5)."""
        # Remove from active buckets.
        self._buckets.pop(cluster_key, None)
        # Record suppression if provided (Task 3.5).
        if suppress_until is not None:
            self._suppressed_until[cluster_key] = suppress_until
