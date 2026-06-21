"""Layered filter: free heuristic gate, then a single-judge quality pass + dedup.

The heuristic gates STRUCTURE only — Munin's output discipline is (unverifiziert) markers,
NOT [n] bracket citations, so it does NOT require citations. Faithfulness/citation quality
is judged by the single Opus-subagent `judge` pass."""
from __future__ import annotations

import re
from collections.abc import Callable

_THREAT = re.compile(r"\b(CRITICAL|HIGH|ELEVATED|MODERATE)\b")
_CONF = re.compile(r"(high|moderate|low) confidence", re.IGNORECASE)
_SECTIONS = (
    "Executive Summary", "Key Findings", "Threat Assessment",
    "Confidence Level", "Recommended Actions",
)


def heuristic_ok(report: str) -> bool:
    if not (300 <= len(report) <= 6000):
        return False
    if not all(s in report for s in _SECTIONS):
        return False
    return bool(_THREAT.search(report) and _CONF.search(report))


def filter_examples(rows: list[dict], judge: Callable[[str], dict], keep: int) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    seen: set[str] = set()
    for r in rows:
        rep = r["assistant"]
        if not heuristic_ok(rep):
            continue
        sig = rep[:200]  # cheap near-dup guard
        if sig in seen:
            continue
        seen.add(sig)
        s = judge(rep)
        mean = sum(s.values()) / len(s)
        scored.append((mean, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in scored[:keep]]
