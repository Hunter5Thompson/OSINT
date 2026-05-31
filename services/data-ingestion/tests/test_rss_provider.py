"""Task 16: RSS per-feed explicit provider + published_at=None semantics."""
from __future__ import annotations

from feeds.rss_collector import RSS_FEEDS


def test_every_feed_has_explicit_non_google_provider():
    for feed in RSS_FEEDS:
        prov = feed.get("provider")
        assert prov, f"feed {feed['name']!r} is missing an explicit provider id"
        assert prov != "news.google.com", f"{feed['name']!r} leaks the google proxy host"
        assert "://" not in prov and "/" not in prov, f"{feed['name']!r} provider must be a bare domain"


def test_known_feeds_have_expected_publisher_domains():
    by_name = {f["name"]: f for f in RSS_FEEDS}
    if "BBC World" in by_name:
        assert by_name["BBC World"]["provider"] == "bbc.co.uk"
    if "Reuters (Google)" in by_name:
        assert by_name["Reuters (Google)"]["provider"] == "reuters.com"


# ---------------------------------------------------------------------------
# Steps 5–7: pure payload builder tests
# ---------------------------------------------------------------------------

from feeds.rss_collector import build_rss_payload  # noqa: E402


def test_build_rss_payload_stamps_explicit_provenance():
    feed = {"name": "BBC World", "url": "https://feeds.bbci.co.uk/x", "provider": "bbc.co.uk"}
    payload = build_rss_payload(
        feed, title="Strike", link="https://bbc.co.uk/a",
        summary="body", published_at="2026-05-30T10:00:00+00:00",
        content_hash="h1", enrichment=None,
    )
    assert payload["source_type"] == "rss"
    assert payload["provider"] == "bbc.co.uk"
    assert payload["published_at"] == "2026-05-30T10:00:00+00:00"
    assert payload["feed_name"] == "BBC World"
    assert "credibility_score" not in payload


def test_build_rss_payload_published_none_when_missing():
    feed = {"name": "BBC World", "url": "https://feeds.bbci.co.uk/x", "provider": "bbc.co.uk"}
    payload = build_rss_payload(
        feed, title="t", link="https://bbc.co.uk/a", summary="s",
        published_at=None, content_hash="h2", enrichment=None,
    )
    assert "published_at" not in payload
    assert payload["published"] is None
