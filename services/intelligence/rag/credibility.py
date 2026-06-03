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
# Keys must match the canonical `provider` the WRITE side actually stamps
# (e.g. the BBC RSS feed resolves to bbc.co.uk, not bbc.com).
PROVIDER_OVERRIDES: dict[str, float] = {
    # Domain keys (GDELT-discovery path surfaces bare domains)
    "reuters.com": 0.85,  # international wire, strong editorial standards
    "bbc.com": 0.80,      # public broadcaster (international domain)
    "bbc.co.uk": 0.80,    # public broadcaster (UK domain — the RSS feed's provider)
    # RSS feed_name keys (provider == normalize_provider(feed_name.lower())).
    # Registry models reliability, not document genre — wire services included.
    "reuters (google)": 0.85,  # wire via Google News feed — same source, different discovery path
    "ap news (google)": 0.85,  # international wire via Google News feed
    "bbc world": 0.80,
    "bellingcat": 0.85,                       # OSINT verification, methodical
    "rand corporation": 0.82,
    "csis": 0.82,
    "rusi commentary": 0.82,
    "rusi publications": 0.82,
    "sipri": 0.82,
    "swp publications (de)": 0.82,
    "swp publications (en)": 0.82,
    "atlantic council": 0.82,
    "brookings": 0.82,
    "crisis group": 0.82,
    "war on the rocks": 0.82,
    "arms control association": 0.82,
    "eu parliament security and defence": 0.80,
    "euvsdisinfo": 0.80,
    # Think-tank canonical DOMAIN overrides (rss_fulltext writes provider=domain).
    # Distinct from the feed_name LABEL keys above (legacy teasers lack canonical provider).
    "csis.org": 0.82,
    "rusi.org": 0.82,
    "rand.org": 0.82,
    "sipri.org": 0.82,
    "swp-berlin.org": 0.82,
    "atlanticcouncil.org": 0.82,
    "brookings.edu": 0.82,
    "crisisgroup.org": 0.82,
    "warontherocks.com": 0.82,
    "bellingcat.com": 0.85,
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
    p = p.split("/", 1)[0]
    # strip a leading www. so www.reuters.com matches the reuters.com override
    # (the GDELT discovery path can surface www-prefixed domains)
    return p.removeprefix("www.")


def credibility_score(source_type: str, provider: str) -> float:
    """Provider override if present, else the source_type baseline.

    A provider override intentionally beats the source_type baseline — a
    reuters.com article surfaced via the GDELT discovery path is still Reuters,
    so it earns Reuters' reliability rather than the gdelt aggregator baseline.

    Raises KeyError if source_type is not a known baseline (fail-fast).
    """
    key = normalize_provider(provider)
    if key in PROVIDER_OVERRIDES:
        return PROVIDER_OVERRIDES[key]
    return TYPE_BASELINES[source_type]
