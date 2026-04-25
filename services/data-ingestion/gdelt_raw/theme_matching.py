"""Prefix-aware theme matcher for GDELT V2Themes.

Patterns:
  "NUCLEAR"        — exact match only
  "CRISISLEX_*"    — prefix match (starts with "CRISISLEX_")

Why not regex: faster, safer, no accidental backtracking, explicit semantics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeMatcher:
    exacts: frozenset[str]
    prefixes: tuple[str, ...]


def compile_patterns(patterns: list[str]) -> ThemeMatcher:
    exacts: set[str] = set()
    prefixes: list[str] = []
    for p in patterns:
        if p.endswith("*"):
            prefixes.append(p[:-1])  # strip trailing "*"
        else:
            exacts.add(p)
    return ThemeMatcher(exacts=frozenset(exacts), prefixes=tuple(prefixes))


def matches_any(theme: str, matcher: ThemeMatcher) -> bool:
    if theme in matcher.exacts:
        return True
    return any(theme.startswith(p) for p in matcher.prefixes)


def any_match_in_themes(themes: list[str], matcher: ThemeMatcher) -> bool:
    return any(matches_any(t, matcher) for t in themes)
