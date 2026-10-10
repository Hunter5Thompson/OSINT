"""S04 preflight precedes every persistence side effect; retries recheck."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from qdrant_client.models import (
    CollectionConfig,
    CollectionInfo,
    CollectionParams,
    Distance,
    VectorParams,
)

from config import Settings
from consumer import VisionConsumer


def _info(size=1024):
    params = CollectionParams.model_construct(
        vectors=VectorParams(size=size, distance=Distance.COSINE), sparse_vectors=None
    )
    return CollectionInfo.model_construct(config=CollectionConfig.model_construct(params=params))


@pytest.mark.parametrize("second", ["valid", "mismatch", "missing"])
async def test_timeout_then_second_schema_check_controls_all_writes(second):
    redis = AsyncMock()
    redis.hincrby.return_value = 1
    consumer = VisionConsumer(redis, Settings(neo4j_password="test"))
    qdrant = MagicMock()
    named = MagicMock()
    named.name = "odin_intel"
    collections = MagicMock(collections=[] if second == "missing" else [named])
    qdrant.get_collections.side_effect = [
        TimeoutError("synthetic timeout"),
        collections,
        collections,
    ]
    qdrant.get_collection.return_value = _info(384 if second == "mismatch" else 1024)
    point = MagicMock(id=1)
    qdrant.scroll.return_value = ([point], None)
    http = AsyncMock()
    http.post.return_value = httpx.Response(
        200,
        json={"results": [{"columns": ["updated_count"], "data": [{"row": [1]}]}], "errors": []},
        request=httpx.Request("POST", "http://neo4j"),
    )
    message = {b"url": b"https://unit.example/1", b"media_path": b"/data/synthetic.jpg"}
    with (
        patch("consumer.QdrantClient", return_value=qdrant),
        patch("consumer.httpx.AsyncClient") as client,
        patch("consumer.analyze_image", AsyncMock(return_value={"scene_description": "synthetic"})),
    ):
        client.return_value.__aenter__ = AsyncMock(return_value=http)
        client.return_value.__aexit__ = AsyncMock(return_value=False)
        await consumer._process_message(b"1-0", message)
        assert consumer._qdrant_schema_validated is False
        http.post.assert_not_awaited()
        qdrant.set_payload.assert_not_called()
        redis.xadd.assert_not_awaited()
        redis.xack.assert_not_awaited()
        await consumer._process_message(b"1-0", message)
        assert qdrant.get_collections.call_count == 2
        if second == "valid":
            assert consumer._qdrant_schema_validated is True
            assert (
                http.post.await_count
                == qdrant.set_payload.call_count
                == redis.xadd.await_count
                == redis.xack.await_count
                == 1
            )
            await consumer._process_message(b"2-0", message)
            assert qdrant.get_collections.call_count == 2
        else:
            assert consumer._qdrant_schema_validated is False
            http.post.assert_not_awaited()
            qdrant.set_payload.assert_not_called()
            redis.xadd.assert_not_awaited()
            redis.xack.assert_not_awaited()


@pytest.mark.parametrize("failure", ["neo4j_missing", "qdrant_missing", "qdrant_write"])
async def test_partial_persistence_does_not_publish_success_or_ack(failure):
    redis = AsyncMock()
    redis.hincrby.return_value = 1
    consumer = VisionConsumer(redis, Settings(neo4j_password="test"))
    qdrant = MagicMock()
    named = MagicMock()
    named.name = "odin_intel"
    qdrant.get_collections.return_value.collections = [named]
    qdrant.get_collection.return_value = _info()
    qdrant.scroll.return_value = (
        ([], None) if failure == "qdrant_missing" else ([MagicMock(id=1)], None)
    )
    if failure == "qdrant_write":
        qdrant.set_payload.side_effect = TimeoutError("synthetic write timeout")
    http = AsyncMock()
    count = 0 if failure == "neo4j_missing" else 1
    http.post.return_value = httpx.Response(
        200,
        json={
            "results": [{"columns": ["updated_count"], "data": [{"row": [count]}]}],
            "errors": [],
        },
        request=httpx.Request("POST", "http://neo4j"),
    )
    with (
        patch("consumer.QdrantClient", return_value=qdrant),
        patch("consumer.httpx.AsyncClient") as client,
        patch("consumer.analyze_image", AsyncMock(return_value={"scene_description": "synthetic"})),
    ):
        client.return_value.__aenter__ = AsyncMock(return_value=http)
        client.return_value.__aexit__ = AsyncMock(return_value=False)
        await consumer._process_message(b"1-0", {b"url": b"https://unit.example/1"})
    redis.xadd.assert_not_awaited()
    redis.xack.assert_not_awaited()
    redis.hincrby.assert_awaited_once()
