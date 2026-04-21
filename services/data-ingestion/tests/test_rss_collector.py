"""Tests for rss_collector error-handling behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.rss_collector import RSSCollector
from pipeline import ExtractionConfigError, ExtractionTransientError


@pytest.fixture
def mock_qdrant():
    return MagicMock()


def _entry(title="T", link="http://e/1"):
    return {
        "title": title, "link": link, "summary": "s",
        "published": "2026-01-01", "published_parsed": None,
    }


@pytest.mark.asyncio
async def test_transient_error_skips_qdrant_upsert(mock_qdrant, monkeypatch):
    """When process_item raises ExtractionTransientError, item is NOT upserted."""
    parsed = MagicMock()
    parsed.entries = [_entry()]
    parsed.bozo = False

    mock_qdrant.retrieve.return_value = []  # not a duplicate

    collector = RSSCollector.__new__(RSSCollector)
    collector.qdrant = mock_qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.rss_collector.feedparser.parse", return_value=parsed), \
         patch("feeds.rss_collector.process_item",
               new=AsyncMock(side_effect=ExtractionTransientError("down"))), \
         patch("feeds.rss_collector.httpx.AsyncClient") as mock_http:
        # Mock the feed-fetch HTTP response (any 200 with text body).
        feed_resp = MagicMock()
        feed_resp.status_code = 200
        feed_resp.text = "<rss/>"
        feed_resp.raise_for_status = MagicMock()
        mc = AsyncMock()
        mc.get.return_value = feed_resp
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector._process_feed({"name": "test", "url": "http://feed/x"})

    mock_qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_config_error_skips_qdrant_upsert(mock_qdrant):
    """When process_item raises ExtractionConfigError, item is NOT upserted."""
    parsed = MagicMock()
    parsed.entries = [_entry()]
    parsed.bozo = False

    mock_qdrant.retrieve.return_value = []

    collector = RSSCollector.__new__(RSSCollector)
    collector.qdrant = mock_qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.rss_collector.feedparser.parse", return_value=parsed), \
         patch("feeds.rss_collector.process_item",
               new=AsyncMock(side_effect=ExtractionConfigError("404 model"))), \
         patch("feeds.rss_collector.httpx.AsyncClient") as mock_http, \
         patch("feeds.rss_collector.log.error") as mock_err:
        feed_resp = MagicMock()
        feed_resp.status_code = 200
        feed_resp.text = "<rss/>"
        feed_resp.raise_for_status = MagicMock()
        mc = AsyncMock()
        mc.get.return_value = feed_resp
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector._process_feed({"name": "test", "url": "http://feed/x"})

    mock_qdrant.upsert.assert_not_called()
    # Error log was emitted with the canonical key.
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)
