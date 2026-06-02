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


# Canonical source_types consistent with each lane (when the contract field
# is present on a payload).
_ANALYSIS_TYPES: frozenset[str] = frozenset({"rss", "notebooklm"})


def validate_lane(results: list[dict], lane: str) -> list[dict]:
    """Second barrier (AC-2): keep only results that satisfy the lane invariant.
    Qdrant filter is the first barrier; index lag / a filter bug must not break
    AC-2. A payload whose canonical `source_type` contradicts the lane (e.g.
    source="rss" but source_type="gdelt") is rejected too. Dropped are logged."""
    kept, dropped = [], []
    for r in results:
        st = r.get("source_type")  # canonical contract field, if present
        if lane == "analysis":
            identity = r.get("source") in ANALYSIS_SOURCES or bool(r.get("notebook_id"))
            type_ok = st is None or st in _ANALYSIS_TYPES
            ok = identity and type_ok
        elif lane == "realtime":
            identity = (r.get("source") == "telegram"
                        and r.get("telegram_channel") in TELEGRAM_ALLOWLIST)
            type_ok = st is None or st == "telegram"
            ok = identity and type_ok
        else:
            ok = False
        (kept if ok else dropped).append(r)
    if dropped:
        log.warning("corpus_guard_dropped", lane=lane, count=len(dropped),
                    sources=[d.get("source") for d in dropped])
    return kept


def merge_lanes(analysis: list[dict], realtime: list[dict],
                *, final_k: int = FINAL_K, telegram_max: int = TELEGRAM_MAX) -> list[dict]:
    """Analysis dominates the top; at most `telegram_max` realtime leads, last,
    each marked source_class="realtime". Realtime displaces at most
    `telegram_max` analysis slots."""
    rt = [{**r, "source_class": "realtime"} for r in realtime[:min(telegram_max, final_k)]]
    if rt:
        return list(analysis[:final_k - len(rt)]) + rt
    return list(analysis[:final_k])
