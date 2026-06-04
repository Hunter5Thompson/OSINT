import pytest

from feeds.fulltext_collector import (
    THINKTANK_FEEDS,
    article_id,
    build_fulltext_payload,
    fulltext_point_id,
    normalize_url,
)


def test_thinktank_feeds_map():
    assert THINKTANK_FEEDS["CSIS"] == "csis.org"
    assert THINKTANK_FEEDS["War on the Rocks"] == "warontherocks.com"
    assert "rybar" not in THINKTANK_FEEDS  # only think-tanks


def test_point_id_is_deterministic_uint64():
    a = fulltext_point_id("https://csis.org/x", 0)
    b = fulltext_point_id("https://csis.org/x", 0)
    c = fulltext_point_id("https://csis.org/x", 1)
    assert a == b and a != c
    assert isinstance(a, int) and 0 <= a < 2**64


def test_payload_canonical_provenance_and_inherited_meta():
    teaser = {
        "feed_name": "CSIS", "url": "https://csis.org/a", "title": "T",
        "published_at": "2026-01-01T00:00:00+00:00", "published": "2026-01-01T00:00:00+00:00",
        "entities": [{"name": "China", "type": "ORG"}],
    }
    p = build_fulltext_payload(teaser, provider="csis.org", chunk_text="body text",
                               chunk_index=2, chunk_count=5)
    assert p["source"] == "rss_fulltext"
    assert p["source_type"] == "rss"            # canonical → credibility/guard
    assert p["provider"] == "csis.org"          # domain → credibility override
    assert p["feed_name"] == "CSIS"
    assert p["entities"] == teaser["entities"]  # inherited, no LLM
    assert p["content"] == "body text"
    assert p["chunk_index"] == 2 and p["chunk_count"] == 5
    assert p["fulltext_article_id"] == article_id("https://csis.org/a")
    assert "chunk_uid" in p


def test_normalize_url_lowercases_host_preserves_path():
    assert normalize_url("HTTPS://CSIS.ORG/Analysis/Foo/") == "https://csis.org/Analysis/Foo"
    assert normalize_url("  https://rusi.org/x  ") == "https://rusi.org/x"
    assert normalize_url("") == ""
    assert normalize_url(None) == ""


def test_article_id_deterministic_and_distinct():
    assert article_id("https://csis.org/a") == article_id("https://csis.org/a")
    assert article_id("https://csis.org/a") != article_id("https://csis.org/b")


def test_payload_requires_url():
    with pytest.raises(KeyError):
        build_fulltext_payload({"feed_name": "CSIS"}, provider="csis.org",
                               chunk_text="x", chunk_index=0, chunk_count=1)
