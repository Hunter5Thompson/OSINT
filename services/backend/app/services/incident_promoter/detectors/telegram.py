"""Telegram topic-cluster detector — shingles-based v1.

The TEI embedding path is gated by ``ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED``;
when that flag is true in v1, the detector logs a warning at construction and
disables itself (no network call). The shingles path remains the production
path for v1.
"""
from __future__ import annotations

import hashlib
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse

import structlog

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import ClusterHit

logger = structlog.get_logger(__name__)


_URL_RE = re.compile(r"https?://\S+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")


def _normalize_title(raw: str) -> str:
    s = _URL_RE.sub("", (raw or "").lower())
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _shingles(normalized: str, *, n: int = 5) -> set[tuple[str, ...]]:
    tokens = normalized.split()
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard_5gram(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _domain_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host


def _channel_of(url: str | None) -> str:
    """Return channel-level key: netloc + first path component.

    This gives per-channel resolution for the domain-boost logic, so that
    signals from the same Telegram channel (e.g. ``t.me/channel``) benefit
    from the lower Jaccard threshold while signals from *different* channels
    on the same host (``t.me/u0`` vs ``t.me/u1``) are treated independently.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            return f"{host}/{parts[0]}"
        return host
    except Exception:
        return ""


@dataclass
class _Centroid:
    cluster_key: str
    tokens: set[tuple[str, ...]]          # 5-gram shingles (cross-channel matching)
    unigram_tokens: set[tuple[str, ...]]   # 1-gram tokens  (same-channel matching)
    deque: deque = field(default_factory=deque)  # entries: (ts, event_id)
    ignited: bool = False
    last_seen_ts: datetime | None = None
    domain: str = ""


class TelegramTopicDetector:
    """Telegram topic-cluster detector. Shingles-only in v1.

    Matching strategy:
    - **Same channel** (netloc + first path component matches): uses unigram
      (word-set) Jaccard with ``telegram_jaccard_threshold_domain`` (0.45).
      This tolerates word-reordered paraphrases from the same source.
    - **Different channel**: uses 5-gram shingle Jaccard with
      ``telegram_jaccard_threshold`` (0.55).  Positional n-grams are more
      precise and prevent false merges across unrelated channels.
    """

    id = "telegram"

    def __init__(
        self,
        *,
        config: PromoterConfig,
        clock: Callable[[], datetime],
        max_centroids: int = 50,
    ) -> None:
        self._config = config
        self._clock = clock
        self._max_centroids = max_centroids
        self._centroids: dict[str, _Centroid] = {}
        self._suppressed_until: dict[str, datetime] = {}
        if config.telegram_embeddings_enabled:
            logger.warning(
                "promoter_telegram_embeddings_flag_disables_detector_in_v1",
                hint="ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED=true; v1 has no embedding path.",
            )

    @property
    def enabled(self) -> bool:
        if self._config.telegram_embeddings_enabled:
            return False
        return self._config.telegram_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        if (envelope.payload.source or "").lower() != "telegram":
            return None

        normalized = _normalize_title(envelope.payload.title)
        if not normalized:
            return None
        shingles = _shingles(normalized)          # 5-gram
        unigrams = _shingles(normalized, n=1)     # word-set
        if not shingles:
            return None
        channel = _channel_of(envelope.payload.url)

        # Find best matching centroid
        best_key: str | None = None
        best_score = 0.0
        for centroid in self._centroids.values():
            same_channel = bool(channel and centroid.domain == channel)
            if same_channel:
                score = _jaccard_5gram(unigrams, centroid.unigram_tokens)
                threshold = self._config.telegram_jaccard_threshold_domain
            else:
                score = _jaccard_5gram(shingles, centroid.tokens)
                threshold = self._config.telegram_jaccard_threshold
            if score >= threshold and score > best_score:
                best_score = score
                best_key = centroid.cluster_key

        if best_key is None:
            # New centroid — key derived from 5-gram fingerprint
            cluster_key = "telegram:topic:" + hashlib.sha1(
                ("|".join(sorted(" ".join(t) for t in shingles))).encode()
            ).hexdigest()[:12]
            centroid = _Centroid(
                cluster_key=cluster_key,
                tokens=shingles,
                unigram_tokens=unigrams,
                domain=channel,
            )
            self._centroids[cluster_key] = centroid
            self._evict_if_needed()
        else:
            cluster_key = best_key
            centroid = self._centroids[cluster_key]
            # widen centroid tokens lazily (both representations)
            centroid.tokens |= shingles
            centroid.unigram_tokens |= unigrams

        # Suppression check
        suppress_until = self._suppressed_until.get(cluster_key)
        if suppress_until is not None:
            if self._clock() < suppress_until:
                return None
            self._suppressed_until.pop(cluster_key, None)

        self._prune(centroid)
        centroid.deque.append((self._clock(), envelope.event_id))
        centroid.last_seen_ts = self._clock()

        if centroid.ignited:
            return self._build_update_hit(envelope, cluster_key)
        if len(centroid.deque) >= self._config.telegram_min_hits:
            centroid.ignited = True
            return self._build_ignition_hit(envelope, cluster_key, centroid)
        return None

    def on_cluster_terminated(
        self, cluster_key: str, suppress_until: datetime | None = None
    ) -> None:
        if not cluster_key.startswith("telegram:topic:"):
            return
        self._centroids.pop(cluster_key, None)
        if suppress_until is None:
            self._suppressed_until.pop(cluster_key, None)
        else:
            self._suppressed_until[cluster_key] = suppress_until

    # -- internals ------------------------------------------------------

    def _evict_if_needed(self) -> None:
        if len(self._centroids) <= self._max_centroids:
            return
        # Evict least-recently-seen
        oldest_key = min(
            self._centroids,
            key=lambda k: self._centroids[k].last_seen_ts
            or datetime.min.replace(tzinfo=self._clock().tzinfo),
        )
        self._centroids.pop(oldest_key, None)

    def _prune(self, centroid: _Centroid) -> None:
        cutoff = self._clock() - timedelta(seconds=self._config.telegram_window_sec)
        while centroid.deque and centroid.deque[0][0] < cutoff:
            centroid.deque.popleft()

    def _build_ignition_hit(
        self, envelope: SignalEnvelope, cluster_key: str, centroid: _Centroid
    ) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_ignition_timeline_event,
        )

        count = len(centroid.deque)
        title = f"Telegram cluster · {count} matching posts"
        ids = [eid for _ts, eid in centroid.deque]
        surrogate = ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="telegram.burst",
            title=title,
            severity="elevated",
            coords=None,
            location="",
            sources_to_merge=[],
            layer_hints_to_merge=[],
            timeline_event=None,  # type: ignore[arg-type]
            contributing_signal_ids=[],
        )
        return ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="telegram.burst",
            title=title,
            severity="elevated",
            coords=None,
            location="",
            sources_to_merge=[f"Telegram · {centroid.domain or 'unknown'}"],
            layer_hints_to_merge=[
                "telegram",
                "auto_promoter:v1",
                f"cluster:{cluster_key}",
            ],
            timeline_event=build_ignition_timeline_event(surrogate),
            contributing_signal_ids=ids,
        )

    def _build_update_hit(
        self, envelope: SignalEnvelope, cluster_key: str
    ) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_update_timeline_event,
        )

        domain = _domain_of(envelope.payload.url)
        title = f"Telegram post · {cluster_key}"
        surrogate = ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="telegram.burst",
            title=title,
            severity="elevated",
            coords=None,
            location="",
            sources_to_merge=[],
            layer_hints_to_merge=[],
            timeline_event=None,  # type: ignore[arg-type]
            contributing_signal_ids=[],
        )
        return ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="telegram.burst",
            title=title,
            severity="elevated",
            coords=None,
            location="",
            sources_to_merge=[f"Telegram · {domain or 'unknown'}"],
            layer_hints_to_merge=[
                "telegram",
                "auto_promoter:v1",
                f"cluster:{cluster_key}",
            ],
            timeline_event=build_update_timeline_event(surrogate, t_offset_s=0.0),
            contributing_signal_ids=[envelope.event_id],
        )
