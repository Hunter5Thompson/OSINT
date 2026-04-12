"""GDACS — Global Disaster Alert and Coordination System.

Collects disaster events (earthquakes, cyclones, floods, volcanoes, droughts, wildfires).
Mutable events: first-seen through Pipeline, updates Qdrant-only.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from feeds.base import BaseCollector

log = structlog.get_logger("gdacs_collector")

_GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"


class GDACSCollector(BaseCollector):
    """Collect disaster alerts from GDACS API."""

    def _parse_features(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            if len(coords) < 2:
                continue

            event_type = str(props.get("eventtype", ""))
            event_id = str(props.get("eventid", ""))
            severity_obj = props.get("severity", {})
            try:
                severity = float(severity_obj.get("value", 0)) if isinstance(severity_obj, dict) else 0.0
            except (TypeError, ValueError):
                severity = 0.0

            events.append({
                "gdacs_id": f"{event_type}_{event_id}",
                "event_type": event_type,
                "event_name": str(props.get("eventname", "")),
                "alert_level": str(props.get("alertlevel", "")),
                "severity": severity,
                "country": str(props.get("country", "")),
                "latitude": coords[1],
                "longitude": coords[0],
                "from_date": str(props.get("fromdate", "")),
                "to_date": str(props.get("todate", "")),
            })
        return events

    async def collect(self) -> None:
        await self._ensure_collection()

        try:
            resp = await self.http.get(_GDACS_URL, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            log.exception("gdacs_fetch_failed")
            return

        events = self._parse_features(data)
        log.info("gdacs_parsed", count=len(events))

        if not events:
            return

        new_count = 0
        update_count = 0
        points = []

        for event in events:
            raw_event_id = event["gdacs_id"].split("_")[-1]
            chash = self._content_hash("gdacs", event["event_type"], raw_event_id)
            point_id = self._point_id(chash)
            description = f"{event['event_name']} - {event['event_type']} alert ({event['alert_level']})"

            existing = await asyncio.to_thread(
                self.qdrant.retrieve,
                collection_name=self.settings.qdrant_collection,
                ids=[point_id],
            )
            is_new = len(existing) == 0

            if is_new:
                try:
                    from pipeline import process_item
                    await process_item(
                        title=event["event_name"],
                        text=description,
                        url=f"https://www.gdacs.org/report.aspx?eventtype={event['event_type']}&eventid={raw_event_id}",
                        source="gdacs",
                        settings=self.settings,
                        redis_client=self.redis,
                    )
                except Exception:
                    log.warning("gdacs_pipeline_failed", event_id=event["gdacs_id"])
                new_count += 1
            else:
                update_count += 1

            try:
                vector = await self._embed(description)
            except Exception:
                log.warning("gdacs_embed_failed", event_id=event["gdacs_id"])
                continue

            payload = {
                "source": "gdacs",
                **event,
                "ingested_epoch": time.time(),
                "description": description,
            }
            point = PointStruct(id=point_id, vector=vector, payload=payload)
            points.append(point)

        if points:
            await self._batch_upsert(points)

        log.info("gdacs_complete", total=len(events), new=new_count, updated=update_count, upserted=len(points))
