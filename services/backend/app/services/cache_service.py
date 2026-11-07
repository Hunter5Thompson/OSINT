"""Redis cache service with TTL support."""

import asyncio
import json
import time
from typing import Any, cast

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()
OPERATION_TIMEOUT_S = 1.0
RETRY_DELAY_S = 5.0


class CacheService:
    def __init__(self, redis_url: str) -> None:
        self._redis: redis.Redis | None = None
        self._redis_url = redis_url
        self._healthy = False
        self._retry_after = 0.0
        self._probe_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._redis is None:
            self._redis = redis.from_url(
                self._redis_url, decode_responses=True,
                socket_connect_timeout=0.5, socket_timeout=0.5,
            )
        await self.check_ready()

    def _failed(self) -> None:
        self._healthy = False
        self._retry_after = time.monotonic() + RETRY_DELAY_S

    async def _available(self, *, probe: bool = False) -> bool:
        if self._redis is None:
            return False
        if self._healthy and not probe:
            return True
        if time.monotonic() < self._retry_after or self._probe_lock.locked():
            return False
        async with self._probe_lock:
            try:
                async with asyncio.timeout(OPERATION_TIMEOUT_S):
                    await cast(Any, self._redis).ping()
                self._healthy = True
                self._retry_after = 0
                return True
            except Exception:
                self._failed()
                logger.warning("redis_probe_failed")
                return False

    async def check_ready(self) -> bool:
        """Bounded active probe; one request owns recovery, peers fail softly."""
        return await self._available(probe=True)

    async def close(self) -> None:
        client, self._redis = self._redis, None
        self._healthy = False
        if client is not None:
            async with asyncio.timeout(OPERATION_TIMEOUT_S):
                await cast(Any, client).aclose()

    async def get(self, key: str) -> Any | None:
        if not await self._available():
            return None
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_S):
                value = await cast(Any, self._redis).get(key)
            if value is not None:
                return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            logger.warning("cache_value_invalid", key=key)
        except Exception:
            self._failed()
            logger.warning("cache_get_error", key=key)
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 60) -> None:
        if not await self._available():
            return
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_S):
                await cast(Any, self._redis).set(
                    key, json.dumps(value, default=str), ex=ttl_seconds
                )
        except Exception:
            self._failed()
            logger.warning("cache_set_error", key=key)

    async def delete(self, key: str) -> None:
        if not await self._available():
            return
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_S):
                await cast(Any, self._redis).delete(key)
        except Exception:
            self._failed()
            logger.warning("cache_delete_error", key=key)
