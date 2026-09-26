"""GDACS — Global Disaster Alert and Coordination System.

Collects disaster events (earthquakes, cyclones, floods, volcanoes, droughts, wildfires).
Mutable events: first-seen through Pipeline, updates Qdrant-only.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from feeds.base import BaseCollector
from feeds.provenance import dataset_provenance

log = structlog.get_logger("gdacs_collector")

_GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"
# The MAP endpoint requires exactly one ``eventtype`` per request (2026-09 API
# change: a bare call answers 400 "Eventtype is required.").
GDACS_EVENT_TYPES: tuple[str, ...] = ("EQ", "TC", "FL", "VO", "DR", "WF")
_CENTROID_CLASS = "Point_Centroid"


def _severity(props: dict[str, Any]) -> float:
    """Legacy ``severity.value`` or current ``severitydata.severity``; 0.0 if unusable."""
    for key, field in (("severity", "value"), ("severitydata", "severity")):
        obj = props.get(key)
        if isinstance(obj, dict) and obj.get(field) is not None:
            try:
                return float(obj[field])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def build_gdacs_payload(event: dict, description: str) -> dict:
    """GDACS Qdrant payload builder (no network/disk I/O). from_date/to_date stay
    event times; they are NOT published_at."""
    now = datetime.now(UTC)
    return {
        **dataset_provenance("gdacs"),
        "source": "gdacs",
        **event,
        "ingested_epoch": now.timestamp(),
        "ingested_at": now.isoformat(),
        "description": description,
    }


class GDACSCollector(BaseCollector):
    """Collect disaster alerts from GDACS API."""

    def _parse_features(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """One event per GDACS event id, located at its point centroid.

        MAP responses carry several features per event (centroid, forecast
        tracks, cone polygons, buffer points); only a ``Point`` feature is a
        location, and when ``Class`` is present only ``Point_Centroid`` is.
        """
        events: dict[str, dict[str, Any]] = {}
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates", [])
            if geom.get("type") != "Point" or len(coords) < 2:
                continue
            if props.get("Class", _CENTROID_CLASS) != _CENTROID_CLASS:
                continue

            event_type = str(props.get("eventtype", ""))
            event_id = str(props.get("eventid", ""))
            gdacs_id = f"{event_type}_{event_id}"
            if gdacs_id in events:
                continue

            events[gdacs_id] = {
                "gdacs_id": gdacs_id,
                "event_type": event_type,
                "event_name": str(props.get("eventname") or props.get("name") or ""),
                "alert_level": str(props.get("alertlevel", "")),
                "severity": _severity(props),
                "country": str(props.get("country", "")),
                "latitude": coords[1],
                "longitude": coords[0],
                "from_date": str(props.get("fromdate", "")),
                "to_date": str(props.get("todate", "")),
            }
        return list(events.values())

    async def _fetch_event_type(self, event_type: str) -> list[dict[str, Any]]:
        """Fetch one event type; a failure only drops that type."""
        try:
            resp = await self.http.get(
                _GDACS_URL, params={"eventtype": event_type}, timeout=60
            )
            if resp.status_code == 404:  # MAP answers 404 when a type has no events
                log.info("gdacs_no_events", event_type=event_type)
                return []
            resp.raise_for_status()
            return self._parse_features(resp.json())
        except Exception:
            log.exception("gdacs_fetch_failed", event_type=event_type)
            return []

    async def collect(self) -> None:
        await self._ensure_collection()

        by_id: dict[str, dict[str, Any]] = {}
        for event_type in GDACS_EVENT_TYPES:
            for event in await self._fetch_event_type(event_type):
                by_id.setdefault(event["gdacs_id"], event)
        events = list(by_id.values())
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
            description = (
                f"{event['event_name']} - {event['event_type']} alert ({event['alert_level']})"
            )

            existing = await asyncio.to_thread(
                self.qdrant.retrieve,
                collection_name=self.settings.qdrant_collection,
                ids=[point_id],
            )
            is_new = len(existing) == 0

            if is_new:
                from pipeline import (
                    ExtractionConfigError,
                    ExtractionTransientError,
                    process_item,
                )

                event_url = (
                    f"https://www.gdacs.org/report.aspx?eventtype={event['event_type']}"
                    f"&eventid={raw_event_id}"
                )
                # Transient/config errors skip Qdrant upsert so the event is
                # retried on the next source re-fetch.
                try:
                    await process_item(
                        title=event["event_name"],
                        text=description,
                        url=event_url,
                        source="gdacs",
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
                    log.warning("gdacs_pipeline_failed", event_id=event["gdacs_id"])
                new_count += 1
            else:
                update_count += 1

            try:
                vector = await self._embed(description)
            except Exception:
                log.warning("gdacs_embed_failed", event_id=event["gdacs_id"])
                continue

            payload = build_gdacs_payload(event, description)
            point = PointStruct(id=point_id, vector=vector, payload=payload)
            points.append(point)

        if points:
            await self._batch_upsert(points)

        log.info(
            "gdacs_complete", total=len(events), new=new_count,
            updated=update_count, upserted=len(points),
        )
