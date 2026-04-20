"""EONET — NASA Earth Observatory Natural Event Tracker.

Collects natural events (wildfires, volcanoes, storms, floods, etc.)
and upserts to Qdrant. Mutable events: first-seen goes through Pipeline,
updates are Qdrant-only to avoid Neo4j duplicates.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from feeds.base import BaseCollector

log = structlog.get_logger("eonet_collector")

_EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"


class EONETCollector(BaseCollector):
    """Collect natural events from NASA EONET API."""

    def _parse_events(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse EONET response into normalized event dicts."""
        events: list[dict[str, Any]] = []
        for event in data.get("events", []):
            geometries = event.get("geometry", [])
            if not geometries:
                continue

            # Filter to Point geometries only (EONET also returns Polygons)
            point_geometries = [g for g in geometries if g.get("type") == "Point"]
            if not point_geometries:
                continue

            # Use latest Point geometry (most recent position)
            latest = max(point_geometries, key=lambda g: g.get("date", ""))
            coords = latest.get("coordinates", [])
            if len(coords) < 2:
                continue

            categories = event.get("categories", [])
            category = categories[0].get("id", "unknown") if categories else "unknown"

            events.append({
                "eonet_id": event["id"],
                "title": event.get("title", ""),
                "category": category,
                "status": "closed" if event.get("closed") else "open",
                "latitude": coords[1],  # GeoJSON: [lon, lat]
                "longitude": coords[0],
                "event_date": latest.get("date", ""),
            })
        return events

    async def collect(self) -> None:
        """Fetch EONET events, upsert to Qdrant (mutable-event pattern)."""
        await self._ensure_collection()

        params = {"status": "open", "days": 30}
        try:
            resp = await self.http.get(_EONET_URL, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            log.exception("eonet_fetch_failed")
            return

        events = self._parse_events(data)
        log.info("eonet_parsed", count=len(events))

        if not events:
            return

        new_count = 0
        update_count = 0
        points = []

        for event in events:
            chash = self._content_hash("eonet", event["eonet_id"])
            point_id = self._point_id(chash)
            description = f"{event['title']} - {event['category']} event"

            # Check if already exists in Qdrant
            existing = await asyncio.to_thread(
                self.qdrant.retrieve,
                collection_name=self.settings.qdrant_collection,
                ids=[point_id],
            )
            is_new = len(existing) == 0

            if is_new:
                # First-seen: run through Pipeline for Neo4j.
                # Transient/config errors skip Qdrant upsert so the event is
                # retried on the next source re-fetch.
                from pipeline import (
                    ExtractionConfigError,
                    ExtractionTransientError,
                    process_item,
                )

                event_url = (
                    f"https://eonet.gsfc.nasa.gov/api/v3/events/{event['eonet_id']}"
                )
                try:
                    await process_item(
                        title=event["title"],
                        text=description,
                        url=event_url,
                        source="eonet",
                        settings=self.settings,
                        redis_client=self.redis,
                    )
                except ExtractionTransientError as exc:
                    log.warning(
                        "extraction_skipped_transient",
                        url=event_url,
                        error=str(exc),
                    )
                    continue
                except ExtractionConfigError as exc:
                    log.error(
                        "extraction_skipped_config",
                        url=event_url,
                        error=str(exc),
                    )
                    continue
                except Exception:
                    log.warning("eonet_pipeline_failed", event_id=event["eonet_id"])
                new_count += 1
            else:
                update_count += 1

            # Mutable events use manual PointStruct (can't use _build_point
            # which derives point_id from content_hash internally, but we need event-based IDs)
            try:
                vector = await self._embed(description)
            except Exception:
                log.warning("eonet_embed_failed", event_id=event["eonet_id"])
                continue

            payload = {
                "source": "eonet",
                **event,
                "ingested_epoch": time.time(),
                "description": description,
            }
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        if points:
            await self._batch_upsert(points)

        log.info(
            "eonet_complete",
            total=len(events),
            new=new_count,
            updated=update_count,
            upserted=len(points),
        )
