"""GDELT tone-spike detector — SKELETON, default-off in v1.

FIELD SCHEMA AUDIT RESULT (2026-05-20):
  The live GDELT collector (services/data-ingestion/feeds/gdelt_collector.py)
  produces ARTICLE-CENTRIC payloads, not EVENT-CENTRIC with actor/tone fields.
  Live fields: title, url, domain, language, source_country, seen_date,
  codebook_type, entities.

  The detector spec assumes GDELT events with:
    - actor1_geo_lat, actor1_geo_lon
    - tone (negativity score)
    - mention_count

  These fields are NOT present in the live payload. When this detector is
  enabled (ODIN_PROMOTER_GDELT_ENABLED=true), all signal lookups will return
  None, and the detector will silently drop every signal with no matches.

  Before real detection can be implemented, the GDELT source must be updated
  to emit the required fields, or the detector spec must be revised to work
  with the actual article schema.

  See §12 (Phase 7) and §10 (Risks) in the design spec.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import ClusterHit


class GDELTToneSpikeDetector:
    """GDELT tone-spike detector — skeleton, no real logic yet.

    Monitors GDELT signals for negative tone spikes co-located in space and time.
    Currently disabled by default; when enabled, returns None for all inputs
    pending schema verification.
    """

    id = "gdelt"

    def __init__(
        self, *, config: PromoterConfig, clock: Callable[[], datetime]
    ) -> None:
        self._config = config
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return self._config.gdelt_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        """Process a signal envelope.

        Args:
            envelope: Signal to evaluate.

        Returns:
            ClusterHit if the signal triggers a cluster (accumulation threshold
            met), None otherwise or if detector is disabled.

        Note:
            Current implementation returns None unconditionally. Real detection
            would require:
              1. Extract (actor1_geo_lat, actor1_geo_lon) from envelope.payload.extras
              2. Extract tone (negative score) and mention_count
              3. Build cluster_key as gdelt:geo:<round(lat,0.5)>:<round(lon,0.5)>
              4. Accumulate in time window (gdelt_window_sec)
              5. Ignite at min_hits threshold (gdelt_min_hits)
        """
        if not self.enabled:
            return None
        # Skeleton: real logic deferred until payload schema verified.
        return None

    def on_cluster_terminated(
        self, cluster_key: str, suppress_until: datetime | None = None
    ) -> None:
        """Called when a GDELT cluster is terminated.

        Args:
            cluster_key: Cluster identifier (gdelt:geo:...)
            suppress_until: Optional datetime; if set, suppress signals until then.

        Note:
            No state to reset until real detection is implemented.
        """
        # Skeleton: no state to manage yet.
        return
