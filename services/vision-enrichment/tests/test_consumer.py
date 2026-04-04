"""Tests for the Redis Stream consumer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consumer import VisionConsumer


def _make_consumer(**overrides):
    from config import Settings

    defaults = {"neo4j_password": "test"}
    defaults.update(overrides)
    s = Settings(**defaults)
    mock_redis = AsyncMock()
    return VisionConsumer(redis_client=mock_redis, settings_override=s), mock_redis


class TestConsumerSetup:
    async def test_ensure_group_creates_if_missing(self):
        consumer, mock_redis = _make_consumer()
        mock_redis.xgroup_create.return_value = True
        await consumer.ensure_consumer_group()
        mock_redis.xgroup_create.assert_called_once_with(
            "vision:pending",
            "vision-workers",
            id="0",
            mkstream=True,
        )

    async def test_ensure_group_ignores_busygroup(self):
        """If group already exists, should not raise."""
        import redis as redis_lib

        consumer, mock_redis = _make_consumer()
        mock_redis.xgroup_create.side_effect = redis_lib.ResponseError("BUSYGROUP")
        await consumer.ensure_consumer_group()  # should not raise


class TestProcessMessage:
    async def test_calls_vision_and_updates_neo4j_and_qdrant(self):
        consumer, mock_redis = _make_consumer()

        msg_data = {
            b"channel": b"OSINTdefender",
            b"message_id": b"123",
            b"media_path": b"/data/photo.jpg",
            b"source_bias": b"neutral",
            b"source": b"telegram",
            b"url": b"https://t.me/OSINTdefender/123",
        }

        mock_vision_result = {
            "scene_description": "Military equipment",
            "visible_text": "",
            "military_equipment": ["T-72"],
            "location_indicators": [],
            "map_annotations": [],
            "damage_assessment": "",
        }

        mock_point = MagicMock()
        mock_point.id = 12345

        with (
            patch("consumer.analyze_image", return_value=mock_vision_result),
            patch("consumer.httpx.AsyncClient") as MockClient,
            patch("consumer.QdrantClient") as MockQdrant,
        ):
            mock_http = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            import httpx

            mock_http.post.return_value = httpx.Response(
                200,
                json={"results": [], "errors": []},
                request=httpx.Request("POST", "http://neo4j"),
            )

            mock_qdrant_instance = MagicMock()
            MockQdrant.return_value = mock_qdrant_instance
            mock_qdrant_instance.scroll.return_value = ([mock_point], None)

            await consumer._process_message(b"stream-id-1", msg_data)

            # Should update Qdrant payload
            mock_qdrant_instance.set_payload.assert_called_once()
            set_payload_kwargs = mock_qdrant_instance.set_payload.call_args
            payload = set_payload_kwargs.kwargs.get(
                "payload", set_payload_kwargs[1].get("payload", {})
            )
            assert "vision_description" in payload
            # Should ACK the message
            mock_redis.xack.assert_called_once()

    async def test_neo4j_error_prevents_ack(self):
        """If Neo4j returns Cypher errors, message should NOT be ACKed."""
        consumer, mock_redis = _make_consumer()

        msg_data = {
            b"channel": b"test",
            b"message_id": b"1",
            b"media_path": b"/data/photo.jpg",
            b"source_bias": b"neutral",
            b"source": b"telegram",
            b"url": b"https://t.me/test/1",
        }

        mock_redis.hincrby.return_value = 1  # first retry

        with (
            patch("consumer.analyze_image", return_value={"scene_description": "test"}),
            patch("consumer.httpx.AsyncClient") as MockClient,
        ):
            mock_http = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            import httpx

            mock_http.post.return_value = httpx.Response(
                200,
                json={"results": [], "errors": [{"message": "SyntaxError"}]},
                request=httpx.Request("POST", "http://neo4j"),
            )

            await consumer._process_message(b"msg-1", msg_data)

        # Should NOT ACK because Neo4j had errors
        assert mock_redis.xack.call_count == 0


class TestPoisonMessages:
    async def test_dead_letter_after_max_retries(self):
        consumer, mock_redis = _make_consumer()
        consumer._settings.vision_max_retries = 3

        msg_data = {
            b"channel": b"test",
            b"message_id": b"1",
            b"media_path": b"/data/broken.jpg",
            b"source_bias": b"neutral",
            b"source": b"telegram",
            b"url": b"https://t.me/test/1",
        }

        # Simulate exceeded max retries
        mock_redis.hincrby.return_value = 4

        with patch("consumer.analyze_image", side_effect=Exception("GPU OOM")):
            await consumer._process_message(b"msg-id-1", msg_data)

        # Should XADD to dead letter queue and XACK
        mock_redis.xadd.assert_called_once()
        xadd_args = mock_redis.xadd.call_args
        assert xadd_args[0][0] == "vision:dead_letter"
        mock_redis.xack.assert_called_once()
