"""A provider's date must not silently override a conflicting original header."""

from datetime import UTC, datetime

from rag.publication import check_publication


def test_original_day_conflict_is_explicit_without_inventing_an_hour():
    result = check_publication(
        "Published: November 1, 2026\n\nArticle body", datetime(2026, 11, 6, tzinfo=UTC)
    )
    assert result.status == "conflict"
    assert result.original_date.isoformat() == "2026-11-01"


def test_matching_original_day_is_not_a_verified_event_time():
    result = check_publication(
        "Published Nov 5, 2026 at 10:00 AM\nContent", datetime(2026, 11, 5, tzinfo=UTC)
    )
    assert result.status == "matched_day"
    assert result.original_date.isoformat() == "2026-11-05"


def test_body_event_date_is_not_a_publication_header():
    result = check_publication(
        "The attack occurred on November 1, 2026.", datetime(2026, 11, 6, tzinfo=UTC)
    )
    assert result.status == "not_found"
    assert result.original_date is None
