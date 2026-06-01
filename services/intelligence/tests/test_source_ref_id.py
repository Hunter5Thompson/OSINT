from __future__ import annotations

from rag.evidence import compute_source_ref_id


def test_external_key_wins_and_is_stable():
    a = compute_source_ref_id(
        source_type="gdelt", provider="reuters.com",
        external_key="doc-123", url="https://x", content_hash="h", title="t", excerpt="e",
    )
    b = compute_source_ref_id(
        source_type="gdelt", provider="reuters.com",
        external_key="doc-123", url="https://other", content_hash="h2", title="t2", excerpt="e2",
    )
    assert a == b  # identity is the external key; other fields don't change it
    assert len(a) == 20


def test_falls_back_to_url_then_hash_then_title_excerpt():
    by_url = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url="https://bbc.com/a", content_hash=None, title="t", excerpt="e",
    )
    by_hash = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url=None, content_hash="abc", title="t", excerpt="e",
    )
    by_text = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url=None, content_hash=None, title="t", excerpt="e",
    )
    assert len({by_url, by_hash, by_text}) == 3
    assert all(len(x) == 20 for x in (by_url, by_hash, by_text))


def test_provider_is_normalized_into_identity():
    upper = compute_source_ref_id(
        source_type="rss", provider="BBC.com",
        external_key=None, url="https://bbc.com/a", content_hash=None, title="t", excerpt="e",
    )
    lower = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url="https://bbc.com/a", content_hash=None, title="t", excerpt="e",
    )
    assert upper == lower
