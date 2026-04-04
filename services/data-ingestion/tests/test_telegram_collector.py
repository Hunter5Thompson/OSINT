"""Tests for Telegram collector core logic."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.telegram_collector import (
    TelegramCollector,
    _dedup_hash,
    _dedup_hash_album,
)


class TestDedupHash:
    def test_single_message_hash(self):
        h = _dedup_hash("OSINTdefender", 12345)
        expected = hashlib.sha256(b"OSINTdefender|12345").hexdigest()
        assert h == expected

    def test_album_hash(self):
        h = _dedup_hash_album("OSINTdefender", 99999)
        expected = hashlib.sha256(b"OSINTdefender|album|99999").hexdigest()
        assert h == expected

    def test_different_channels_different_hash(self):
        h1 = _dedup_hash("chan_a", 1)
        h2 = _dedup_hash("chan_b", 1)
        assert h1 != h2

    def test_hash_is_deterministic(self):
        h1 = _dedup_hash("test", 42)
        h2 = _dedup_hash("test", 42)
        assert h1 == h2


class TestCollectorInit:
    @patch("feeds.telegram_collector._load_channels")
    def test_loads_channels_on_init(self, mock_load):
        mock_load.return_value = []
        mock_redis = AsyncMock()
        collector = TelegramCollector(redis_client=mock_redis)
        mock_load.assert_called_once()
        assert collector._redis is mock_redis


# ── Helpers ──────────────────────────────────────────────────────────


def _make_mock_message(msg_id=1, text="Breaking: Test event", grouped_id=None, has_photo=False):
    """Create a mock Telethon message."""
    msg = MagicMock()
    msg.id = msg_id
    msg.message = text
    msg.grouped_id = grouped_id
    msg.date = datetime(2026, 4, 4, 10, 0, 0, tzinfo=timezone.utc)
    msg.forward = None
    msg.photo = MagicMock() if has_photo else None
    msg.video = None
    msg.document = None
    msg.file = None
    return msg


def _make_settings(**overrides):
    """Create Settings with test-friendly defaults."""
    from config import Settings

    defaults = {
        "neo4j_password": "test",
        "telegram_api_id": 12345,
        "telegram_api_hash": "testhash",
        "telegram_channels_config": "feeds/telegram_channels.yaml",
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ── Redis dedup tests ────────────────────────────────────────────────


class TestDedupRedis:
    async def test_is_duplicate_returns_false_when_not_seen(self):
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._is_duplicate("abc123")
        assert result is False
        mock_redis.exists.assert_called_once_with("telegram:seen:abc123")

    async def test_is_duplicate_returns_true_when_seen(self):
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 1
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._is_duplicate("abc123")
        assert result is True

    async def test_mark_seen_sets_with_ttl(self):
        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        await collector._mark_seen("abc123")
        mock_redis.set.assert_called_once_with(
            "telegram:seen:abc123", "1", ex=604800
        )

    async def test_no_redis_means_no_duplicate(self):
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=None)
        result = await collector._is_duplicate("abc123")
        assert result is False


# ── Last message ID state ────────────────────────────────────────────


class TestLastMessageId:
    async def test_get_returns_none_when_no_state(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._get_last_message_id("test_channel")
        assert result is None

    async def test_get_returns_int(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = b"42"
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._get_last_message_id("test_channel")
        assert result == 42

    async def test_set_stores_msg_id(self):
        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        await collector._set_last_message_id("test_channel", 99)
        mock_redis.set.assert_called_once_with(
            "telegram:last_msg:test_channel", "99"
        )

    async def test_get_returns_none_without_redis(self):
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=None)
        result = await collector._get_last_message_id("test_channel")
        assert result is None


# ── Vision queue tests ───────────────────────────────────────────────


class TestVisionQueue:
    async def test_backpressure_falls_back_to_xlen_on_nogroup(self):
        """If consumer group doesn't exist yet, XPENDING fails — fall back to XLEN."""
        import redis as redis_lib

        mock_redis = AsyncMock()
        mock_redis.xpending.side_effect = redis_lib.ResponseError(
            "NOGROUP No such consumer group 'vision-workers'"
        )
        mock_redis.xlen.return_value = 150  # over threshold
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        status = await collector._maybe_enqueue_vision(ch, 1, "/data/photo.jpg")
        assert status == "deferred"
        mock_redis.xlen.assert_called_once()

    async def test_enqueue_vision_publishes_to_stream(self):
        mock_redis = AsyncMock()
        mock_redis.xpending.return_value = {"pending": 10}  # under threshold
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )
        status = await collector._maybe_enqueue_vision(ch, 123, "/data/photo.jpg")
        assert status == "pending"
        mock_redis.xadd.assert_called_once()

    async def test_backpressure_defers_medium_priority(self):
        mock_redis = AsyncMock()
        mock_redis.xpending.return_value = {"pending": 150}  # over threshold
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        status = await collector._maybe_enqueue_vision(ch, 123, "/data/photo.jpg")
        assert status == "deferred"
        mock_redis.xadd.assert_not_called()

    async def test_backpressure_allows_high_priority(self):
        mock_redis = AsyncMock()
        mock_redis.xpending.return_value = {"pending": 150}  # over threshold
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )
        status = await collector._maybe_enqueue_vision(ch, 123, "/data/photo.jpg")
        assert status == "pending"
        mock_redis.xadd.assert_called_once()

    async def test_no_redis_returns_skipped(self):
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=None)

        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )
        status = await collector._maybe_enqueue_vision(ch, 1, "/data/photo.jpg")
        assert status == "skipped"


# ── Adaptive polling tests ───────────────────────────────────────────


class TestAdaptivePolling:
    async def test_high_priority_always_polls(self):
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )
        assert await collector._should_poll(ch) is True

    async def test_no_redis_always_polls(self):
        from feeds.telegram_models import ChannelConfig

        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=None)

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        assert await collector._should_poll(ch) is True

    async def test_never_polled_channel_polls(self):
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # no last_activity
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        assert await collector._should_poll(ch) is True

    async def test_interval_doubles_on_no_activity(self):
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        mock_redis.get.return_value = "300"  # current interval
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        await collector._update_polling_interval(ch, had_new_messages=False)
        # Should set interval to 600 (300 * 2)
        set_calls = mock_redis.set.call_args_list
        interval_call = [c for c in set_calls if "interval" in str(c)]
        assert any("600" in str(c) for c in interval_call)

    async def test_interval_resets_on_activity(self):
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        mock_redis.get.return_value = "1200"  # current interval (backed off)
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        await collector._update_polling_interval(ch, had_new_messages=True)
        # Should reset interval to base (300)
        set_calls = mock_redis.set.call_args_list
        interval_call = [c for c in set_calls if "interval" in str(c)]
        assert any("300" in str(c) for c in interval_call)

    async def test_interval_capped_at_max(self):
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        mock_redis.get.return_value = "1800"  # already at max
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        await collector._update_polling_interval(ch, had_new_messages=False)
        set_calls = mock_redis.set.call_args_list
        interval_call = [c for c in set_calls if "interval" in str(c)]
        # min(1800*2, 1800) = 1800
        assert any("1800" in str(c) for c in interval_call)

    async def test_high_priority_skips_interval_update(self):
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )
        await collector._update_polling_interval(ch, had_new_messages=False)
        # No Redis calls for high priority
        mock_redis.set.assert_not_called()
        mock_redis.get.assert_not_called()


# ── Contiguous watermark tests ───────────────────────────────────────


class TestContiguousWatermark:
    async def test_watermark_advances_on_success(self):
        """Watermark advances through contiguous successful items."""
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0  # not seen
        mock_redis.get.return_value = None  # no prior watermark

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )

        msg1 = _make_mock_message(msg_id=10, text="Event 1")
        msg2 = _make_mock_message(msg_id=11, text="Event 2")

        mock_client = AsyncMock()
        mock_client.get_entity.return_value = MagicMock()
        mock_client.get_messages.return_value = [msg2, msg1]  # descending

        with patch("feeds.telegram_collector._load_channels", return_value=[ch]):
            collector = TelegramCollector(redis_client=mock_redis)
        collector._client = mock_client

        # Mock the processing methods to succeed
        collector._process_single = AsyncMock(return_value=1)
        collector._embed_and_upsert = AsyncMock(return_value=True)

        count = await collector._fetch_and_process(ch)

        assert count == 2
        # Watermark should be set to 11 (highest successful)
        watermark_calls = [
            c for c in mock_redis.set.call_args_list
            if "last_msg" in str(c)
        ]
        assert len(watermark_calls) == 1
        assert watermark_calls[0] == (("telegram:last_msg:test", "11"),)

    async def test_watermark_freezes_on_failure(self):
        """When processing fails, watermark freezes at last success."""
        from feeds.telegram_models import ChannelConfig

        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0  # not seen
        mock_redis.get.return_value = None  # no prior watermark

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )

        msg1 = _make_mock_message(msg_id=10, text="Event 1")
        msg2 = _make_mock_message(msg_id=11, text="Event 2")  # will fail
        msg3 = _make_mock_message(msg_id=12, text="Event 3")

        mock_client = AsyncMock()
        mock_client.get_entity.return_value = MagicMock()
        mock_client.get_messages.return_value = [msg3, msg2, msg1]

        with patch("feeds.telegram_collector._load_channels", return_value=[ch]):
            collector = TelegramCollector(redis_client=mock_redis)
        collector._client = mock_client

        # msg1 succeeds, msg2 fails, msg3 succeeds
        call_count = 0

        async def mock_process_single(channel, msg, chash):
            nonlocal call_count
            call_count += 1
            if msg.id == 11:
                return 0  # fail
            return 1  # success

        collector._process_single = mock_process_single

        count = await collector._fetch_and_process(ch)

        # count = 2 (msg1 + msg3 succeed)
        assert count == 2
        # Watermark should freeze at 10 (last contiguous success before failure)
        watermark_calls = [
            c for c in mock_redis.set.call_args_list
            if "last_msg" in str(c)
        ]
        assert len(watermark_calls) == 1
        assert watermark_calls[0] == (("telegram:last_msg:test", "10"),)


# ── Media download tests ────────────────────────────────────────────


class TestMediaDownload:
    async def test_skips_oversized_media(self, tmp_path):
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=None)
        collector._settings = _make_settings(telegram_media_path=str(tmp_path))

        msg = MagicMock()
        msg.id = 1
        msg.file = MagicMock()
        msg.file.size = 50_000_000  # 50 MB, over 20 MB limit

        result = await collector._download_media("test_channel", msg)
        assert result is None

    async def test_downloads_media_under_limit(self, tmp_path):
        mock_client = AsyncMock()
        mock_client.download_media.return_value = str(tmp_path / "photo.jpg")

        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=None)
        collector._client = mock_client
        collector._settings = _make_settings(telegram_media_path=str(tmp_path))

        msg = MagicMock()
        msg.id = 1
        msg.file = MagicMock()
        msg.file.size = 1_000_000  # 1 MB, under limit

        result = await collector._download_media("test_channel", msg)
        assert result == str(tmp_path / "photo.jpg")
        mock_client.download_media.assert_called_once()

    async def test_handles_download_failure_gracefully(self, tmp_path):
        mock_client = AsyncMock()
        mock_client.download_media.side_effect = Exception("Network error")

        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=None)
        collector._client = mock_client
        collector._settings = _make_settings(telegram_media_path=str(tmp_path))

        msg = MagicMock()
        msg.id = 1
        msg.file = MagicMock()
        msg.file.size = 1_000_000

        result = await collector._download_media("test_channel", msg)
        assert result is None


# ── Collect entry point tests ────────────────────────────────────────


class TestCollectEntryPoint:
    async def test_collect_skips_adaptive_channels(self):
        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="medium", media=True,
        )
        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[ch]):
            collector = TelegramCollector(redis_client=mock_redis)
        collector._client = AsyncMock()
        collector._should_poll = AsyncMock(return_value=False)
        collector._collect_channel = AsyncMock()

        await collector.collect()

        collector._collect_channel.assert_not_called()

    async def test_collect_handles_channel_error(self):
        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )
        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[ch]):
            collector = TelegramCollector(redis_client=mock_redis)
        collector._client = AsyncMock()
        collector._collect_channel = AsyncMock(side_effect=Exception("API error"))
        collector._update_polling_interval = AsyncMock()

        # Should not raise — errors are caught per-channel
        await collector.collect()

    async def test_collect_auto_connects(self):
        from feeds.telegram_models import ChannelConfig

        ch = ChannelConfig(
            handle="test", name="Test", category="osint",
            source_bias="neutral", language="en", priority="high", media=True,
        )
        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[ch]):
            collector = TelegramCollector(redis_client=mock_redis)
        collector._client = None
        collector._collect_channel = AsyncMock(return_value=0)
        collector._update_polling_interval = AsyncMock()

        with patch.object(collector, "connect", new_callable=AsyncMock) as mock_connect:
            await collector.collect()
            mock_connect.assert_called_once()
