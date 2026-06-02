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


def credibility_of(payload: dict) -> float:
    """Reliability for a raw retriever-result payload. Reuses the read-side
    provenance derivation so NLM(notebook_id)->notebooklm(0.60), rss->feed_name
    override or 0.60, telegram->0.40, etc."""
    from rag.evidence import to_evidence_item  # local import avoids cycle
    return to_evidence_item(payload).source.credibility_score


def apply_tier_boost(results: list[dict], *, lam: float = TIER_BOOST_LAMBDA) -> list[dict]:
    """final = (1-lam)*rerank_norm + lam*credibility, stable-sorted desc.

    rerank_norm is the min-max normalized rerank_score (dense `score` if no
    rerank_score). When max==min (ties / pool size 1) rerank_norm=1.0 for all,
    so reputation decides. Suitable as enhanced_search's post_rerank callback.
    """
    if not results:
        return results
    raws = [float(r.get("rerank_score", r.get("score", 0.0))) for r in results]
    lo, hi = min(raws), max(raws)
    span = hi - lo
    out: list[dict] = []
    for r, raw in zip(results, raws, strict=True):
        r_norm = 1.0 if span == 0 else (raw - lo) / span
        cred = credibility_of(r)
        final = (1.0 - lam) * r_norm + lam * cred
        out.append({**r, "tier_raw": raw, "tier_norm": r_norm,
                    "tier_cred": cred, "tier_score": final})
    out.sort(key=lambda x: x["tier_score"], reverse=True)
    log.info(
        "tier_boost_applied",
        lam=lam,
        ranked=[{"provider": x.get("feed_name") or x.get("source"),
                 "source": x.get("source"), "raw": round(x["tier_raw"], 4),
                 "norm": round(x["tier_norm"], 4), "cred": x["tier_cred"],
                 "final": round(x["tier_score"], 4)} for x in out],
    )
    return out
