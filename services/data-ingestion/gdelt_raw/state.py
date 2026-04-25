"""Redis-backed state for GDELT ingestion.

Two layers:
  - Per-slice per-stream/store state (primary truth)
  - Summary last-slice keys (for fast UI/status)
"""

from __future__ import annotations

from typing import Literal


StreamName = Literal["events", "mentions", "gkg"]
StoreName = Literal["parquet", "neo4j", "qdrant"]


def _stream_key(slice_id: str, stream: StreamName) -> str:
    return f"gdelt:slice:{slice_id}:{stream}:parquet"


def _store_key(slice_id: str, store: Literal["neo4j", "qdrant"]) -> str:
    return f"gdelt:slice:{slice_id}:{store}"


def _pending_key(store: Literal["neo4j", "qdrant"]) -> str:
    return f"gdelt:pending:{store}"


def _last_slice_key(store: StoreName) -> str:
    return f"gdelt:forward:last_slice:{store}"


class GDELTState:
    def __init__(self, redis_client):
        self.r = redis_client

    async def set_stream_parquet(self, slice_id: str, stream: StreamName, value: str):
        await self.r.set(_stream_key(slice_id, stream), value)

    async def get_stream_parquet(self, slice_id: str, stream: StreamName) -> str | None:
        return await self.r.get(_stream_key(slice_id, stream))

    async def set_store_state(
        self, slice_id: str, store: Literal["neo4j", "qdrant"], value: str
    ):
        await self.r.set(_store_key(slice_id, store), value)

    async def get_store_state(
        self, slice_id: str, store: Literal["neo4j", "qdrant"]
    ) -> str | None:
        return await self.r.get(_store_key(slice_id, store))

    async def add_pending(self, store: Literal["neo4j", "qdrant"], slice_id: str):
        await self.r.zadd(_pending_key(store), {slice_id: int(slice_id)})

    async def remove_pending(self, store: Literal["neo4j", "qdrant"], slice_id: str):
        await self.r.zrem(_pending_key(store), slice_id)

    async def list_pending(
        self, store: Literal["neo4j", "qdrant"], limit: int = 10
    ) -> list[str]:
        return await self.r.zrange(_pending_key(store), 0, limit - 1)

    async def set_last_slice(self, store: StoreName, slice_id: str):
        await self.r.set(_last_slice_key(store), slice_id)

    async def get_last_slice(self, store: StoreName) -> str | None:
        return await self.r.get(_last_slice_key(store))

    async def is_slice_fully_done(self, slice_id: str) -> bool:
        for st in ("events", "mentions", "gkg"):
            if await self.get_stream_parquet(slice_id, st) != "done":
                return False
        for store in ("neo4j", "qdrant"):
            if await self.get_store_state(slice_id, store) != "done":
                return False
        return True
