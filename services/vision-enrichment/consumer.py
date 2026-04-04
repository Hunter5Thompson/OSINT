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
                entries = await self._redis.xreadgroup(
                    self._settings.vision_consumer_group,
                    self._settings.vision_consumer_name,
                    {self._settings.vision_queue_name: ">"},
                    count=5,
                    block=5000,
                )

                if entries:
                    for _stream_name, messages in entries:
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
        msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
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
            # Clean up any retry state from prior failed attempts
            await self._redis.delete(f"vision:retries:{msg_id_str}")
            log.info("vision_processed", url=url, channel=channel)

        except Exception as e:
            log.error("vision_processing_failed", url=url, error=str(e))

            # Track retries
            retry_key = f"vision:retries:{msg_id_str}"
            retry_count = await self._redis.hincrby(retry_key, "count", 1)

            if retry_count > self._settings.vision_max_retries:
                # Dead letter
                await self._redis.xadd(
                    self._settings.vision_dead_letter_queue,
                    {
                        **{
                            k.decode() if isinstance(k, bytes) else k: v.decode()
                            if isinstance(v, bytes)
                            else v
                            for k, v in msg_data.items()
                        },
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
