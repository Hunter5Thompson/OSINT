"""Unit tests for the Redis cache lifecycle."""

from unittest.mock import AsyncMock

import pytest

from app.services.cache_service import CacheService


@pytest.mark.asyncio
async def test_close_awaits_redis_aclose() -> None:
    cache = CacheService("redis://localhost:6379/0")
    client = AsyncMock()
    cache._redis = client

    await cache.close()

    client.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_corrupt_json_is_a_miss() -> None:
    cache = CacheService("redis://localhost:6379/0")
    client = AsyncMock()
    client.get.return_value = "{not-json"
    cache._redis = client

    assert await cache.get("flights:all") is None


@pytest.mark.asyncio
async def test_json_null_is_a_miss() -> None:
    cache = CacheService("redis://localhost:6379/0")
    client = AsyncMock()
    client.get.return_value = "null"
    cache._redis = client

    assert await cache.get("flights:all") is None


@pytest.mark.asyncio
async def test_get_and_set_without_a_client_are_quiet() -> None:
    cache = CacheService("redis://localhost:6379/0")

    assert await cache.get("flights:all") is None
    await cache.set("flights:all", [{"icao24": "abc"}])
    await cache.delete("flights:all")


@pytest.mark.asyncio
async def test_connect_failure_disables_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = CacheService("redis://localhost:6379/0")
    client = AsyncMock()
    client.ping.side_effect = ConnectionError("down")
    monkeypatch.setattr("app.services.cache_service.redis.from_url", lambda *_a, **_k: client)

    await cache.connect()

    assert cache._redis is None
    assert await cache.get("flights:all") is None
