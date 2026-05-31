"""Read-side credibility policy: source_type baseline + provider override."""
from __future__ import annotations

import pytest

from rag.credibility import credibility_score, normalize_provider


def test_baseline_per_source_type():
    assert credibility_score("rss", "some-unknown-blog.example") == 0.60
    assert credibility_score("telegram", "telegram:randomchannel") == 0.40
    assert credibility_score("gdelt", "aggregator.example") == 0.50
    assert credibility_score("dataset", "usgs.gov") == 0.80
    assert credibility_score("notebooklm", "notebooklm:nb-1") == 0.60
    assert credibility_score("unknown", "whatever") == 0.30


def test_provider_override_beats_baseline():
    assert credibility_score("rss", "reuters.com") == 0.85
    assert credibility_score("rss", "bbc.com") == 0.80


def test_normalize_provider_is_case_and_scheme_insensitive():
    assert normalize_provider("Reuters.com") == "reuters.com"
    assert normalize_provider("https://reuters.com/world") == "reuters.com"
    assert normalize_provider("  bbc.com/news  ") == "bbc.com"
    assert normalize_provider("telegram:Rybar") == "telegram:rybar"


def test_normalize_provider_handles_ports_and_schemes():
    assert normalize_provider("http://bbc.com/sport") == "bbc.com"
    assert normalize_provider("https://reuters.com:443/news") == "reuters.com"
    assert normalize_provider("ftp://reuters.com/feed") == "reuters.com"


def test_credibility_unknown_fallback_score():
    from rag.credibility import credibility_score
    assert credibility_score("unknown", "anything") == 0.30


def test_unknown_source_type_raises():
    with pytest.raises(KeyError):
        credibility_score("not-a-type", "x")
