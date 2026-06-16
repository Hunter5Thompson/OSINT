"""WP-06: GDELT ArtList seendate -> ISO-8601 observed_at. Empty/malformed -> None
(falls back to the ingested basis; never fabricates a fake instant)."""
from feeds.gdelt_collector import _normalize_seendate


def test_full_timestamp_to_iso():
    assert _normalize_seendate("20260610T120000Z") == "2026-06-10T12:00:00+00:00"


def test_date_only_anchors_to_utc_midnight():
    # lower-resolution but correct DAY -> correct CHRONIK bucket; strictly better
    # than drifting to ingest-time. (Real GDELT seendate is the full timestamp.)
    assert _normalize_seendate("20260610") == "2026-06-10T00:00:00+00:00"


def test_empty_is_none():
    assert _normalize_seendate("") is None
    assert _normalize_seendate(None) is None


def test_malformed_is_none():
    assert _normalize_seendate("last tuesday") is None
    assert _normalize_seendate("2026-06-10") is None  # dashed form is not GDELT's
