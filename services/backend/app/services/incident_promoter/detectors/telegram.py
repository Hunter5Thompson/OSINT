"""Telegram topic-cluster detector — shingles-based v1.

The TEI embedding path is gated by ``ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED``;
when that flag is true in v1, the detector logs a warning at construction and
disables itself (no network call). The shingles path remains the production
path for v1.
"""
from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import ClusterHit


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
