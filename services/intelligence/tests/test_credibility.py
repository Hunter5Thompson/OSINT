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


def test_bbc_co_uk_matches_override_like_the_feed_writes_it():
    # The BBC RSS feed's canonical provider is bbc.co.uk, not bbc.com.
    assert credibility_score("rss", "bbc.co.uk") == 0.80


def test_provider_override_beats_gdelt_aggregator_baseline():
    # Reuters surfaced via GDELT discovery is still Reuters.
    assert credibility_score("gdelt", "reuters.com") == 0.85
    assert credibility_score("gdelt", "www.reuters.com") == 0.85  # www stripped


def test_normalize_provider_is_case_and_scheme_insensitive():
    assert normalize_provider("Reuters.com") == "reuters.com"
    assert normalize_provider("https://reuters.com/world") == "reuters.com"
    assert normalize_provider("  bbc.com/news  ") == "bbc.com"
    assert normalize_provider("telegram:Rybar") == "telegram:rybar"


def test_normalize_provider_handles_ports_and_schemes():
    assert normalize_provider("http://bbc.com/sport") == "bbc.com"
    assert normalize_provider("https://reuters.com:443/news") == "reuters.com"
    assert normalize_provider("ftp://reuters.com/feed") == "reuters.com"


def test_normalize_provider_strips_www():
    assert normalize_provider("www.reuters.com") == "reuters.com"
    assert normalize_provider("https://www.bbc.co.uk/news") == "bbc.co.uk"


def test_credibility_unknown_fallback_score():
    from rag.credibility import credibility_score
    assert credibility_score("unknown", "anything") == 0.30


def test_unknown_source_type_raises():
    with pytest.raises(KeyError):
        credibility_score("not-a-type", "x")


class TestProviderOverrides:
    @pytest.mark.parametrize("feed_name,expected", [
        ("csis", 0.82),
        ("rand corporation", 0.82),
        ("rusi commentary", 0.82),
        ("rusi publications", 0.82),
        ("sipri", 0.82),
        ("atlantic council", 0.82),
        ("war on the rocks", 0.82),
        ("brookings", 0.82),
        ("crisis group", 0.82),
        ("arms control association", 0.82),
        ("swp publications (de)", 0.82),
        ("swp publications (en)", 0.82),
        ("bellingcat", 0.85),
        ("reuters (google)", 0.85),
        ("ap news (google)", 0.85),
        ("bbc world", 0.80),
        ("eu parliament security and defence", 0.80),
        ("euvsdisinfo", 0.80),
    ])
    def test_analysis_feed_override(self, feed_name, expected):
        # rss provider is the lowercased feed_name
        assert credibility_score("rss", feed_name) == expected

    def test_local_rss_keeps_baseline(self):
        assert credibility_score("rss", "some local paper") == 0.60

    def test_fail_fast_is_on_source_type_not_provider(self):
        with pytest.raises(KeyError):
            credibility_score("not_a_type", "whatever")


class TestThinkTankDomainOverrides:
    @pytest.mark.parametrize("domain,expected", [
        ("csis.org", 0.82), ("rusi.org", 0.82), ("rand.org", 0.82), ("sipri.org", 0.82),
        ("swp-berlin.org", 0.82), ("atlanticcouncil.org", 0.82), ("brookings.edu", 0.82),
        ("crisisgroup.org", 0.82), ("warontherocks.com", 0.82), ("bellingcat.com", 0.85),
    ])
    def test_canonical_domain_override(self, domain, expected):
        # rss_fulltext writes provider=domain (canonical); the boost must fire
        assert credibility_score("rss", domain) == expected


class TestSuvReportOverride:
    """SUV.report — paid German defense analysis (think-tank-grade), licensing
    cleared for ODIN use. Both the teaser (rss provider=suv.report) and the
    enriched rss_fulltext (provider=domain) resolve to the single domain key."""

    def test_suv_report_domain_override(self):
        # 0.78: below the SWP/RAND cluster (0.82), well above the rss baseline (0.60).
        assert credibility_score("rss", "suv.report") == 0.78

    def test_suv_report_override_survives_gdelt_discovery_path(self):
        # If ever surfaced via GDELT discovery, it's still SUV → keeps the override.
        assert credibility_score("gdelt", "suv.report") == 0.78
