"""Read-side credibility policy.

Quellenverlässlichkeit (NICHT Aussagewahrheit). Zentrale, prüfbare Stelle.
source_type-Baseline + kurze, begründete Provider-Overrides.
"""
from __future__ import annotations

from urllib.parse import urlparse

# Baseline reliability per source_type. notebooklm/gdelt are NOT primary sources.
TYPE_BASELINES: dict[str, float] = {
    "rss": 0.60,
    "telegram": 0.40,
    "gdelt": 0.50,        # aggregator/discovery path, not a publisher
    "dataset": 0.80,
    "notebooklm": 0.60,   # transformation path, conservative
    "unknown": 0.30,      # read-only legacy fallback
}

# Keep short. Every entry needs a one-line justification and a test.
PROVIDER_OVERRIDES: dict[str, float] = {
    "reuters.com": 0.85,  # international wire, strong editorial standards
    "bbc.com": 0.80,      # public broadcaster, strong editorial standards
}


def normalize_provider(provider: str) -> str:
    """Canonicalize a provider id for registry lookup.

    Lowercase; strip scheme/port/path; keep `telegram:<handle>` /
    `notebooklm:<id>` namespaced ids intact (only lowercased).
    """
    p = (provider or "").strip().lower()
    if ":" in p and "://" not in p:
        # namespaced id like telegram:rybar — keep as-is
        return p
    if "://" in p:
        p = urlparse(p).hostname or p
    # drop any path that slipped through (e.g. "bbc.com/news")
    return p.split("/", 1)[0]


def credibility_score(source_type: str, provider: str) -> float:
    """Provider override if present, else the source_type baseline.

    Raises KeyError if source_type is not a known baseline (fail-fast).
    """
    key = normalize_provider(provider)
    if key in PROVIDER_OVERRIDES:
        return PROVIDER_OVERRIDES[key]
    return TYPE_BASELINES[source_type]
