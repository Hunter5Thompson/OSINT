"""EONET — NASA Earth Observatory Natural Event Tracker.

Collects natural events (wildfires, volcanoes, storms, floods, etc.)
and upserts to Qdrant. Mutable events: first-seen goes through Pipeline,
updates refresh the existing source Location without creating duplicate Events.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from feeds.base import BaseCollector
from feeds.provenance import dataset_provenance

log = structlog.get_logger("eonet_collector")

_EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"


def _parse_utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None
    except OverflowError:
        return None


def _valid_point_coordinates(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    lon_raw, lat_raw = value[0], value[1]
    if any(
        isinstance(component, bool) or not isinstance(component, (int, float))
        for component in (lon_raw, lat_raw)
    ):
        return None
    try:
        lon, lat = float(lon_raw), float(lat_raw)
    except OverflowError:
        return None
    if (
        not math.isfinite(lon)
        or not math.isfinite(lat)
        or not -180 <= lon <= 180
        or not -90 <= lat <= 90
    ):
        return None
    return lon, lat


def build_eonet_payload(event: dict, description: str) -> dict:
    """EONET Qdrant payload builder (no network/disk I/O). event_date stays an
    event time; it is NOT published_at."""
    now = datetime.now(UTC)
    return {
        **dataset_provenance("eonet"),
        "source": "eonet",
        **event,
        "ingested_epoch": now.timestamp(),
        "ingested_at": now.isoformat(),
        "description": description,
    }


class EONETCollector(BaseCollector):
    """Collect natural events from NASA EONET API."""

    def _parse_events(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse EONET response into normalized event dicts."""
        events: list[dict[str, Any]] = []
        invalid_geometry_count = 0
        skipped_event_count = 0
        raw_events = data.get("events", [])
        if not isinstance(raw_events, list):
            return events
        for event in raw_events:
            if not isinstance(event, Mapping):
                continue
            geometries = event.get("geometry", [])
            if not isinstance(geometries, list):
                invalid_geometry_count += 1
                skipped_event_count += 1
                continue
            if not geometries:
                continue

            candidates: list[tuple[datetime, float, float]] = []
            invalid_for_event = False
            for geometry in geometries:
                if not isinstance(geometry, Mapping):
                    invalid_geometry_count += 1
                    invalid_for_event = True
                    continue
                if geometry.get("type") != "Point":
                    # Valid non-Point geometries are expected EONET data.
                    continue
                occurred_at = _parse_utc_datetime(geometry.get("date"))
                coordinates = _valid_point_coordinates(geometry.get("coordinates"))
                if occurred_at is None or coordinates is None:
                    invalid_geometry_count += 1
                    invalid_for_event = True
                    continue
                lon, lat = coordinates
                candidates.append((occurred_at, lon, lat))
            if not candidates:
                if invalid_for_event:
                    skipped_event_count += 1
                continue
            occurred_at, lon, lat = max(candidates, key=lambda candidate: candidate[0])

            categories = event.get("categories", [])
            category = (
                categories[0].get("id", "unknown")
                if isinstance(categories, list)
                and categories
                and isinstance(categories[0], Mapping)
                else "unknown"
            )
            event_id = event.get("id")
            if not isinstance(event_id, (str, int)):
                continue

            events.append({
                "eonet_id": str(event_id),
                "title": event.get("title", ""),
                "category": category,
                "status": "closed" if event.get("closed") else "open",
                "latitude": lat,
                "longitude": lon,
                "event_date": occurred_at.isoformat().replace("+00:00", "Z"),
            })
        if invalid_geometry_count:
            log.warning(
                "eonet_invalid_geometry_summary",
                invalid_geometry_count=invalid_geometry_count,
                skipped_event_count=skipped_event_count,
            )
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

                event_url = f"https://eonet.gsfc.nasa.gov/api/v3/events/{event['eonet_id']}"
                try:
                    await process_item(
                        title=event["title"],
                        text=description,
                        url=event_url,
                        source="eonet",
                        observed_at=event.get("event_date"),
                        source_evidence={**event, "source": "eonet"},
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
                try:
                    await self._refresh_observation_location({**event, "source": "eonet"})
                except Exception:
                    log.exception("eonet_location_refresh_failed", event_id=event["eonet_id"])
                    continue
                update_count += 1

            # Mutable events use manual PointStruct (can't use _build_point
            # which derives point_id from content_hash internally, but we need event-based IDs)
            try:
                vector = await self._embed(description)
            except Exception:
                log.warning("eonet_embed_failed", event_id=event["eonet_id"])
                continue

            payload = build_eonet_payload(event, description)
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
