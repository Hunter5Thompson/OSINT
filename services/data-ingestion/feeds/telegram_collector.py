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
        except TimeoutError:
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
        import datetime

        from pipeline import process_item

        text = msg.message or ""
        title = text.split("\n")[0][:200] if text.strip() else f"{channel.name} #{msg.id}"
        url = f"https://t.me/{channel.handle}/{msg.id}"
        published = msg.date.astimezone(datetime.UTC).isoformat()

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
        import datetime

        from pipeline import process_item

        # Concatenate text from all messages in the album
        texts = [m.message for m in msgs if m.message]
        text = "\n".join(texts)
        title = text.split("\n")[0][:200] if text else channel.name
        canonical_msg = min(msgs, key=lambda m: m.id)
        url = f"https://t.me/{channel.handle}/{canonical_msg.id}"
        published = canonical_msg.date.astimezone(datetime.UTC).isoformat()

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
        for path, mtype in zip(media_paths, media_types, strict=False):
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
            max_size = self._settings.telegram_media_max_size
            if msg.file and msg.file.size and msg.file.size > max_size:
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
        if pending_count > self._settings.vision_queue_max_pending and channel.priority != "high":
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
        import datetime

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
            "ingested_at": datetime.datetime.now(datetime.UTC).isoformat(),
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
