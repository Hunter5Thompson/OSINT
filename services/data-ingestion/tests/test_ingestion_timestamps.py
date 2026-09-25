"""Every Qdrant payload builder stamps the canonical numeric ``ingested_epoch``.

The backend feed-freshness watchdog orders by ``ingested_epoch`` per source; a writer that
only stamps the ISO ``ingested_at`` string would read as a permanently *missing* feed.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from feeds.fulltext_collector import build_fulltext_payload
from feeds.provenance import ingestion_timestamps
from feeds.rss_collector import build_rss_payload
from feeds.telegram_collector import build_telegram_payload
from gdelt_raw.writers.qdrant_writer import build_payload as build_gdelt_payload


def _assert_consistent_stamps(payload: dict) -> None:
    assert isinstance(payload["ingested_epoch"], float)
    assert payload["ingested_epoch"] == pytest.approx(
        datetime.fromisoformat(payload["ingested_at"]).timestamp()
    )


def test_ingestion_timestamps_share_one_instant():
    _assert_consistent_stamps(ingestion_timestamps())


def test_rss_payload_stamps_epoch():
    _assert_consistent_stamps(build_rss_payload(
        {"name": "BBC", "url": "https://x", "provider": "bbc.co.uk"},
        title="t", link="https://bbc.co.uk/a", summary="s", published_at=None,
        content_hash="h", enrichment=None,
    ))


def test_fulltext_payload_stamps_epoch():
    _assert_consistent_stamps(build_fulltext_payload(
        {"feed_name": "CSIS", "url": "https://csis.org/a"}, provider="csis.org",
        chunk_text="body", chunk_index=0, chunk_count=1,
    ))


def test_telegram_payload_stamps_epoch():
    _assert_consistent_stamps(build_telegram_payload(
        channel=SimpleNamespace(handle="@Rybar", source_bias="state", category="mil"),
        message_id=1, title="m", url="https://t.me/Rybar/1", published=None,
        content_hash="h", enrichment=None, forwarded_from=None, has_media=False,
        media_paths=[], media_types=[], vision_status="none",
    ))


def test_gdelt_gkg_payload_stamps_epoch():
    _assert_consistent_stamps(build_gdelt_payload({"doc_id": "d1"}))
