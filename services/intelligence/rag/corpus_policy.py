"""Read-corpus policy — the single auditable place for *which sources are
readable* and *how reputation nudges relevance*. Consumed only by the
qdrant_search tool; the generic retriever stays neutral.

Two lanes:
  analysis  — rss OR NotebookLM (notebook_id present; legacy raw source="unknown")
  realtime  — vetted Telegram leads (NOT verified primary sources)
"""
from __future__ import annotations

import math
from collections import Counter

import structlog
from qdrant_client import models

from config import settings
from rag.content_quality import content_junk_reason

log = structlog.get_logger(__name__)

# Analysis lane: prose analysis.
ANALYSIS_SOURCES: frozenset[str] = frozenset({"rss", "rss_fulltext", "suv_structured"})

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


def analysis_filter() -> models.Filter:
    """Qdrant filter: source ∈ ANALYSIS_SOURCES OR notebook_id present (NLM);
    never a superseded teaser. min_should=1 (Qdrant default)."""
    return models.Filter(
        should=[
            models.FieldCondition(
                key="source",
                match=models.MatchAny(any=sorted(ANALYSIS_SOURCES)),
            ),
            models.Filter(
                must_not=[
                    models.IsEmptyCondition(
                        is_empty=models.PayloadField(key="notebook_id")
                    )
                ]
            ),
        ],
        must_not=[
            models.FieldCondition(
                key="superseded_by_fulltext",
                match=models.MatchValue(value=True),
            )
        ],
    )


def realtime_filter() -> models.Filter:
    """Qdrant filter: vetted Telegram channels."""
    return models.Filter(
        must=[
            models.FieldCondition(
                key="source",
                match=models.MatchValue(value="telegram"),
            ),
            models.FieldCondition(
                key="telegram_channel",
                match=models.MatchAny(any=sorted(TELEGRAM_ALLOWLIST)),
            ),
        ]
    )


def credibility_of(payload: dict) -> float:
    """Reliability for a raw retriever-result payload. Reuses the read-side
    provenance derivation so NLM(notebook_id)->notebooklm(0.60), rss->feed_name
    override or 0.60, telegram->0.40, etc."""
    from rag.evidence import to_evidence_item  # local import avoids cycle
    return to_evidence_item(payload).source.credibility_score


def _invalid_hit_reason(result: object) -> str | None:
    if not isinstance(result, dict):
        return "invalid-root"
    if "content" in result and not isinstance(result["content"], str):
        return "invalid-content-type"
    for key in ("score", "rerank_score", "tier_score"):
        if key not in result:
            continue
        value = result[key]
        try:
            if type(value) not in (int, float) or not math.isfinite(value):
                return "invalid-score"
        except OverflowError:
            return "invalid-score"
    source = result.get("source")
    if source is not None and not isinstance(source, str):
        return "invalid-source-type"
    return None


def apply_tier_boost(results: list[dict], *, lam: float = TIER_BOOST_LAMBDA) -> list[dict]:
    """Normalize valid scores, blend credibility, then exclude invalid final scores."""
    valid: list[tuple[dict, float, float]] = []
    reasons: Counter[str] = Counter()
    for result in results:
        reason = _invalid_hit_reason(result)
        if reason is not None:
            reasons[reason] += 1
            continue
        raw = result.get("rerank_score", result.get("score"))
        if raw is None:
            reasons["missing-score"] += 1
            continue
        try:
            credibility = credibility_of(result)
        except (ValueError, TypeError, OverflowError):
            reasons["invalid-evidence"] += 1
            continue
        valid.append((result, float(raw), credibility))
    out: list[dict] = []
    if valid:
        raws = [raw for _result, raw, _credibility in valid]
        lo, hi = min(raws), max(raws)
        span = hi - lo
        for result, raw, credibility in valid:
            normalized = 1.0 if span == 0 else (raw - lo) / span
            final = (1.0 - lam) * normalized + lam * credibility
            if not math.isfinite(final):
                reasons["invalid-final-score"] += 1
                continue
            out.append({**result, "tier_raw": raw, "tier_norm": normalized,
                        "tier_cred": credibility, "tier_score": final})
    out.sort(key=lambda result: result["tier_score"], reverse=True)
    if reasons:
        log.warning("retrieval_hits_rejected", count=sum(reasons.values()), reasons=dict(reasons))
    log.info("tier_boost_applied", lam=lam, result_count=len(out))
    return out


# Canonical source -> expected source_type for the analysis lane (PAIR validation).
# Independent identity/type checks would let {source:"rss", source_type:"dataset"} leak,
# and many dataset collectors (firms/usgs/…) stamp source_type="dataset".
# NLM points carry no analysis `source`; identified by notebook_id, expected "notebooklm".
_ANALYSIS_SOURCE_TYPE: dict[str, str] = {
    "rss": "rss",
    "rss_fulltext": "rss",
    "suv_structured": "dataset",
}
if set(_ANALYSIS_SOURCE_TYPE) != ANALYSIS_SOURCES:  # keep in lock-step; assert stripped under -O
    raise RuntimeError(
        f"_ANALYSIS_SOURCE_TYPE keys {set(_ANALYSIS_SOURCE_TYPE)} "
        f"!= ANALYSIS_SOURCES {set(ANALYSIS_SOURCES)}; update both together"
    )


def validate_lane(results: list[dict], lane: str) -> list[dict]:
    """Second barrier (AC-2): keep only results that satisfy the lane invariant.
    Qdrant filter is the first barrier; index lag / a filter bug must not break
    AC-2. A payload whose canonical `source_type` contradicts the lane (e.g.
    source="rss" but source_type="gdelt") is rejected too. Dropped are logged."""
    kept, dropped, content_dropped = [], [], []
    for r in results:
        reason = _invalid_hit_reason(r)
        if reason is not None:
            content_dropped.append((reason, r))
            continue
        if r.get("superseded_by_fulltext") is True:
            # normal supersede (fulltext chunks already replace it); logged separately
            # so corpus_guard_dropped stays a true anomaly signal (filter bug / leakage)
            log.debug("corpus_supersede_skipped", lane=lane,
                      source=r.get("source"), feed_name=r.get("feed_name"))
            continue
        st = r.get("source_type")  # canonical contract field, if present
        if lane == "analysis":
            src = r.get("source")
            if src in ANALYSIS_SOURCES:
                expected = _ANALYSIS_SOURCE_TYPE[src]
                ok = st is None or st == expected
            elif r.get("notebook_id"):
                ok = st is None or st == "notebooklm"
            else:
                ok = False
            # Content-quality gate (AC: no empty / base64-image / keyword-soup chunks reach
            # synthesis). The corpus survey found ~14k empty rss headlines + base64-image
            # blobs in this lane; the Qdrant filter can't express "usable prose", so drop
            # them here. Logged separately as a quality signal, not a leakage anomaly.
            if ok:
                # Evaluate the SAME text the model will see: mirror rag.evidence._excerpt's
                # fallback. Bare `rss` points store prose under `summary` (no `content`
                # key), so checking only `content` would wrongly drop ~24 wire/gov feeds.
                text = (r.get("content") or r.get("summary")
                        or r.get("description") or r.get("title") or "")
                reason = (
                    content_junk_reason(text) if isinstance(text, str) else "invalid-content-type"
                )
                if reason is not None:
                    content_dropped.append((reason, r))
                    continue
        elif lane == "realtime":
            identity = (r.get("source") == "telegram"
                        and isinstance(r.get("telegram_channel"), str)
                        and r.get("telegram_channel") in TELEGRAM_ALLOWLIST)
            type_ok = st is None or st == "telegram"
            ok = identity and type_ok
        else:
            ok = False
        (kept if ok else dropped).append(r)
    if dropped:
        log.warning("corpus_guard_dropped", lane=lane, count=len(dropped),
                    sources=[d.get("source") for d in dropped])
    if content_dropped:
        log.warning("corpus_content_dropped", lane=lane, count=len(content_dropped),
                    reasons=dict(Counter(reason for reason, _ in content_dropped)))
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
