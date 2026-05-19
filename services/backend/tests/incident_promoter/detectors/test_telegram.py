"""Unit tests for Telegram detector helpers."""
import pytest

from app.services.incident_promoter.detectors.telegram import (
    _domain_of,
    _jaccard_5gram,
    _normalize_title,
    _shingles,
)


def test_normalize_lowercases_strips_urls_and_punctuation():
    raw = "BREAKING: Strike on Kharkiv https://t.me/foo/123 — confirmed!!"
    assert _normalize_title(raw) == "breaking strike on kharkiv confirmed"


def test_shingles_of_short_text_returns_single_token_tuple():
    assert _shingles("a b") == {("a", "b")}


def test_shingles_5gram_for_long_text():
    s = _shingles("alpha bravo charlie delta echo foxtrot")
    # 2 windows of 5 tokens each
    assert ("alpha", "bravo", "charlie", "delta", "echo") in s
    assert ("bravo", "charlie", "delta", "echo", "foxtrot") in s


def test_jaccard_5gram_identical_is_one():
    a = _shingles("strike on kharkiv overnight powerful")
    b = _shingles("strike on kharkiv overnight powerful")
    assert _jaccard_5gram(a, b) == 1.0


def test_jaccard_5gram_disjoint_is_zero():
    a = _shingles("alpha bravo charlie delta echo")
    b = _shingles("zulu yankee xray whisky victor")
    assert _jaccard_5gram(a, b) == 0.0


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://t.me/OSINTdefender/12345", "t.me"),
        ("http://example.com/path", "example.com"),
        ("", ""),
        (None, ""),
    ],
)
def test_domain_of(url, expected):
    assert _domain_of(url) == expected
