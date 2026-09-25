"""Data-based feed freshness: when did each source last land a point in Qdrant?

Measured from the data itself, not from scheduler runs — a collector that swallows an
upstream 404 and writes nothing still looks "healthy" to a job heartbeat, but ages here.
Needs a float range index on ``ingested_epoch`` (intelligence
``scripts.ensure_payload_indexes``); without it Qdrant rejects ``order_by`` and the
source reports ``unknown`` instead of a false ``fresh``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from qdrant_client.models import Direction, FieldCondition, Filter, MatchValue, OrderBy

FreshnessStatus = Literal["fresh", "stale", "missing", "unknown"]


class SourceFreshness(BaseModel):
    source: str
    status: FreshnessStatus
    last_ingested_at: datetime | None = None
    age_s: int | None = None
    max_age_s: int
    error: str | None = None


class FeedFreshnessReport(BaseModel):
    status: Literal["ok", "degraded"]
    checked_at: datetime
    sources: list[SourceFreshness]


async def _source_freshness(
    client: Any, collection: str, source: str, max_age_s: int, now: float
) -> SourceFreshness:
    try:
        points, _ = await client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            ),
            order_by=OrderBy(key="ingested_epoch", direction=Direction.DESC),
            limit=1,
            with_payload=["ingested_epoch"],
            with_vectors=False,
        )
        if not points:
            return SourceFreshness(source=source, status="missing", max_age_s=max_age_s)
        epoch = float((points[0].payload or {})["ingested_epoch"])
    except Exception as exc:  # noqa: BLE001 - any failure must degrade, never read as fresh
        return SourceFreshness(
            source=source, status="unknown", max_age_s=max_age_s, error=str(exc)[:200]
        )
    age = max(0, int(now - epoch))
    return SourceFreshness(
        source=source,
        status="fresh" if age <= max_age_s else "stale",
        last_ingested_at=datetime.fromtimestamp(epoch, UTC),
        age_s=age,
        max_age_s=max_age_s,
    )


async def compute_feed_freshness(
    client: Any,
    *,
    collection: str,
    max_age_s: dict[str, int],
    now: float | None = None,
) -> FeedFreshnessReport:
    at = time.time() if now is None else now
    sources = await asyncio.gather(
        *(
            _source_freshness(client, collection, source, limit, at)
            for source, limit in max_age_s.items()
        )
    )
    return FeedFreshnessReport(
        status="ok" if all(s.status == "fresh" for s in sources) else "degraded",
        checked_at=datetime.fromtimestamp(at, UTC),
        sources=list(sources),
    )
