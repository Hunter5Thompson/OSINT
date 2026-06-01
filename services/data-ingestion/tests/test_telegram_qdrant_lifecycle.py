"""Qdrant lifecycle tests for the Telegram collector."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import Settings
from feeds.telegram_collector import TelegramCollector
from feeds.telegram_models import ChannelConfig


def _settings() -> Settings:
    return Settings(
        telegram_api_id=12345,
        telegram_api_hash="test",
        telegram_channels_config="feeds/telegram_channels.yaml",
    )


def _channel() -> ChannelConfig:
    return ChannelConfig(
        handle="test",
        name="Test",
        category="osint",
        source_bias="neutral",
        language="en",
        priority="high",
        media=False,
    )


def test_telegram_init_does_not_touch_qdrant_network() -> None:
    with (
        patch("feeds.telegram_collector._load_channels", return_value=[]),
        patch(
            "feeds.telegram_collector.QdrantClient",
            side_effect=AssertionError("network call in __init__"),
        ),
    ):
        collector = TelegramCollector(settings_override=_settings())

    assert collector.qdrant is None


@pytest.mark.asyncio
async def test_telegram_preflights_existing_collection_once_off_loop() -> None:
    qdrant = MagicMock()
    collection = MagicMock(name="odin_intel")
    collection.name = "odin_intel"
    info = MagicMock()

    def get_collections() -> MagicMock:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return MagicMock(collections=[collection])

    def get_collection(_: str) -> MagicMock:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return info

    qdrant.get_collections = get_collections
    qdrant.get_collection = get_collection

    with (
        patch("feeds.telegram_collector._load_channels", return_value=[]),
        patch("feeds.telegram_collector.QdrantClient", create=True, return_value=qdrant),
        patch("feeds.telegram_collector.validate_collection_schema", create=True) as validate,
    ):
        collector = TelegramCollector(settings_override=_settings())
        await collector._ensure_collection()
        await collector._ensure_collection()

    validate.assert_called_once_with(info, enable_hybrid=False)


@pytest.mark.asyncio
async def test_telegram_upsert_reuses_owned_client_and_runs_off_loop() -> None:
    qdrant = MagicMock()

    def upsert(**_: object) -> None:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()

    qdrant.upsert = upsert

    collector = TelegramCollector.__new__(TelegramCollector)
    collector._settings = _settings()
    collector.qdrant = qdrant
    collector._collection_ready = True

    response = MagicMock()
    response.json.return_value = [[0.0] * 1024]
    response.raise_for_status = MagicMock()
    http = AsyncMock()
    http.post.return_value = response

    with (
        patch("httpx.AsyncClient") as http_cls,
        patch("qdrant_client.QdrantClient", side_effect=AssertionError("per-message client")),
    ):
        http_cls.return_value.__aenter__ = AsyncMock(return_value=http)
        http_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        persisted = await collector._embed_and_upsert(
            content_hash="1" * 64,
            title="Title",
            text="Text",
            url="https://t.me/test/1",
            published="2026-06-01T12:00:00+00:00",
            channel=_channel(),
            message_id=1,
            forwarded_from=None,
            has_media=False,
            media_paths=[],
            media_types=[],
            vision_status="skipped",
            enrichment=None,
        )

    assert persisted is True


@pytest.mark.asyncio
async def test_telegram_close_disconnects_and_releases_qdrant() -> None:
    collector = TelegramCollector.__new__(TelegramCollector)
    collector._client = MagicMock(disconnect=AsyncMock())
    collector.qdrant = MagicMock()

    await collector.close()

    collector._client.disconnect.assert_awaited_once()
    collector.qdrant.close.assert_called_once_with()
