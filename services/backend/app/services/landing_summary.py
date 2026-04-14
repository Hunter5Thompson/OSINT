"""Aggregator service for the Landing page 24h numerals.

Queries Qdrant (FIRMS hotspots + all ingested signals) and Neo4j (UCDP
conflict-event documents) concurrently. Each upstream is isolated: a
failure in one does not cascade — the service returns a `LandingSummary`
with that metric set to `None` and the source marked `:unavailable`.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import structlog
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

from app.config import settings
from app.models.landing import LandingSummary
from app.services.neo4j_client import read_query
from app.services.qdrant_client import get_qdrant_client

log = structlog.get_logger(__name__)

# UCDP conflict documents in Neo4j are written by the data-ingestion
# pipeline (services/data-ingestion/pipeline.py) as
#   MERGE (d:Document {url: ...}) SET d.source = 'ucdp', d.updated_at = datetime()
# so we count fresh documents with that source marker.
_UCDP_COUNT_CYPHER = (
    "MATCH (d:Document {source: 'ucdp'}) "
    "WHERE d.updated_at >= datetime($cutoff) "
    "RETURN count(d) AS count"
)


class LandingSummaryService:
    """Concurrent fan-out aggregator with per-source error isolation."""

    async def get_summary(self, window: timedelta) -> LandingSummary:
        cutoff_epoch = time.time() - window.total_seconds()
        cutoff_iso = datetime.fromtimestamp(cutoff_epoch, tz=UTC).isoformat()

        hotspots_task = self._count_hotspots(cutoff_epoch)
        conflict_task = self._count_conflicts(cutoff_iso)
        nuntii_task = self._count_nuntii(cutoff_epoch)

        (hotspots_val, hotspots_src), (conflict_val, conflict_src), (
            nuntii_val,
            nuntii_src,
        ) = await asyncio.gather(
            hotspots_task,
            conflict_task,
            nuntii_task,
        )

        libri_val, libri_src = self._libri_stub()

        return LandingSummary(
            window=_format_window(window),
            generated_at=datetime.now(UTC),
            hotspots_24h=hotspots_val,
            hotspots_source=hotspots_src,
            conflict_24h=conflict_val,
            conflict_source=conflict_src,
            nuntii_24h=nuntii_val,
            nuntii_source=nuntii_src,
            libri_24h=libri_val,
            libri_source=libri_src,
            reports_not_available_yet=True,
        )

    async def _count_hotspots(self, cutoff_epoch: float) -> tuple[int | None, str]:
        """Count FIRMS points in Qdrant with ingested_epoch >= cutoff."""
        flt = Filter(
            must=[
                FieldCondition(key="source", match=MatchValue(value="firms")),
                FieldCondition(key="ingested_epoch", range=Range(gte=cutoff_epoch)),
            ]
        )
        try:
            qdrant = await get_qdrant_client()
            result = await qdrant.count(
                collection_name=settings.qdrant_collection,
                count_filter=flt,
                exact=True,
            )
            return int(result.count), "qdrant:firms"
        except Exception as exc:
            log.warning("landing_hotspots_unavailable", error=str(exc))
            return None, "qdrant:firms:unavailable"

    async def _count_conflicts(self, cutoff_iso: str) -> tuple[int | None, str]:
        """Count UCDP Documents in Neo4j with updated_at >= cutoff."""
        try:
            rows = await read_query(_UCDP_COUNT_CYPHER, {"cutoff": cutoff_iso})
            count = int(rows[0]["count"]) if rows else 0
            return count, "neo4j:ucdp"
        except Exception as exc:
            log.warning("landing_conflict_unavailable", error=str(exc))
            return None, "neo4j:ucdp:unavailable"

    async def _count_nuntii(self, cutoff_epoch: float) -> tuple[int | None, str]:
        """Count all Qdrant points ingested within window (regardless of source)."""
        flt = Filter(
            must=[
                FieldCondition(key="ingested_epoch", range=Range(gte=cutoff_epoch)),
            ]
        )
        try:
            qdrant = await get_qdrant_client()
            result = await qdrant.count(
                collection_name=settings.qdrant_collection,
                count_filter=flt,
                exact=True,
            )
            return int(result.count), "qdrant:signals"
        except Exception as exc:
            log.warning("landing_nuntii_unavailable", error=str(exc))
            return None, "qdrant:signals:unavailable"

    @staticmethod
    def _libri_stub() -> tuple[int, str]:
        """S1 stub — Reports backend is S3. Always 0."""
        return 0, "reports:stub"


def _format_window(window: timedelta) -> str:
    hours = int(window.total_seconds() // 3600)
    return f"{hours}h"
