"""Read-only before/after measurement for the corpus-scoping slice.

Runs six fixed queries against live Qdrant and prints the top-5 source mix
BEFORE (the prior product path: enhanced_search, no scoping) vs AFTER (two-lane
scoped + tier-boost), with source, provider and raw/norm/final scores. Paste the
table into the PR to evidence AC-1/AC-2. Not a CI gate (live-data dependent).

Usage:  uv run python -m scripts.measure_corpus_scoping
"""
from __future__ import annotations

import asyncio

QUERIES = [
    "Bundeswehr Beschaffung",
    "Russia shadow fleet",
    "Taiwan strait tensions",
    "NATO eastern flank posture",
    "Iran proxy escalation",
    "Sahel coup instability",
]


def _label(hit: dict) -> str:
    src = hit.get("source", "?")
    name = hit.get("feed_name") or hit.get("telegram_channel") or hit.get("source_name")
    return f"{src}:{name}" if name else src


def _scores(hit: dict) -> str:
    raw = hit.get("tier_raw", hit.get("rerank_score", hit.get("score")))
    norm = hit.get("tier_norm")
    final = hit.get("tier_score")
    parts = []
    if raw is not None:
        parts.append(f"raw={raw:.3f}")
    if norm is not None:
        parts.append(f"norm={norm:.3f}")
    if final is not None:
        parts.append(f"final={final:.3f}")
    return f"({','.join(parts)})" if parts else ""


def format_hits(hits: list[dict]) -> str:
    """One line: `source:provider(raw=…,norm=…,final=…)` per hit."""
    return " | ".join(f"{_label(h)}{_scores(h)}" for h in hits)


async def _run() -> None:
    from rag.corpus_policy import (
        ANALYSIS_POOL,
        FINAL_K,
        REALTIME_POOL,
        RT_SCORE_THRESHOLD,
        TELEGRAM_MAX,
        analysis_filter,
        apply_tier_boost,
        merge_lanes,
        realtime_filter,
        validate_lane,
    )
    from rag.retriever import enhanced_search

    for q in QUERIES:
        # BEFORE = the prior product path (dense + rerank, NO scoping/tier-boost).
        before = await enhanced_search(q, limit=FINAL_K, enable_graph_context=False)
        analysis = await enhanced_search(
            q,
            limit=FINAL_K,
            pool=ANALYSIS_POOL,
            query_filter=analysis_filter(),
            post_rerank=apply_tier_boost,
            enable_graph_context=False,
        )
        realtime = await enhanced_search(
            q,
            limit=TELEGRAM_MAX,
            pool=REALTIME_POOL,
            query_filter=realtime_filter(),
            post_rerank=apply_tier_boost,
            score_threshold=RT_SCORE_THRESHOLD,
            enable_graph_context=False,
        )
        after = merge_lanes(
            validate_lane(analysis, "analysis"),
            validate_lane(realtime, "realtime"),
        )
        print(f"\n### {q}")
        print(f"BEFORE: {format_hits(before)}")
        print(f"AFTER : {format_hits(after)}")


if __name__ == "__main__":
    asyncio.run(_run())
