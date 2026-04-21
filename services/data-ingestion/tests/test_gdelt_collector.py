"""Tests for gdelt_collector error-handling behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.gdelt_collector import GDELTCollector
from pipeline import ExtractionConfigError, ExtractionTransientError


def _gdelt_response(articles: list[dict] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "articles": articles
        if articles is not None
        else [
            {
                "title": "x",
                "url": "http://e/1",
                "seendate": "20260101T000000Z",
                "domain": "ex.com",
                "language": "English",
            }
        ]
    }
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_gdelt_transient_skips_upsert():
    """When process_item raises ExtractionTransientError, item is NOT upserted."""
    qdrant = MagicMock()
    qdrant.retrieve.return_value = []  # not a duplicate

    collector = GDELTCollector.__new__(GDELTCollector)
    collector.qdrant = qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.gdelt_collector.httpx.AsyncClient") as mock_cls, \
         patch("feeds.gdelt_collector.process_item",
               new=AsyncMock(side_effect=ExtractionTransientError("down"))):
        mc = AsyncMock()
        mc.get.return_value = _gdelt_response()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector.collect()

    qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_gdelt_config_skips_upsert():
    """When process_item raises ExtractionConfigError, item is NOT upserted."""
    qdrant = MagicMock()
    qdrant.retrieve.return_value = []

    collector = GDELTCollector.__new__(GDELTCollector)
    collector.qdrant = qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.gdelt_collector.httpx.AsyncClient") as mock_cls, \
         patch("feeds.gdelt_collector.process_item",
               new=AsyncMock(side_effect=ExtractionConfigError("404"))), \
         patch("feeds.gdelt_collector.log.error") as mock_err:
        mc = AsyncMock()
        mc.get.return_value = _gdelt_response()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector.collect()

    qdrant.upsert.assert_not_called()
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)
