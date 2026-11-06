"""Fetch coverage must survive failures without exposing credential-bearing URLs."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from feeds.availability import KEY, catalog, record_fetch


@pytest.mark.asyncio
async def test_failure_does_not_replace_last_success_or_other_feed():
    redis = AsyncMock()
    await record_fetch(redis, "rss", "A", item_count=0, now=100)
    success = redis.hset.call_args.kwargs["mapping"]
    await record_fetch(redis, "rss", "A", error_code="http_403", now=200)
    failure = redis.hset.call_args.kwargs["mapping"]
    assert redis.hset.call_args.args == (KEY,)
    assert success["rss:A:last_success"] == "100"
    assert "rss:A:last_success" not in failure
    assert json.loads(failure["rss:A"])["status"] == "unavailable"
    assert json.loads(success["rss:A"])["item_count"] == 0
    assert set(failure) == {"rss:A"}


@pytest.mark.asyncio
async def test_telemetry_outage_is_bounded_and_does_not_break_ingestion():
    redis = AsyncMock()
    redis.hset.side_effect = ConnectionError("private credentials")
    await record_fetch(redis, "rss", "A", item_count=3)
    await record_fetch(None, "rss", "A", item_count=3)


def test_catalog_covers_every_configured_rss_ofac_and_hapi_feed():
    from feeds.hapi_collector import FOCUS_COUNTRIES
    from feeds.ofac_collector import OFAC_FEEDS
    from feeds.rss_collector import RSS_FEEDS

    entries = catalog()
    assert {e["id"] for e in entries} == (
        {f"rss:{feed['name']}" for feed in RSS_FEEDS}
        | {f"ofac:{name}" for name in OFAC_FEEDS}
        | {f"hapi:{country}" for country in FOCUS_COUNTRIES}
    )


@pytest.mark.asyncio
async def test_rss_http_failure_and_empty_success_are_recorded():
    from feeds.rss_collector import RSSCollector

    collector = RSSCollector.__new__(RSSCollector)
    collector._redis = AsyncMock()
    for status, body, expected in [
        (403, "blocked", "unavailable"),
        (200, '<rss version="2.0"><channel><title>A</title></channel></rss>', "available"),
        (200, "<html><body>not a feed</body></html>", "unavailable"),
    ]:
        transport = httpx.MockTransport(
            lambda request, code=status, text=body: httpx.Response(code, text=text)
        )
        client = httpx.AsyncClient(transport=transport)
        with patch("feeds.rss_collector.httpx.AsyncClient", return_value=client):
            await collector._process_feed({"name": "A", "url": "https://feed.example"})
        mapping = collector._redis.hset.call_args.kwargs["mapping"]
        assert json.loads(mapping["rss:A"])["status"] == expected
