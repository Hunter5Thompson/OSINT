"""Redis cache service with TTL support."""

import json
from typing import Any

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()


class CacheService:
    def __init__(self, redis_url: str) -> None:
        self._redis: redis.Redis | None = None
        self._redis_url = redis_url

    async def connect(self) -> None:
        self._redis = redis.from_url(self._redis_url, decode_responses=True)
        try:
            await self._redis.ping()
            logger.info("redis_connected", url=self._redis_url)
        except Exception:
            logger.warning("redis_connection_failed", url=self._redis_url)
            self._redis = None

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()

    async def get(self, key: str) -> Any | None:
        if not self._redis:
            return None
        try:
            value = await self._redis.get(key)
            if value is not None:
                return json.loads(value)
        except Exception:
            logger.warning("cache_get_error", key=key)
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 60) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception:
            logger.warning("cache_set_error", key=key)

    async def delete(self, key: str) -> None:
        if not self._redis:
            return
        try:
            await self._redis.delete(key)
        except Exception:
            logger.warning("cache_delete_error", key=key)
