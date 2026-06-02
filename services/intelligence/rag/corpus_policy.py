"""Read-corpus policy — the single auditable place for *which sources are
readable* and *how reputation nudges relevance*. Consumed only by the
qdrant_search tool; the generic retriever stays neutral.

Two lanes:
  analysis  — rss OR NotebookLM (notebook_id present; legacy raw source="unknown")
  realtime  — vetted Telegram leads (NOT verified primary sources)
"""
from __future__ import annotations

import structlog

from config import settings

log = structlog.get_logger(__name__)

# Analysis lane: prose analysis.
ANALYSIS_SOURCES: frozenset[str] = frozenset({"rss"})

# Realtime lane: vetted Telegram leads. rybar (state-aligned) deliberately excluded.
TELEGRAM_ALLOWLIST: frozenset[str] = frozenset({
    "wartranslated", "OSINTdefender", "liveuamap", "AuroraIntel", "DeepStateEN",
})

# Tunable start values — sourced from settings (env-overridable). NOT permanent truth.
TIER_BOOST_LAMBDA: float = settings.rag_tier_boost_lambda
ANALYSIS_POOL: int = settings.rag_analysis_pool
REALTIME_POOL: int = settings.rag_realtime_pool
RT_SCORE_THRESHOLD: float = settings.rag_realtime_score_threshold
FINAL_K: int = settings.rag_final_k
TELEGRAM_MAX: int = settings.rag_telegram_max


def analysis_filter() -> dict:
    """Qdrant filter: source ∈ ANALYSIS_SOURCES OR notebook_id present (NLM).
    min_should=1 (Qdrant default)."""
    return {"should": [
        {"key": "source", "match": {"any": sorted(ANALYSIS_SOURCES)}},
        {"must_not": [{"is_empty": {"key": "notebook_id"}}]},
    ]}


def realtime_filter() -> dict:
    """Qdrant filter: vetted Telegram channels."""
    return {"must": [
        {"key": "source", "match": {"value": "telegram"}},
        {"key": "telegram_channel", "match": {"any": sorted(TELEGRAM_ALLOWLIST)}},
    ]}
