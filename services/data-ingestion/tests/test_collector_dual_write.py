from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline import Neo4jWriteError


@pytest.mark.asyncio
async def test_gdelt_skips_point_on_neo4j_write_error():
    """When process_item raises Neo4jWriteError, the article's point is NOT appended
    to the Qdrant batch (so the dedup key is not minted and the item retries)."""
    from feeds import gdelt_collector

    col = gdelt_collector.GDELTCollector.__new__(gdelt_collector.GDELTCollector)
    col.qdrant = MagicMock()
    col.qdrant.retrieve = MagicMock(return_value=[])   # not a duplicate
    col.qdrant.upsert = MagicMock()
    col._redis = None
    col._embed = AsyncMock(return_value=[0.0] * 1024)

    articles = [{"title": "t", "url": "http://u", "seendate": "", "domain": "",
                 "language": "", "sourcecountry": ""}]

    with patch.object(gdelt_collector, "process_item",
                      AsyncMock(side_effect=Neo4jWriteError("down"))):
        n = await col._ingest_articles(articles, "q")

    assert n == 0
    col.qdrant.upsert.assert_not_called()
    col._embed.assert_not_called()


@pytest.mark.asyncio
async def test_gdelt_skips_item_on_dedup_retrieve_failure():
    """A transient Qdrant fault during the dedup retrieve skips the item (keeps the
    batch): process_item is never reached, nothing is embedded or upserted."""
    from feeds import gdelt_collector

    col = gdelt_collector.GDELTCollector.__new__(gdelt_collector.GDELTCollector)
    col.qdrant = MagicMock()
    col.qdrant.retrieve = MagicMock(side_effect=RuntimeError("qdrant down"))
    col.qdrant.upsert = MagicMock()
    col._redis = None
    col._embed = AsyncMock(return_value=[0.0] * 1024)

    articles = [{"title": "t", "url": "http://u", "seendate": "", "domain": "",
                 "language": "", "sourcecountry": ""}]

    with patch.object(gdelt_collector, "process_item", AsyncMock()) as pi:
        n = await col._ingest_articles(articles, "q")

    assert n == 0
    pi.assert_not_called()
    col.qdrant.upsert.assert_not_called()
    col._embed.assert_not_called()


def _rss_collector_with_one_entry():
    """An RSSCollector instance (bypassing __init__) whose feed fetch + feedparser are
    mocked to yield exactly one entry; returns (col, patches_contextmanager_factory)."""
    from feeds import rss_collector

    col = rss_collector.RSSCollector.__new__(rss_collector.RSSCollector)
    col.qdrant = MagicMock()
    col.qdrant.retrieve = MagicMock(return_value=[])
    col.qdrant.upsert = MagicMock()
    col._redis = None
    col._embed = AsyncMock(return_value=[0.0] * 1024)
    return col


def _mock_feed_fetch():
    """patch() contexts for the httpx fetch + feedparser yielding one entry."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = "<rss/>"
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    feed = SimpleNamespace(
        bozo=False,
        entries=[{"title": "t", "link": "http://u", "summary": "s"}],
    )
    return (
        patch("feeds.rss_collector.httpx.AsyncClient", return_value=cm),
        patch("feeds.rss_collector.feedparser.parse", return_value=feed),
    )


@pytest.mark.asyncio
async def test_rss_skips_point_on_neo4j_write_error():
    from feeds import rss_collector

    col = _rss_collector_with_one_entry()
    http_patch, fp_patch = _mock_feed_fetch()
    with http_patch, fp_patch, patch.object(
        rss_collector, "process_item", AsyncMock(side_effect=Neo4jWriteError("down"))
    ):
        n = await col._process_feed({"name": "f", "url": "http://feed"})

    assert n == 0
    col.qdrant.upsert.assert_not_called()
    col._embed.assert_not_called()


@pytest.mark.asyncio
async def test_rss_skips_item_on_dedup_retrieve_failure():
    from feeds import rss_collector

    col = _rss_collector_with_one_entry()
    col.qdrant.retrieve = MagicMock(side_effect=RuntimeError("qdrant down"))
    http_patch, fp_patch = _mock_feed_fetch()
    with http_patch, fp_patch, patch.object(
        rss_collector, "process_item", AsyncMock()
    ) as pi:
        n = await col._process_feed({"name": "f", "url": "http://feed"})

    assert n == 0
    pi.assert_not_called()
    col.qdrant.upsert.assert_not_called()
    col._embed.assert_not_called()
