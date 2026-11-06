"""Fetch availability is separate from document freshness and write success."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

KEY = "health:collector-fetch:v1"
Status = Literal["available", "unavailable", "not_configured", "unknown", "stale"]


class FeedDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    collector: Literal["rss", "hapi", "ofac"]
    name: str = Field(min_length=1, max_length=180)
    max_age_s: int = Field(gt=0, le=604800)


class FetchObservation(BaseModel):
    status: Literal["available", "unavailable", "not_configured"]
    attempt_at: int = Field(ge=0)
    item_count: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=80)


class FeedAvailability(FeedDefinition):
    status: Status = "unknown"
    last_attempt_at: int | None = None
    last_success_at: int | None = None
    item_count: int | None = None
    error_code: str | None = None


class CollectorAvailabilityReport(BaseModel):
    status: Literal["ok", "degraded"]
    checked_at: int
    meaning: str = "Publisher fetch availability; not ingestion success or evidence freshness."
    feeds: list[FeedAvailability]


def availability_report(snapshot: dict[str, str], *, now: int) -> CollectorAvailabilityReport:
    try:
        raw = json.loads(snapshot["_registry"])
        if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
            raise ValueError("Invalid registry size")
        registry = [FeedDefinition.model_validate(entry) for entry in raw]
        if len({entry.id for entry in registry}) != len(registry):
            raise ValueError("Duplicate feed IDs")
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Collector registry unavailable") from exc

    feeds = []
    for definition in registry:
        feed = FeedAvailability(**definition.model_dump())
        try:
            observation = FetchObservation.model_validate_json(snapshot[feed.id])
            success = snapshot.get(f"{feed.id}:last_success")
            last_success = int(success) if success is not None else None
            if observation.attempt_at > now or (
                last_success is not None and not 0 <= last_success <= now
            ):
                raise ValueError("Future or invalid telemetry timestamp")
            feed.status = observation.status
            feed.last_attempt_at = observation.attempt_at
            feed.last_success_at = last_success
            feed.item_count = observation.item_count
            feed.error_code = observation.error_code
            if feed.status == "available" and (
                last_success is None or now - observation.attempt_at > feed.max_age_s
            ):
                feed.status = "stale"
        except (KeyError, ValueError, ValidationError):
            pass
        feeds.append(feed)
    return CollectorAvailabilityReport(
        status="ok" if all(feed.status == "available" for feed in feeds) else "degraded",
        checked_at=now, feeds=feeds,
    )
