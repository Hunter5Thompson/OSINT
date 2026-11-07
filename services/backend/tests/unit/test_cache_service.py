"""Unit tests for the Redis cache lifecycle."""

import asyncio
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
async def test_connect_failure_recovers_after_bounded_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = CacheService("redis://localhost:6379/0")
    client = AsyncMock()
    client.ping.side_effect = [ConnectionError("down"), True]
    client.get.return_value = '{"recovered": true}'
    clock = [100.0]
    monkeypatch.setattr("app.services.cache_service.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.services.cache_service.redis.from_url", lambda *_a, **_k: client)

    await cache.connect()

    assert cache._redis is client
    assert await cache.get("flights:all") is None
    client.ping.assert_awaited_once()
    clock[0] += 10
    assert await cache.get("flights:all") == {"recovered": True}
    assert client.ping.await_count == 2


async def test_later_outage_and_concurrent_recovery_use_one_probe(monkeypatch) -> None:
    cache = CacheService("redis://localhost:6379/0")
    client = AsyncMock()
    monkeypatch.setattr("app.services.cache_service.redis.from_url", lambda *_a, **_k: client)
    clock = [100.0]
    monkeypatch.setattr("app.services.cache_service.time.monotonic", lambda: clock[0])
    await cache.connect()
    client.get.side_effect = ConnectionError("down")
    assert await cache.get("test") is None
    clock[0] += 10
    entered, resume = asyncio.Event(), asyncio.Event()

    async def ping():
        entered.set()
        await resume.wait()
        return True

    client.ping.side_effect = ping
    client.get.side_effect = None
    client.get.return_value = '42'
    first = asyncio.create_task(cache.get("test"))
    await entered.wait()
    assert await asyncio.gather(*(cache.get("test") for _ in range(20))) == [None] * 20
    resume.set()
    assert await first == 42
    assert client.ping.await_count == 2
    assert await cache.get("test") == 42


async def test_stalled_ping_is_bounded_and_client_can_be_closed(monkeypatch) -> None:
    cache = CacheService("redis://localhost:6379/0")
    client = AsyncMock()
    async def stalled():
        await asyncio.sleep(10)
    client.ping.side_effect = stalled
    monkeypatch.setattr("app.services.cache_service.redis.from_url", lambda *_a, **_k: client)
    monkeypatch.setattr("app.services.cache_service.OPERATION_TIMEOUT_S", 0.01)
    await asyncio.wait_for(cache.connect(), timeout=0.2)
    await cache.close()
    client.aclose.assert_awaited_once()
