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
