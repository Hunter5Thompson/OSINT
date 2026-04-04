"""Pydantic models for Telegram channel configuration and message payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class ChannelConfig(BaseModel):
    """Single Telegram channel configuration from YAML."""

    handle: str
    name: str
    category: str
    source_bias: Literal[
        "neutral", "pro_russian", "pro_ukrainian", "pro_western", "pro_chinese"
    ]
    language: str
    priority: Literal["high", "medium", "low"]
    media: bool


class ChannelsFile(BaseModel):
    """Root model for telegram_channels.yaml."""

    channels: list[ChannelConfig]

    @field_validator("channels")
    @classmethod
    def channels_not_empty(cls, v: list[ChannelConfig]) -> list[ChannelConfig]:
        if not v:
            raise ValueError("channels list must not be empty")
        return v

    @field_validator("channels")
    @classmethod
    def handles_unique(cls, v: list[ChannelConfig]) -> list[ChannelConfig]:
        handles = [ch.handle for ch in v]
        if len(handles) != len(set(handles)):
            raise ValueError("duplicate channel handles found")
        return v


class TelegramPayload(BaseModel):
    """Qdrant payload schema for a Telegram message."""

    # Standard fields (shared with RSS/GDELT)
    source: Literal["telegram"]
    title: str
    url: str
    published: str
    codebook_type: str = "other.unclassified"
    entities: list[dict] = []
    ingested_at: str = ""

    # Telegram-specific
    telegram_channel: str
    telegram_message_id: int
    source_bias: str
    source_category: str
    forwarded_from: str | None = None
    has_media: bool
    media_paths: list[str]
    media_types: list[str]
    vision_status: Literal["pending", "completed", "skipped", "deferred"]
