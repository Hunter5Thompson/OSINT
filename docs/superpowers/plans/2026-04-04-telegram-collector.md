# Telegram Collector + Vision Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Telegram channels as a new OSINT source with media download and async vision enrichment via Qwen3-VL-8B.

**Architecture:** Telegram Collector lives inside `data-ingestion` service, using Telethon (MTProto) with adaptive polling. Media images are published to a Redis Stream (`vision:pending`) consumed by a new `vision-enrichment` microservice that runs Qwen3-VL-8B via a dedicated vLLM instance. Both components use the existing `process_item()` pipeline for intelligence extraction.

**Tech Stack:** Telethon 1.36+, cryptg, Redis Streams (consumer groups), vLLM (Qwen3-VL-8B-Instruct), Pydantic v2, httpx, APScheduler

**Spec:** `docs/superpowers/specs/2026-04-04-telegram-collector-design.md`

---

## File Structure

### Data Ingestion Service (modify existing)

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `feeds/telegram_channels.yaml` | Channel configuration (7 channels) |
| Create | `feeds/telegram_models.py` | Pydantic models for channel config + message payload |
| Create | `feeds/telegram_collector.py` | Telethon client, adaptive polling, album grouping, media download, vision queue |
| Modify | `config.py` | Add Telegram + Vision settings fields |
| Modify | `scheduler.py` | Register telegram_collector job |
| Modify | `pyproject.toml` | Add telethon, cryptg dependencies |
| Create | `tests/test_telegram_models.py` | Channel config validation tests |
| Create | `tests/test_telegram_collector.py` | Collector logic tests (mocked Telethon) |

### Vision Enrichment Service (new)

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/vision-enrichment/config.py` | Vision service settings |
| Create | `services/vision-enrichment/consumer.py` | Redis Stream consumer with consumer group |
| Create | `services/vision-enrichment/vision.py` | vLLM Qwen3-VL-8B image analysis |
| Create | `services/vision-enrichment/main.py` | Async entry point |
| Create | `services/vision-enrichment/pyproject.toml` | Dependencies |
| Create | `services/vision-enrichment/Dockerfile` | Container definition |
| Create | `services/vision-enrichment/tests/test_consumer.py` | Consumer logic tests |
| Create | `services/vision-enrichment/tests/test_vision.py` | Vision analysis tests |

### Infrastructure (modify existing)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `docker-compose.yml` | Add vllm-vision + vision-enrichment services, telegram volume |
| Modify | `odin.sh` | Add `telegram` and `vision` subcommands to orchestrator |
| Modify | `.env.example` | Add TELEGRAM_API_ID, TELEGRAM_API_HASH |

---

## Task 1: Feature Branch + Dependencies

**Files:**
- Modify: `services/data-ingestion/pyproject.toml`

- [ ] **Step 1: Create feature branch**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git checkout -b feature/telegram-collector
```

- [ ] **Step 2: Add Telethon + cryptg to dependencies**

In `services/data-ingestion/pyproject.toml`, add to the `dependencies` list:

```toml
dependencies = [
    "httpx>=0.27",
    "apscheduler>=3.10",
    "qdrant-client>=1.9",
    "structlog>=24.1",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "feedparser>=6.0",
    "lxml>=5.1",
    "redis>=5.0",
    "pyyaml>=6.0",
    "telethon>=1.36",
    "cryptg>=0.4",
]
```

- [ ] **Step 3: Install dependencies**

```bash
cd services/data-ingestion && uv sync
```

- [ ] **Step 4: Commit**

```bash
git add services/data-ingestion/pyproject.toml services/data-ingestion/uv.lock
git commit -m "feat(data-ingestion): add telethon + cryptg dependencies for telegram collector"
```

---

## Task 2: Config Extensions

**Files:**
- Modify: `services/data-ingestion/config.py`
- Test: `services/data-ingestion/tests/test_telegram_models.py` (partial — config test)

- [ ] **Step 1: Write config field test**

Create `services/data-ingestion/tests/test_telegram_config.py`:

```python
"""Tests for Telegram + Vision configuration fields."""

from config import Settings


def test_telegram_defaults():
    """Verify Telegram config defaults are sane."""
    s = Settings(neo4j_password="test")
    assert s.telegram_api_id == 0
    assert s.telegram_api_hash == ""
    assert s.telegram_session_path == "/data/telegram/odin"
    assert s.telegram_media_path == "/data/telegram/media"
    assert s.telegram_media_max_size == 20_971_520
    assert s.telegram_channels_config == "feeds/telegram_channels.yaml"
    assert s.telegram_base_interval == 300
    assert s.telegram_max_interval == 1800


def test_vision_defaults():
    """Verify Vision config defaults are sane."""
    s = Settings(neo4j_password="test")
    assert s.vision_vllm_url == "http://localhost:8011"
    assert s.vision_vllm_model == "qwen-vl"
    assert s.vision_queue_name == "vision:pending"
    assert s.vision_queue_max_pending == 100
    assert s.vision_dead_letter_queue == "vision:dead_letter"


def test_telegram_env_override(monkeypatch):
    """Telegram settings are overridable via environment."""
    monkeypatch.setenv("TELEGRAM_API_ID", "99999")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc123")
    monkeypatch.setenv("TELEGRAM_BASE_INTERVAL", "120")
    s = Settings(neo4j_password="test")
    assert s.telegram_api_id == 99999
    assert s.telegram_api_hash == "abc123"
    assert s.telegram_base_interval == 120
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_config.py -v
```

Expected: FAIL — `Settings` has no `telegram_api_id` field.

- [ ] **Step 3: Add config fields**

In `services/data-ingestion/config.py`, add these fields to the `Settings` class after the existing NLM fields:

```python
    # Telegram Collector
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_path: str = "/data/telegram/odin"
    telegram_media_path: str = "/data/telegram/media"
    telegram_media_max_size: int = 20_971_520  # 20 MB
    telegram_channels_config: str = "feeds/telegram_channels.yaml"
    telegram_base_interval: int = 300   # 5 minutes
    telegram_max_interval: int = 1800   # 30 minutes

    # Vision Enrichment
    vision_vllm_url: str = "http://localhost:8011"
    vision_vllm_model: str = "qwen-vl"
    vision_queue_name: str = "vision:pending"
    vision_queue_max_pending: int = 100
    vision_dead_letter_queue: str = "vision:dead_letter"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_config.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/config.py services/data-ingestion/tests/test_telegram_config.py
git commit -m "feat(data-ingestion): add telegram + vision config fields"
```

---

## Task 3: Channel Config Models

**Files:**
- Create: `services/data-ingestion/feeds/telegram_models.py`
- Create: `services/data-ingestion/tests/test_telegram_models.py`

- [ ] **Step 1: Write model validation tests**

Create `services/data-ingestion/tests/test_telegram_models.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_models.py -v
```

Expected: FAIL — module `feeds.telegram_models` not found.

- [ ] **Step 3: Implement models**

Create `services/data-ingestion/feeds/telegram_models.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_models.py -v
```

Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/telegram_models.py services/data-ingestion/tests/test_telegram_models.py
git commit -m "feat(data-ingestion): add telegram channel config + payload pydantic models"
```

---

## Task 4: Channel Config YAML

**Files:**
- Create: `services/data-ingestion/feeds/telegram_channels.yaml`
- Modify: `services/data-ingestion/tests/test_telegram_models.py` (add YAML load test)

- [ ] **Step 1: Write YAML loading test**

Append to `services/data-ingestion/tests/test_telegram_models.py`:

```python
from pathlib import Path
import yaml


class TestChannelYAML:
    def test_yaml_loads_and_validates(self):
        yaml_path = Path(__file__).parent.parent / "feeds" / "telegram_channels.yaml"
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
        cf = ChannelsFile(**raw)
        assert len(cf.channels) >= 7
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_models.py::TestChannelYAML -v
```

Expected: FAIL — FileNotFoundError (YAML doesn't exist yet).

- [ ] **Step 3: Create channel config YAML**

Create `services/data-ingestion/feeds/telegram_channels.yaml`:

```yaml
channels:
  - handle: OSINTdefender
    name: "OSINT Defender"
    category: osint
    source_bias: neutral
    language: en
    priority: high
    media: true

  - handle: AuroraIntel
    name: "Aurora Intel"
    category: osint
    source_bias: neutral
    language: en
    priority: high
    media: true

  - handle: DeepStateEN
    name: "DeepState Map (EN)"
    category: conflict_ukraine
    source_bias: pro_ukrainian
    language: en
    priority: high
    media: true

  - handle: wartranslated
    name: "War Translated"
    category: conflict_ukraine
    source_bias: neutral
    language: en
    priority: medium
    media: false

  - handle: liveuamap
    name: "Liveuamap"
    category: conflict_global
    source_bias: neutral
    language: en
    priority: medium
    media: true

  - handle: CalibreObscura
    name: "Calibre Obscura"
    category: arms_tracking
    source_bias: neutral
    language: en
    priority: medium
    media: true

  - handle: rybar
    name: "Rybar"
    category: conflict_ukraine
    source_bias: pro_russian
    language: en
    priority: medium
    media: true
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_models.py -v
```

Expected: 10 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/telegram_channels.yaml services/data-ingestion/tests/test_telegram_models.py
git commit -m "feat(data-ingestion): add telegram channel config YAML with 7 OSINT channels"
```

---

## Task 5: Telegram Collector — Core Structure + Deduplication

**Files:**
- Create: `services/data-ingestion/feeds/telegram_collector.py`
- Create: `services/data-ingestion/tests/test_telegram_collector.py`

This task implements the collector skeleton: YAML loading, dedup hashing, state tracking keys, and the `collect()` entry point. Telethon calls are mocked.

- [ ] **Step 1: Write dedup + state tests**

Create `services/data-ingestion/tests/test_telegram_collector.py`:

```python
"""Tests for Telegram collector core logic."""

from __future__ import annotations

import hashlib
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_collector.py -v
```

Expected: FAIL — module `feeds.telegram_collector` not found.

- [ ] **Step 3: Implement collector skeleton**

Create `services/data-ingestion/feeds/telegram_collector.py`:

```python
"""Telegram Channel Collector — Telethon-based adaptive poller with media download."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import structlog
import yaml

from config import Settings, settings
from feeds.telegram_models import ChannelConfig, ChannelsFile

log = structlog.get_logger(__name__)


def _dedup_hash(channel_handle: str, message_id: int) -> str:
    """SHA256 hash for single-message deduplication."""
    raw = f"{channel_handle}|{message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _dedup_hash_album(channel_handle: str, grouped_id: int) -> str:
    """SHA256 hash for album (grouped messages) deduplication."""
    raw = f"{channel_handle}|album|{grouped_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_channels(config_path: str | None = None) -> list[ChannelConfig]:
    """Load and validate channel config from YAML."""
    path = Path(config_path or settings.telegram_channels_config)
    if not path.is_absolute():
        path = Path(__file__).parent / path.name
    with open(path) as f:
        raw = yaml.safe_load(f)
    cf = ChannelsFile(**raw)
    return cf.channels


class TelegramCollector:
    """Collect messages from Telegram channels via Telethon."""

    def __init__(
        self,
        redis_client: Any = None,
        settings_override: Settings | None = None,
    ) -> None:
        self._settings = settings_override or settings
        self._redis = redis_client
        self._channels = _load_channels(self._settings.telegram_channels_config)
        self._client = None  # TelegramClient, initialized in connect()

    async def connect(self) -> None:
        """Initialize and connect the Telethon client."""
        from telethon import TelegramClient

        self._client = TelegramClient(
            self._settings.telegram_session_path,
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash,
        )
        await self._client.start()
        log.info("telegram_connected")

    async def disconnect(self) -> None:
        """Disconnect the Telethon client."""
        if self._client:
            await self._client.disconnect()
            log.info("telegram_disconnected")

    async def _is_duplicate(self, content_hash: str) -> bool:
        """Check if message was already processed via Redis."""
        if not self._redis:
            return False
        return await self._redis.exists(f"telegram:seen:{content_hash}") > 0

    async def _mark_seen(self, content_hash: str) -> None:
        """Mark a message hash as seen in Redis (TTL 7 days)."""
        if self._redis:
            await self._redis.set(
                f"telegram:seen:{content_hash}", "1", ex=604800
            )

    async def _get_last_message_id(self, handle: str) -> int | None:
        """Get the last processed message ID for a channel."""
        if not self._redis:
            return None
        val = await self._redis.get(f"telegram:last_msg:{handle}")
        return int(val) if val else None

    async def _set_last_message_id(self, handle: str, msg_id: int) -> None:
        """Store the last processed message ID for a channel."""
        if self._redis:
            await self._redis.set(f"telegram:last_msg:{handle}", str(msg_id))

    async def _should_poll(self, channel: ChannelConfig) -> bool:
        """Adaptive polling: decide if this channel should be polled now."""
        if channel.priority == "high":
            return True
        if not self._redis:
            return True

        last_activity = await self._redis.get(
            f"telegram:last_activity:{channel.handle}"
        )
        if last_activity is None:
            return True  # Never polled — poll now

        import time

        last_ts = float(last_activity)
        elapsed = time.time() - last_ts

        # Get current interval for this channel
        interval_key = f"telegram:interval:{channel.handle}"
        current_interval = await self._redis.get(interval_key)
        current_interval = (
            int(current_interval) if current_interval
            else self._settings.telegram_base_interval
        )

        return elapsed >= current_interval

    async def _update_polling_interval(
        self, channel: ChannelConfig, had_new_messages: bool
    ) -> None:
        """Adjust polling interval based on activity."""
        if channel.priority == "high":
            return  # Always base interval

        if not self._redis:
            return

        interval_key = f"telegram:interval:{channel.handle}"
        current = await self._redis.get(interval_key)
        current = (
            int(current) if current
            else self._settings.telegram_base_interval
        )

        if had_new_messages:
            new_interval = self._settings.telegram_base_interval
        else:
            new_interval = min(current * 2, self._settings.telegram_max_interval)

        await self._redis.set(interval_key, str(new_interval))

        import time

        await self._redis.set(
            f"telegram:last_activity:{channel.handle}",
            str(time.time()),
        )

    async def collect(self) -> None:
        """Main entry point — poll all channels."""
        log.info("telegram_collection_started", channels=len(self._channels))

        if not self._client:
            await self.connect()

        for channel in self._channels:
            if not await self._should_poll(channel):
                log.debug("telegram_channel_skipped_adaptive", handle=channel.handle)
                continue

            try:
                count = await self._collect_channel(channel)
                await self._update_polling_interval(channel, had_new_messages=count > 0)
                if count:
                    log.info(
                        "telegram_channel_collected",
                        handle=channel.handle,
                        new_messages=count,
                    )
            except Exception as e:
                log.error(
                    "telegram_channel_failed",
                    handle=channel.handle,
                    error=str(e),
                )

        log.info("telegram_collection_finished")

    async def _collect_channel(self, channel: ChannelConfig) -> int:
        """Collect new messages from a single channel. Returns count of new items."""
        import asyncio

        try:
            return await asyncio.wait_for(
                self._fetch_and_process(channel),
                timeout=60,
            )
        except asyncio.TimeoutError:
            log.warning("telegram_channel_timeout", handle=channel.handle)
            return 0

    async def _fetch_and_process(self, channel: ChannelConfig) -> int:
        """Fetch messages from Telethon and process them."""
        entity = await self._client.get_entity(channel.handle)
        last_id = await self._get_last_message_id(channel.handle)

        messages = await self._client.get_messages(
            entity,
            limit=50,
            min_id=last_id or 0,
        )

        if not messages:
            return 0

        # Group messages by grouped_id (albums)
        albums: dict[int, list] = {}
        singles: list = []
        for msg in messages:
            if msg.grouped_id:
                albums.setdefault(msg.grouped_id, []).append(msg)
            else:
                singles.append(msg)

        count = 0

        # ── Contiguous watermark ──────────────────────────────────────
        # We process messages in ascending ID order.  The watermark may
        # only advance through a *contiguous* run of succeeded/dedup'd
        # items.  The moment an item fails, the watermark freezes —
        # every subsequent ID stays above it regardless of its own result.
        #
        # Example: IDs [10,11,12,13], 10 ok, 11 fail, 12 ok, 13 ok
        #   → watermark = 10.  Next poll re-fetches 11-13.
        #   → 12+13 hit dedup (already seen), 11 retries.
        #
        # This guarantees zero data loss at the cost of re-checking
        # already-persisted items (cheap: Redis EXISTS).

        # Flatten all items into a single list sorted by message ID so
        # we can walk them in Telegram's chronological order.
        items: list[tuple[int, str, Any]] = []
        # "album" items keyed by grouped_id, carry the album msg list
        for grouped_id, album_msgs in albums.items():
            canonical_id = min(m.id for m in album_msgs)
            chash = _dedup_hash_album(channel.handle, grouped_id)
            items.append((canonical_id, chash, ("album", album_msgs)))
        # "single" items
        for msg in singles:
            if not msg.message and not msg.photo and not msg.video and not msg.document:
                continue  # Skip service messages (joins, pins, etc.)
            chash = _dedup_hash(channel.handle, msg.id)
            items.append((msg.id, chash, ("single", msg)))

        items.sort(key=lambda x: x[0])

        watermark: int | None = await self._get_last_message_id(channel.handle)
        watermark_frozen = False

        for item_id, chash, payload in items:
            if await self._is_duplicate(chash):
                # Already persisted — safe to advance if watermark not frozen
                if not watermark_frozen:
                    watermark = max(watermark or 0, item_id)
                count += 0  # no new item
                continue

            kind, data = payload
            if kind == "album":
                result = await self._process_album(channel, data, chash)
            else:
                result = await self._process_single(channel, data, chash)

            count += result
            if result > 0 and not watermark_frozen:
                watermark = max(watermark or 0, item_id)
            elif result == 0:
                # Persist failed — freeze watermark for the rest of the batch
                watermark_frozen = True

        # Advance last_message_id to the contiguous watermark
        if watermark is not None:
            await self._set_last_message_id(channel.handle, watermark)

        return count

    async def _process_single(
        self, channel: ChannelConfig, msg: Any, content_hash: str
    ) -> int:
        """Process a single (non-album) message."""
        from datetime import timezone

        from pipeline import process_item

        text = msg.message or ""
        title = text.split("\n")[0][:200] if text.strip() else f"{channel.name} #{msg.id}"
        url = f"https://t.me/{channel.handle}/{msg.id}"
        published = msg.date.astimezone(timezone.utc).isoformat()

        # Forwarded message source
        forwarded_from = None
        if msg.forward and msg.forward.chat:
            forwarded_from = getattr(msg.forward.chat, "username", None) or str(
                msg.forward.chat.id
            )

        # Media download
        media_paths: list[str] = []
        media_types: list[str] = []
        if channel.media and msg.photo:
            path = await self._download_media(channel.handle, msg)
            if path:
                media_paths.append(path)
                media_types.append("photo")
        elif channel.media and msg.video:
            path = await self._download_media(channel.handle, msg)
            if path:
                media_paths.append(path)
                media_types.append("video")
        elif channel.media and msg.document:
            path = await self._download_media(channel.handle, msg)
            if path:
                media_paths.append(path)
                media_types.append("document")

        has_media = len(media_paths) > 0

        # Determine vision status
        vision_status = "skipped"
        if has_media and "photo" in media_types:
            vision_status = await self._maybe_enqueue_vision(
                channel, msg.id, media_paths[0]
            )

        # Intelligence extraction via existing pipeline
        enrichment = await process_item(
            title=title,
            text=text,
            url=url,
            source="telegram",
            settings=self._settings,
            redis_client=self._redis,
        )

        # Embed and upsert to Qdrant — only mark seen if persisted
        persisted = await self._embed_and_upsert(
            content_hash=content_hash,
            title=title,
            text=text,
            url=url,
            published=published,
            channel=channel,
            message_id=msg.id,
            forwarded_from=forwarded_from,
            has_media=has_media,
            media_paths=media_paths,
            media_types=media_types,
            vision_status=vision_status,
            enrichment=enrichment,
        )

        if persisted:
            await self._mark_seen(content_hash)
        return 1 if persisted else 0

    async def _process_album(
        self, channel: ChannelConfig, msgs: list, content_hash: str
    ) -> int:
        """Process a group of messages (Telegram album)."""
        from datetime import timezone

        from pipeline import process_item

        # Concatenate text from all messages in the album
        texts = [m.message for m in msgs if m.message]
        text = "\n".join(texts)
        title = text.split("\n")[0][:200] if text else channel.name
        canonical_msg = min(msgs, key=lambda m: m.id)
        url = f"https://t.me/{channel.handle}/{canonical_msg.id}"
        published = canonical_msg.date.astimezone(timezone.utc).isoformat()

        # Forwarded source from first message
        forwarded_from = None
        if canonical_msg.forward and canonical_msg.forward.chat:
            forwarded_from = getattr(
                canonical_msg.forward.chat, "username", None
            ) or str(canonical_msg.forward.chat.id)

        # Download all media from album
        media_paths: list[str] = []
        media_types: list[str] = []
        if channel.media:
            for m in msgs:
                if m.photo:
                    path = await self._download_media(channel.handle, m)
                    if path:
                        media_paths.append(path)
                        media_types.append("photo")
                elif m.video:
                    path = await self._download_media(channel.handle, m)
                    if path:
                        media_paths.append(path)
                        media_types.append("video")

        has_media = len(media_paths) > 0

        # Enqueue only photos for vision
        vision_status = "skipped"
        for path, mtype in zip(media_paths, media_types):
            if mtype == "photo":
                vision_status = await self._maybe_enqueue_vision(
                    channel, canonical_msg.id, path
                )

        enrichment = await process_item(
            title=title,
            text=text,
            url=url,
            source="telegram",
            settings=self._settings,
            redis_client=self._redis,
        )

        persisted = await self._embed_and_upsert(
            content_hash=content_hash,
            title=title,
            text=text,
            url=url,
            published=published,
            channel=channel,
            message_id=canonical_msg.id,
            forwarded_from=forwarded_from,
            has_media=has_media,
            media_paths=media_paths,
            media_types=media_types,
            vision_status=vision_status,
            enrichment=enrichment,
        )

        if persisted:
            await self._mark_seen(content_hash)
        return 1 if persisted else 0

    async def _download_media(self, channel_handle: str, msg: Any) -> str | None:
        """Download media from a message. Returns local path or None."""
        media_dir = Path(self._settings.telegram_media_path) / channel_handle / str(msg.id)
        media_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Check file size before download
            if msg.file and msg.file.size and msg.file.size > self._settings.telegram_media_max_size:
                log.warning(
                    "telegram_media_too_large",
                    handle=channel_handle,
                    msg_id=msg.id,
                    size=msg.file.size,
                )
                return None

            path = await self._client.download_media(
                msg,
                file=str(media_dir) + "/",
            )
            return path
        except Exception as e:
            log.warning(
                "telegram_media_download_failed",
                handle=channel_handle,
                msg_id=msg.id,
                error=str(e),
            )
            return None

    async def _maybe_enqueue_vision(
        self, channel: ChannelConfig, message_id: int, media_path: str
    ) -> str:
        """Publish image to vision:pending queue with backpressure check.

        Returns vision_status: 'pending', 'deferred', or 'skipped'.
        """
        if not self._redis:
            return "skipped"

        # Backpressure check — prefer pending count (unacked) over stream
        # length. XPENDING requires the consumer group to exist; if the
        # vision-enrichment service hasn't started yet (group not created),
        # fall back to XLEN as a conservative upper bound.
        try:
            pending_info = await self._redis.xpending(
                self._settings.vision_queue_name,
                self._settings.vision_consumer_group,
            )
            pending_count = (
                pending_info["pending"]
                if isinstance(pending_info, dict)
                else (pending_info[0] if pending_info else 0)
            )
        except Exception:
            # NOGROUP or connection issue — fall back to stream length
            pending_count = await self._redis.xlen(
                self._settings.vision_queue_name
            )
        if pending_count > self._settings.vision_queue_max_pending:
            if channel.priority != "high":
                return "deferred"

        await self._redis.xadd(
            self._settings.vision_queue_name,
            {
                "channel": channel.handle,
                "message_id": str(message_id),
                "media_path": media_path,
                "source_bias": channel.source_bias,
                "source": "telegram",
                "url": f"https://t.me/{channel.handle}/{message_id}",
            },
        )
        return "pending"

    async def _embed_and_upsert(
        self,
        *,
        content_hash: str,
        title: str,
        text: str,
        url: str,
        published: str,
        channel: ChannelConfig,
        message_id: int,
        forwarded_from: str | None,
        has_media: bool,
        media_paths: list[str],
        media_types: list[str],
        vision_status: str,
        enrichment: dict | None,
    ) -> bool:
        """Embed text and upsert to Qdrant. Returns True on success, False on failure."""
        from datetime import datetime, timezone

        import httpx
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct

        embed_text = f"{title}\n{text}"[:2000]

        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout) as client:
                resp = await client.post(
                    f"{self._settings.tei_embed_url}/embed",
                    json={"inputs": embed_text},
                )
                resp.raise_for_status()
                result = resp.json()
                vector = result[0] if isinstance(result[0], list) else result
        except Exception as e:
            log.warning("telegram_embedding_failed", url=url, error=str(e))
            return False

        point_id = int(content_hash[:16], 16)

        payload = {
            "source": "telegram",
            "title": title,
            "url": url,
            "published": published,
            "content_hash": content_hash,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "codebook_type": enrichment["codebook_type"] if enrichment else "other.unclassified",
            "entities": enrichment["entities"] if enrichment else [],
            "telegram_channel": channel.handle,
            "telegram_message_id": message_id,
            "source_bias": channel.source_bias,
            "source_category": channel.category,
            "forwarded_from": forwarded_from,
            "has_media": has_media,
            "media_paths": media_paths,
            "media_types": media_types,
            "vision_status": vision_status,
        }

        qdrant = QdrantClient(url=self._settings.qdrant_url)
        qdrant.upsert(
            collection_name=self._settings.qdrant_collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_collector.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/feeds/telegram_collector.py services/data-ingestion/tests/test_telegram_collector.py
git commit -m "feat(data-ingestion): add telegram collector with dedup, adaptive polling, media download"
```

---

## Task 6: Telegram Collector — Message Processing Tests

**Files:**
- Modify: `services/data-ingestion/tests/test_telegram_collector.py`

This task adds comprehensive mocked tests for the message processing pipeline.

- [ ] **Step 1: Add single message processing test**

Append to `services/data-ingestion/tests/test_telegram_collector.py`:

```python
from datetime import datetime, timezone
from unittest.mock import PropertyMock


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


class TestDedupRedis:
    @pytest.mark.asyncio
    async def test_is_duplicate_returns_false_when_not_seen(self):
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._is_duplicate("abc123")
        assert result is False
        mock_redis.exists.assert_called_once_with("telegram:seen:abc123")

    @pytest.mark.asyncio
    async def test_is_duplicate_returns_true_when_seen(self):
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 1
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._is_duplicate("abc123")
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_seen_sets_with_ttl(self):
        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        await collector._mark_seen("abc123")
        mock_redis.set.assert_called_once_with(
            "telegram:seen:abc123", "1", ex=604800
        )


class TestLastMessageId:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_no_state(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._get_last_message_id("test_channel")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_int(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = b"42"
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        result = await collector._get_last_message_id("test_channel")
        assert result == 42

    @pytest.mark.asyncio
    async def test_set_stores_msg_id(self):
        mock_redis = AsyncMock()
        with patch("feeds.telegram_collector._load_channels", return_value=[]):
            collector = TelegramCollector(redis_client=mock_redis)
        await collector._set_last_message_id("test_channel", 99)
        mock_redis.set.assert_called_once_with(
            "telegram:last_msg:test_channel", "99"
        )


class TestVisionQueue:
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
```

- [ ] **Step 2: Run tests**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_collector.py -v
```

Expected: 14 PASSED

- [ ] **Step 3: Commit**

```bash
git add services/data-ingestion/tests/test_telegram_collector.py
git commit -m "test(data-ingestion): add telegram collector redis + vision queue tests"
```

---

## Task 7: Scheduler Integration

**Files:**
- Modify: `services/data-ingestion/scheduler.py`

- [ ] **Step 1: Write scheduler test**

Append to `services/data-ingestion/tests/test_telegram_collector.py`:

```python
class TestSchedulerIntegration:
    def test_telegram_job_registered(self):
        """Verify the telegram collector job is in the scheduler."""
        from scheduler import create_scheduler
        scheduler = create_scheduler()
        job_ids = [j.id for j in scheduler.get_jobs()]
        assert "telegram_collector" in job_ids

    def test_telegram_job_interval_5_min(self):
        from scheduler import create_scheduler
        scheduler = create_scheduler()
        job = scheduler.get_job("telegram_collector")
        assert job is not None
        # IntervalTrigger stores interval as timedelta
        assert job.trigger.interval.total_seconds() == 300
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_collector.py::TestSchedulerIntegration -v
```

Expected: FAIL — `telegram_collector` job not in scheduler.

- [ ] **Step 3: Add telegram job to scheduler**

In `services/data-ingestion/scheduler.py`:

Add import at top (after existing collector imports):

```python
from feeds.telegram_collector import TelegramCollector
```

Add job wrapper function (after `run_hotspot_updater`):

```python
async def run_telegram_collector() -> None:
    """Collect Telegram channel messages."""
    collector = TelegramCollector(redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("telegram_job_failed")
    finally:
        await collector.disconnect()
```

Add job registration inside `create_scheduler()` (after hotspot job):

```python
    # Telegram channels — every 5 minutes (adaptive internally)
    scheduler.add_job(
        run_telegram_collector,
        trigger=IntervalTrigger(minutes=5),
        id="telegram_collector",
        name="Telegram Channel Collector",
        replace_existing=True,
    )
```

Add to initial tasks in `main()` (add to the `initial_tasks` list):

```python
        run_telegram_collector(),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_collector.py::TestSchedulerIntegration -v
```

Expected: 2 PASSED

- [ ] **Step 5: Run all existing tests to verify no regressions**

```bash
cd services/data-ingestion && uv run pytest tests/ -v --ignore=tests/test_nlm_cli.py --ignore=tests/test_nlm_transcribe.py
```

Expected: All pass (NLM CLI/transcribe tests may need optional deps — ignore if not installed).

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/scheduler.py services/data-ingestion/tests/test_telegram_collector.py
git commit -m "feat(data-ingestion): register telegram collector in APScheduler (5min interval)"
```

---

## Task 8: Vision Enrichment Service — Project Scaffold

**Files:**
- Create: `services/vision-enrichment/pyproject.toml`
- Create: `services/vision-enrichment/config.py`
- Create: `services/vision-enrichment/Dockerfile`
- Create: `services/vision-enrichment/tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p services/vision-enrichment/tests
```

- [ ] **Step 2: Create pyproject.toml**

Create `services/vision-enrichment/pyproject.toml`:

```toml
[project]
name = "worldview-vision-enrichment"
version = "0.1.0"
description = "Vision enrichment service for WorldView — analyses OSINT images via Qwen3-VL-8B"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "redis>=5.0",
    "structlog>=24.1",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "qdrant-client>=1.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM"]
```

- [ ] **Step 3: Create config.py**

Create `services/vision-enrichment/config.py`:

```python
"""Configuration for the Vision Enrichment service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Vision service settings — all values from env vars or .env."""

    redis_url: str = "redis://localhost:6379/0"
    vision_vllm_url: str = "http://localhost:8011/v1"
    vision_vllm_model: str = "qwen-vl"

    # Queue settings
    vision_queue_name: str = "vision:pending"
    vision_consumer_group: str = "vision-workers"
    vision_consumer_name: str = "worker-1"
    vision_dead_letter_queue: str = "vision:dead_letter"
    vision_max_retries: int = 3
    vision_idle_timeout_ms: int = 600_000  # 10 min for XAUTOCLAIM

    # Neo4j (for updating Document nodes)
    neo4j_url: str = "http://localhost:7474"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Qdrant (for updating payloads)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "odin_intel"

    # Redis Streams (enriched events)
    redis_stream_enriched: str = "events:enriched"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 4: Create Dockerfile**

Create `services/vision-enrichment/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv sync --no-dev

COPY . .

CMD ["uv", "run", "python", "main.py"]
```

- [ ] **Step 5: Create empty test init**

Create `services/vision-enrichment/tests/__init__.py` (empty file).

- [ ] **Step 6: Commit**

```bash
git add services/vision-enrichment/
git commit -m "feat(vision-enrichment): scaffold project with config, Dockerfile, pyproject"
```

---

## Task 9: Vision Enrichment — Image Analysis

**Files:**
- Create: `services/vision-enrichment/vision.py`
- Create: `services/vision-enrichment/tests/test_vision.py`

- [ ] **Step 1: Write vision analysis test**

Create `services/vision-enrichment/tests/test_vision.py`:

```python
"""Tests for vision image analysis via vLLM."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from vision import analyze_image


_DUMMY_REQUEST = httpx.Request("POST", "http://localhost:8011/v1/chat/completions")


class TestAnalyzeImage:
    @pytest.mark.asyncio
    async def test_returns_parsed_json(self):
        vision_result = {
            "scene_description": "Military convoy on highway",
            "visible_text": "Z marking on vehicle",
            "military_equipment": ["T-72B3 tank", "BMP-2"],
            "location_indicators": ["Road sign in Cyrillic"],
            "map_annotations": [],
            "damage_assessment": "No visible damage",
        }
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(vision_result)}}
                ]
            },
            request=_DUMMY_REQUEST,
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_response

        result = await analyze_image(
            client=mock_client,
            vllm_url="http://localhost:8011/v1",
            model="qwen-vl",
            image_path="/data/telegram/media/test/1/photo.jpg",
        )

        assert result["scene_description"] == "Military convoy on highway"
        assert "T-72B3 tank" in result["military_equipment"]
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "500", request=_DUMMY_REQUEST, response=httpx.Response(500, request=_DUMMY_REQUEST)
        )

        result = await analyze_image(
            client=mock_client,
            vllm_url="http://localhost:8011/v1",
            model="qwen-vl",
            image_path="/data/photo.jpg",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_sends_base64_image(self):
        """Verify the image is sent as base64 in the request payload."""
        mock_response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
            request=_DUMMY_REQUEST,
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_response

        # Create a tiny test image file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # minimal JPEG header
            tmp_path = f.name

        await analyze_image(
            client=mock_client,
            vllm_url="http://localhost:8011/v1",
            model="qwen-vl",
            image_path=tmp_path,
        )

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        messages = payload["messages"]
        user_msg = messages[1]
        # Should have image_url content type
        assert any(
            c.get("type") == "image_url"
            for c in user_msg["content"]
            if isinstance(c, dict)
        )

        import os
        os.unlink(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/vision-enrichment && uv sync && uv run pytest tests/test_vision.py -v
```

Expected: FAIL — `vision` module not found.

- [ ] **Step 3: Implement vision analysis**

Create `services/vision-enrichment/vision.py`:

```python
"""Image analysis via vLLM Qwen3-VL-8B."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import structlog

log = structlog.get_logger(__name__)

VISION_PROMPT = """\
Analyze this image from a geopolitical/military OSINT context.
Extract:
- scene_description: What is shown in the image
- visible_text: Any text, labels, watermarks visible
- military_equipment: Equipment types if identifiable (e.g., "T-72B3 tank", "HIMARS launcher")
- location_indicators: Any clues about location (signs, terrain, landmarks)
- map_annotations: If satellite/map image — marked areas, arrows, labels
- damage_assessment: If applicable — infrastructure damage, impact craters
Output as JSON."""


async def analyze_image(
    *,
    client: httpx.AsyncClient,
    vllm_url: str,
    model: str,
    image_path: str,
) -> dict | None:
    """Analyze an image via vLLM vision model. Returns parsed JSON dict or None on failure."""
    try:
        image_data = Path(image_path).read_bytes()
        b64 = base64.b64encode(image_data).decode("utf-8")
    except (FileNotFoundError, PermissionError) as e:
        log.error("vision_image_read_failed", path=image_path, error=str(e))
        return None

    # Determine MIME type from extension
    suffix = Path(image_path).suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        suffix, "image/jpeg"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an OSINT image analyst. Output valid JSON only."},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": VISION_PROMPT},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
    }

    try:
        resp = await client.post(f"{vllm_url}/chat/completions", json=payload, timeout=60.0)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
        log.error("vision_analysis_failed", path=image_path, error=str(e))
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/vision-enrichment && uv run pytest tests/test_vision.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/vision-enrichment/vision.py services/vision-enrichment/tests/test_vision.py
git commit -m "feat(vision-enrichment): add vLLM Qwen3-VL image analysis with OSINT prompt"
```

---

## Task 10: Vision Enrichment — Redis Stream Consumer

**Files:**
- Create: `services/vision-enrichment/consumer.py`
- Create: `services/vision-enrichment/tests/test_consumer.py`

- [ ] **Step 1: Write consumer tests**

Create `services/vision-enrichment/tests/test_consumer.py`:

```python
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
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_ensure_group_ignores_busygroup(self):
        """If group already exists, should not raise."""
        import redis as redis_lib
        consumer, mock_redis = _make_consumer()
        mock_redis.xgroup_create.side_effect = redis_lib.ResponseError("BUSYGROUP")
        await consumer.ensure_consumer_group()  # should not raise


class TestProcessMessage:
    @pytest.mark.asyncio
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

        with patch("consumer.analyze_image", return_value=mock_vision_result) as mock_analyze, \
             patch("consumer.httpx.AsyncClient") as MockClient, \
             patch("consumer.QdrantClient") as MockQdrant:
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

            mock_analyze.assert_called_once()
            # Should update Qdrant payload
            mock_qdrant_instance.set_payload.assert_called_once()
            set_payload_kwargs = mock_qdrant_instance.set_payload.call_args
            assert "vision_description" in set_payload_kwargs.kwargs.get("payload", set_payload_kwargs[1].get("payload", {}))
            # Should ACK the message
            mock_redis.xack.assert_called_once()

    @pytest.mark.asyncio
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

        with patch("consumer.analyze_image", return_value={"scene_description": "test"}), \
             patch("consumer.httpx.AsyncClient") as MockClient:
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

        # Should NOT ACK because Neo4j had errors — will retry
        # (hincrby was called for retry tracking, but count=1 < max_retries=3)
        assert mock_redis.xack.call_count == 0


class TestPoisonMessages:
    @pytest.mark.asyncio
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

        # Simulate 3 retries tracked in Redis
        mock_redis.hincrby.return_value = 4  # exceeded max

        with patch("consumer.analyze_image", side_effect=Exception("GPU OOM")):
            await consumer._process_message(b"msg-id-1", msg_data)

        # Should XADD to dead letter queue and XACK
        mock_redis.xadd.assert_called_once()
        xadd_args = mock_redis.xadd.call_args
        assert xadd_args[0][0] == "vision:dead_letter"
        mock_redis.xack.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/vision-enrichment && uv run pytest tests/test_consumer.py -v
```

Expected: FAIL — `consumer` module not found.

- [ ] **Step 3: Implement consumer**

Create `services/vision-enrichment/consumer.py`:

```python
"""Redis Stream consumer for vision enrichment."""

from __future__ import annotations

import json
from typing import Any

import httpx
import redis as redis_lib
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import Settings, settings
from vision import analyze_image

log = structlog.get_logger(__name__)


class VisionConsumer:
    """Consume images from vision:pending, analyze, and update Neo4j + Qdrant."""

    def __init__(
        self,
        redis_client: Any,
        settings_override: Settings | None = None,
    ) -> None:
        self._redis = redis_client
        self._settings = settings_override or settings

    async def ensure_consumer_group(self) -> None:
        """Create the consumer group if it doesn't exist."""
        try:
            await self._redis.xgroup_create(
                self._settings.vision_queue_name,
                self._settings.vision_consumer_group,
                id="0",
                mkstream=True,
            )
            log.info("vision_consumer_group_created")
        except redis_lib.ResponseError as e:
            if "BUSYGROUP" in str(e):
                log.debug("vision_consumer_group_exists")
            else:
                raise

    async def run(self) -> None:
        """Main consumer loop — read from stream and process."""
        await self.ensure_consumer_group()
        log.info("vision_consumer_started")

        while True:
            try:
                # Read new messages
                entries = await self._redis.xreadgroup(
                    self._settings.vision_consumer_group,
                    self._settings.vision_consumer_name,
                    {self._settings.vision_queue_name: ">"},
                    count=5,
                    block=5000,
                )

                if entries:
                    for stream_name, messages in entries:
                        for msg_id, msg_data in messages:
                            await self._process_message(msg_id, msg_data)

                # Claim idle messages from other consumers
                claimed = await self._redis.xautoclaim(
                    self._settings.vision_queue_name,
                    self._settings.vision_consumer_group,
                    self._settings.vision_consumer_name,
                    min_idle_time=self._settings.vision_idle_timeout_ms,
                    count=3,
                )
                if claimed and claimed[1]:
                    for msg_id, msg_data in claimed[1]:
                        if msg_data:
                            await self._process_message(msg_id, msg_data)

            except Exception:
                log.exception("vision_consumer_loop_error")
                import asyncio
                await asyncio.sleep(5)

    async def _process_message(self, msg_id: bytes, msg_data: dict) -> None:
        """Process a single vision queue entry."""
        url = msg_data.get(b"url", b"").decode()
        media_path = msg_data.get(b"media_path", b"").decode()
        channel = msg_data.get(b"channel", b"").decode()

        try:
            async with httpx.AsyncClient() as http_client:
                result = await analyze_image(
                    client=http_client,
                    vllm_url=self._settings.vision_vllm_url,
                    model=self._settings.vision_vllm_model,
                    image_path=media_path,
                )

            if result is None:
                raise Exception(f"Vision analysis returned None for {media_path}")

            vision_description = json.dumps(result)

            # Update Neo4j: SET vision_description on Document node
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                resp = await http_client.post(
                    f"{self._settings.neo4j_url}/db/neo4j/tx/commit",
                    json={
                        "statements": [
                            {
                                "statement": (
                                    "MATCH (d:Document {url: $url}) "
                                    "SET d.vision_description = $desc, "
                                    "d.vision_status = 'completed'"
                                ),
                                "parameters": {"url": url, "desc": vision_description},
                            }
                        ]
                    },
                    auth=(self._settings.neo4j_user, self._settings.neo4j_password),
                )
                resp.raise_for_status()
                neo4j_errors = resp.json().get("errors", [])
                if neo4j_errors:
                    raise Exception(f"Neo4j write errors: {neo4j_errors}")

            # Update Qdrant: set vision_description + vision_status on payload
            qdrant = QdrantClient(url=self._settings.qdrant_url)
            hits = qdrant.scroll(
                collection_name=self._settings.qdrant_collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="url", match=MatchValue(value=url))]
                ),
                limit=1,
            )
            if hits and hits[0]:
                point = hits[0][0]
                qdrant.set_payload(
                    collection_name=self._settings.qdrant_collection,
                    payload={
                        "vision_description": vision_description,
                        "vision_status": "completed",
                    },
                    points=[point.id],
                )

            # Publish enriched event
            await self._redis.xadd(
                self._settings.redis_stream_enriched,
                {
                    "url": url,
                    "channel": channel,
                    "vision_status": "completed",
                },
            )

            # ACK only after successful persistence
            await self._redis.xack(
                self._settings.vision_queue_name,
                self._settings.vision_consumer_group,
                msg_id,
            )
            log.info("vision_processed", url=url, channel=channel)

        except Exception as e:
            log.error("vision_processing_failed", url=url, error=str(e))

            # Track retries
            retry_key = f"vision:retries:{msg_id}"
            retry_count = await self._redis.hincrby(retry_key, "count", 1)

            if retry_count > self._settings.vision_max_retries:
                # Dead letter
                await self._redis.xadd(
                    self._settings.vision_dead_letter_queue,
                    {
                        **{k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in msg_data.items()},
                        "error": str(e),
                        "retries": str(retry_count),
                    },
                )
                await self._redis.xack(
                    self._settings.vision_queue_name,
                    self._settings.vision_consumer_group,
                    msg_id,
                )
                await self._redis.delete(retry_key)
                log.warning("vision_dead_letter", url=url, retries=retry_count)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/vision-enrichment && uv run pytest tests/test_consumer.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/vision-enrichment/consumer.py services/vision-enrichment/tests/test_consumer.py
git commit -m "feat(vision-enrichment): add redis stream consumer with dead letter + retries"
```

---

## Task 11: Vision Enrichment — Main Entry Point

**Files:**
- Create: `services/vision-enrichment/main.py`

- [ ] **Step 1: Create main.py**

Create `services/vision-enrichment/main.py`:

```python
"""Vision Enrichment Service — main entry point."""

from __future__ import annotations

import asyncio
import signal

import redis.asyncio as aioredis
import structlog

from config import settings
from consumer import VisionConsumer

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("vision-enrichment")


async def main() -> None:
    """Start the vision enrichment consumer."""
    log.info("vision_service_starting")

    redis_client = aioredis.from_url(settings.redis_url)
    consumer = VisionConsumer(redis_client=redis_client)

    shutdown_event = asyncio.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        log.info("signal_received", signal=signal.Signals(signum).name)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    consumer_task = asyncio.create_task(consumer.run())

    # Wait for shutdown signal
    await shutdown_event.wait()

    log.info("vision_service_shutting_down")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
    log.info("vision_service_stopped")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add services/vision-enrichment/main.py
git commit -m "feat(vision-enrichment): add async main entry point with graceful shutdown"
```

---

## Task 12: Docker Compose + odin.sh Integration

**Files:**
- Modify: `docker-compose.yml`
- Modify: `odin.sh`
- Modify: `.env.example`

- [ ] **Step 1: Add Telegram env vars to .env.example**

Append to `.env.example`:

```bash
# Telegram Collector
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# Vision Enrichment (Qwen3-VL-8B)
VISION_VLLM_MODEL=qwen-vl
```

- [ ] **Step 2: Add telegram volume + env to data-ingestion in docker-compose.yml**

In the `data-ingestion` service, add the telegram volume mount and env vars:

Under `volumes:` (or add if not present):
```yaml
    volumes:
      - ${ODIN_DATA_DIR:-${HOME}/ODIN/odin-data}/telegram:/data/telegram
```

Under `environment:` add:
```yaml
      - TELEGRAM_API_ID=${TELEGRAM_API_ID:-0}
      - TELEGRAM_API_HASH=${TELEGRAM_API_HASH:-}
```

- [ ] **Step 3: Add vllm-vision service to docker-compose.yml**

Add after the existing vllm services:

```yaml
  vllm-vision:
    image: vllm/vllm-openai:latest
    profiles: ["vision"]
    ports:
      - "8011:8000"
    volumes:
      - ${HF_HOME:-${HOME}/.cache/huggingface}:/root/.cache/huggingface
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - HF_TOKEN=${HF_TOKEN:-}
    command: >
      --model Qwen/Qwen3-VL-8B-Instruct
      --served-model-name qwen-vl
      --max-model-len 4096
      --gpu-memory-utilization 0.40
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 20
      start_period: 120s
    restart: unless-stopped
```

- [ ] **Step 4: Add vision-enrichment service to docker-compose.yml**

```yaml
  vision-enrichment:
    build:
      context: ./services/vision-enrichment
      dockerfile: Dockerfile
    profiles: ["vision"]
    volumes:
      - ${ODIN_DATA_DIR:-${HOME}/ODIN/odin-data}/telegram/media:/data/telegram/media:ro
    environment:
      - VISION_VLLM_URL=http://vllm-vision:8000/v1
      - VISION_VLLM_MODEL=${VISION_VLLM_MODEL:-qwen-vl}
      - REDIS_URL=redis://redis:6379/0
      - NEO4J_URL=http://neo4j:7474
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD:-odin1234}
      - QDRANT_URL=http://qdrant:6333
    depends_on:
      redis:
        condition: service_healthy
      vllm-vision:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 5: Update odin.sh with vision subcommand**

Add `VISION_SERVICES` array near the top (after `INTERACTIVE_SERVICES`):

```bash
VISION_SERVICES=(vllm-vision vision-enrichment)
```

Add `telegram` and `vision` subcommand handlers in the case statement:

```bash
    telegram)
        case "${2:-}" in
            up)
                echo "Starting Telegram-enabled ingestion..."
                "${COMPOSE[@]}" --profile ingestion up -d "${INGESTION_SERVICES[@]}"
                echo "Telegram collector runs inside data-ingestion (check TELEGRAM_API_ID is set)."
                ;;
            down)
                echo "Stopping ingestion services..."
                "${COMPOSE[@]}" stop "${INGESTION_SERVICES[@]}"
                ;;
            *)
                echo "Usage: odin telegram up|down"
                exit 1
                ;;
        esac
        ;;
    vision)
        case "${2:-}" in
            up)
                echo "Starting Vision Enrichment services..."
                "${COMPOSE[@]}" --profile vision up -d "${VISION_SERVICES[@]}"
                ;;
            down)
                echo "Stopping Vision Enrichment services..."
                "${COMPOSE[@]}" stop "${VISION_SERVICES[@]}"
                ;;
            *)
                echo "Usage: odin vision up|down"
                exit 1
                ;;
        esac
        ;;
```

Add vision checks to the `doctor` subcommand:

```bash
        # Vision model (optional)
        if [ -d "${HF_HOME:-${HOME}/.cache/huggingface}" ]; then
            ok "HuggingFace cache directory exists"
        else
            warn "HuggingFace cache directory not found (needed for Vision model download)"
        fi
```

Add vision checks to the `smoke` subcommand:

```bash
        # Vision services (if running)
        if docker compose ps --format json 2>/dev/null | grep -q "vllm-vision"; then
            check "vllm-vision health" curl -sf http://localhost:8011/health
            check "vision-enrichment running" docker compose ps --format '{{.State}}' vision-enrichment 2>/dev/null | grep -q running
        fi
```

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml odin.sh .env.example
git commit -m "feat(infra): add vllm-vision + vision-enrichment services, telegram volume mounts"
```

---

## Task 13: Hatch Build Include + Final Wiring

**Files:**
- Modify: `services/data-ingestion/pyproject.toml` (include new files in wheel)

- [ ] **Step 1: Update hatch build includes**

In `services/data-ingestion/pyproject.toml`, update the wheel includes:

```toml
[tool.hatch.build.targets.wheel]
include = ["*.py", "feeds/**/*.py", "feeds/**/*.yaml", "nlm_ingest/**/*.py", "nlm_ingest/prompts/*.txt"]
```

Note: added `"feeds/**/*.yaml"` to include `telegram_channels.yaml` in the wheel.

- [ ] **Step 2: Verify all data-ingestion tests pass**

```bash
cd services/data-ingestion && uv run pytest tests/test_telegram_config.py tests/test_telegram_models.py tests/test_telegram_collector.py tests/test_feeds.py tests/test_pipeline.py -v
```

Expected: All pass.

- [ ] **Step 3: Verify all vision-enrichment tests pass**

```bash
cd services/vision-enrichment && uv run pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 4: Lint both services**

```bash
cd services/data-ingestion && uv run ruff check .
cd services/vision-enrichment && uv run ruff check .
```

Expected: No errors or only pre-existing warnings.

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/pyproject.toml
git commit -m "chore(data-ingestion): include telegram YAML in wheel build"
```

---

## Task 14: Final Integration Verification

- [ ] **Step 1: Run full test suite for data-ingestion**

```bash
cd services/data-ingestion && uv run pytest tests/ -v
```

Document pass/fail count.

- [ ] **Step 2: Run full test suite for vision-enrichment**

```bash
cd services/vision-enrichment && uv run pytest tests/ -v
```

Document pass/fail count.

- [ ] **Step 3: Verify docker compose config is valid**

```bash
cd /home/deadpool-ultra/ODIN/OSINT && docker compose config --quiet
```

Expected: No errors.

- [ ] **Step 4: Verify branch is clean and complete**

```bash
git status
git log --oneline feature/telegram-collector ^main
```

Document all commits.
