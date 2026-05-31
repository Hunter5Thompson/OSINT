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
