"""Bounded excerpts select whole paragraphs, never cut an attributed clause."""

import re

GAP = "\n[…]\n"


def select_excerpt(text: str, question: str, budget: int = 2400) -> str:
    if len(text) <= budget:
        return text
    words = set(re.findall(r"\w{3,}", question.lower()))
    paragraphs = list(dict.fromkeys(p.strip() for p in text.split("\n\n") if p.strip()))
    ranked = sorted(
        enumerate(paragraphs), key=lambda pair: -sum(word in pair[1].lower() for word in words)
    )
    selected = []
    remaining = budget
    for index, paragraph in ranked:
        cost = len(paragraph) + (len(GAP) if selected else 0)
        if cost <= remaining:
            selected.append((index, paragraph))
            remaining -= cost
    return GAP.join(p for _, p in sorted(selected))


def complete_passages(excerpt: str) -> list[str]:
    """Expose fixed paragraph spans; model output cannot choose a substring."""
    return [p.strip() for segment in excerpt.split(GAP) for p in segment.split("\n\n") if p.strip()]
