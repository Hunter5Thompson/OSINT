"""Deterministic severity + category normalization.

The real corpus mixes vocabularies (hotspots low/moderate/elevated/high/critical;
incidents low/elevated/high/critical; RSS low/medium/high/critical; GDACS numeric;
GDELT *none*). Everything severity-touching MUST go through normalize_severity so
colours/rankings are deterministic and null/unknown never produces a random value.
"""

from __future__ import annotations

# Canonical ordered scale (index = rank; unknown lowest, critical highest).
CANONICAL_ORDER: list[str] = ["unknown", "low", "medium", "high", "critical"]
_RANK = {s: i for i, s in enumerate(CANONICAL_ORDER)}

# Every known raw value (lower-cased) -> canonical level.
_SEVERITY_MAP: dict[str, str] = {
    "low": "low",
    "warning": "low",
    "moderate": "medium",
    "medium": "medium",
    "elevated": "high",
    "high": "high",
    "critical": "critical",
    "severe": "critical",
    "extreme": "critical",
}

# Fixed category priority for dominant-category tie-breaks (most -> least salient).
_CATEGORY_PRIORITY: list[str] = [
    "military", "conflict", "posture", "cyber", "political", "economic",
    "humanitarian", "social", "civil", "infrastructure", "space",
    "environmental", "other",
]
_CAT_PRIO = {c: i for i, c in enumerate(_CATEGORY_PRIORITY)}


def normalize_severity(raw: object) -> str:
    """Map any raw severity to the canonical scale; null/unknown/garbage -> 'unknown'."""
    if not isinstance(raw, str):
        return "unknown"
    return _SEVERITY_MAP.get(raw.strip().lower(), "unknown")


def severity_rank(raw: object) -> int:
    """Rank of a (raw or canonical) severity; higher = more severe."""
    value = raw if isinstance(raw, str) and raw in _RANK else normalize_severity(raw)
    return _RANK[value]


def category_of(codebook_type: object) -> str:
    """First segment of a codebook_type (e.g. 'military.airstrike' -> 'military')."""
    if not isinstance(codebook_type, str) or not codebook_type.strip():
        return "other"
    return codebook_type.split(".")[0].strip().lower() or "other"


def dominant_category(categories: list[object]) -> str:
    """Modal category; exact ties broken by fixed priority then alphabetical.

    Blank/None entries are ignored; an empty/all-blank input -> 'other'.
    """
    counts: dict[str, int] = {}
    for raw in categories:
        cat = category_of(raw)
        if cat:
            counts[cat] = counts.get(cat, 0) + 1
    if not counts:
        return "other"
    # sort by (count desc, priority asc, name asc) -> deterministic
    return sorted(
        counts.items(),
        key=lambda kv: (-kv[1], _CAT_PRIO.get(kv[0], len(_CATEGORY_PRIORITY)), kv[0]),
    )[0][0]
