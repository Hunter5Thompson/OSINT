"""Tests for Telegram channel config Pydantic models."""

import pytest
from feeds.telegram_models import ChannelConfig, ChannelsFile, TelegramPayload


class TestChannelConfig:
    def test_valid_channel(self):
        ch = ChannelConfig(
            handle="OSINTdefender",
            name="OSINT Defender",
            category="osint",
            source_bias="neutral",
            language="en",
            priority="high",
            media=True,
        )
        assert ch.handle == "OSINTdefender"
        assert ch.priority == "high"

    def test_invalid_bias_rejected(self):
        with pytest.raises(ValueError):
            ChannelConfig(
                handle="test",
                name="Test",
                category="osint",
                source_bias="invalid_bias",
                language="en",
                priority="high",
                media=True,
            )

    def test_invalid_priority_rejected(self):
        with pytest.raises(ValueError):
            ChannelConfig(
                handle="test",
                name="Test",
                category="osint",
                source_bias="neutral",
                language="en",
                priority="urgent",
                media=True,
            )


class TestChannelsFile:
    def test_load_channels_list(self):
        data = {
            "channels": [
                {
                    "handle": "OSINTdefender",
                    "name": "OSINT Defender",
                    "category": "osint",
                    "source_bias": "neutral",
                    "language": "en",
                    "priority": "high",
                    "media": True,
                },
                {
                    "handle": "rybar",
                    "name": "Rybar",
                    "category": "conflict_ukraine",
                    "source_bias": "pro_russian",
                    "language": "en",
                    "priority": "medium",
                    "media": True,
                },
            ]
        }
        cf = ChannelsFile(**data)
        assert len(cf.channels) == 2
        assert cf.channels[0].handle == "OSINTdefender"
        assert cf.channels[1].source_bias == "pro_russian"

    def test_empty_channels_rejected(self):
        with pytest.raises(ValueError):
            ChannelsFile(channels=[])

    def test_duplicate_handles_rejected(self):
        ch = {
            "handle": "dup",
            "name": "Dup",
            "category": "osint",
            "source_bias": "neutral",
            "language": "en",
            "priority": "high",
            "media": True,
        }
        with pytest.raises(ValueError):
            ChannelsFile(channels=[ch, ch])


class TestTelegramPayload:
    def test_minimal_payload(self):
        p = TelegramPayload(
            source="telegram",
            title="Breaking: Event",
            url="https://t.me/OSINTdefender/12345",
            published="2026-04-04T10:00:00Z",
            telegram_channel="OSINTdefender",
            telegram_message_id=12345,
            source_bias="neutral",
            source_category="osint",
            has_media=False,
            media_paths=[],
            media_types=[],
            vision_status="skipped",
        )
        assert p.source == "telegram"
        assert p.forwarded_from is None

    def test_payload_with_media(self):
        p = TelegramPayload(
            source="telegram",
            title="Photo post",
            url="https://t.me/test/1",
            published="2026-04-04T10:00:00Z",
            telegram_channel="test",
            telegram_message_id=1,
            source_bias="neutral",
            source_category="osint",
            has_media=True,
            media_paths=["/data/telegram/media/test/1/photo.jpg"],
            media_types=["photo"],
            vision_status="pending",
            forwarded_from="OriginalChannel",
        )
        assert p.has_media is True
        assert p.forwarded_from == "OriginalChannel"

    def test_invalid_vision_status(self):
        with pytest.raises(ValueError):
            TelegramPayload(
                source="telegram",
                title="X",
                url="https://t.me/x/1",
                published="2026-04-04T10:00:00Z",
                telegram_channel="x",
                telegram_message_id=1,
                source_bias="neutral",
                source_category="osint",
                has_media=False,
                media_paths=[],
                media_types=[],
                vision_status="unknown",
            )


from pathlib import Path
import yaml


class TestChannelYAML:
    def test_yaml_loads_and_validates(self):
        yaml_path = Path(__file__).parent.parent / "feeds" / "telegram_channels.yaml"
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
        cf = ChannelsFile(**raw)
        assert len(cf.channels) >= 6
        handles = [ch.handle for ch in cf.channels]
        assert "OSINTdefender" in handles
        assert "rybar" in handles

    def test_all_channels_have_required_fields(self):
        yaml_path = Path(__file__).parent.parent / "feeds" / "telegram_channels.yaml"
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
        cf = ChannelsFile(**raw)
        for ch in cf.channels:
            assert ch.handle
            assert ch.name
            assert ch.category
            assert ch.language == "en"  # all spec channels are English
