"""FIRMS cross-correlation batch job.

Correlates FIRMS thermal anomalies (possible_explosion=true) with
conflict events from any source (GDELT, UCDP, RSS) within a
configurable radius and time window. Writes CORROBORATED_BY
relationships to Neo4j.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime
from typing import Any

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    Range,
)

from config import Settings
from feeds.geo import haversine_km

log = structlog.get_logger(__name__)

SCROLL_LIMIT = 200

_REDIS_KEY_LAST_RUN = "correlation:last_run"


# Conflict sources to correlate against FIRMS hits
CONFLICT_SOURCES = ("gdelt", "ucdp", "rss")

# Codebook types that indicate conflict/violence (boost score)
CONFLICT_CODEBOOK_TYPES = frozenset({
    "military.airstrike",
    "military.drone_attack",
    "military.shelling",
    "military.ground_combat",
    "political.armed_clash",
})


def correlation_score(
    distance_km: float,
    days_diff: int,
    possible_explosion: bool,
    conflict_codebook_type: str,
    firms_confidence: str,
) -> float:
    """Compute correlation confidence between a FIRMS and a conflict event.

    Returns a score from 0.0 to 1.0.
    """
    # Distance: 0km = 1.0, 50km = 0.0 (linear)
    dist_score = max(0.0, 1.0 - distance_km / 50.0)

    # Time: same day = 1.0, ±1 day = 0.5
    time_score = 1.0 if days_diff == 0 else 0.5

    # Base = distance × time
    base = dist_score * time_score

    # Additive bonuses, capped at 1.0
    bonus = 0.0
    if possible_explosion:
        bonus += 0.3
    if conflict_codebook_type in CONFLICT_CODEBOOK_TYPES:
        bonus += 0.2
    if firms_confidence == "high":
        bonus += 0.1

    return min(1.0, round(base + bonus, 2))


def build_firms_filter(last_run_epoch: float) -> Filter:
    """Build a Qdrant filter for FIRMS points since *last_run_epoch*.

    Only returns points with source=firms, possible_explosion=True, and
    ingested_epoch >= last_run_epoch.
    """
    return Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value="firms")),
            FieldCondition(key="possible_explosion", match=MatchValue(value=True)),
            FieldCondition(
                key="ingested_epoch",
                range=Range(gte=last_run_epoch),
            ),
        ]
    )


def build_conflict_bbox_filter(lat: float, lon: float) -> Filter:
    """Build a Qdrant filter for conflict events within ~50 km of (lat, lon).

    Matches any source in CONFLICT_SOURCES (gdelt, ucdp, rss).
    The lat window is always ±0.5°.  The lon window is widened by
    1/cos(lat) to keep a roughly square ground footprint.
    """
    lat_delta = 0.5
    cos_lat = math.cos(math.radians(lat))
    lon_delta = 0.5 / max(cos_lat, 1e-6)

    return Filter(
        must=[
            FieldCondition(
                key="latitude",
                range=Range(gte=lat - lat_delta, lte=lat + lat_delta),
            ),
            FieldCondition(
                key="longitude",
                range=Range(gte=lon - lon_delta, lte=lon + lon_delta),
            ),
        ],
        should=[
            FieldCondition(key="source", match=MatchValue(value=src))
            for src in CONFLICT_SOURCES
        ],
    )


def _extract_event_date(payload: dict) -> str:
    """Extract a date string from a conflict event payload.

    Different sources store dates in different fields:
    - GDELT: seen_date (YYYYMMDDTHHMMSS or ISO)
    - UCDP: date_start (YYYY-MM-DD)
    - RSS: published (ISO datetime)
    - Fallback: ingested_at (ISO datetime)
    """
    for key in ("event_date", "date_start", "seen_date", "published", "ingested_at"):
        val = payload.get(key, "")
        if val:
            return val[:10]  # Take YYYY-MM-DD portion
    return ""


def passes_time_filter(
    firms_date: str,
    conflict_date: str,
    window_days: int,
) -> bool:
    """Return True if |firms_date - conflict_date| <= window_days.

    Both dates are ISO-format strings (YYYY-MM-DD).
    """
    try:
        d_firms = date.fromisoformat(firms_date)
        d_conflict = date.fromisoformat(conflict_date)
        return abs((d_conflict - d_firms).days) <= window_days
    except (ValueError, TypeError):
        return False


class CorrelationJob:
    """Batch job: correlate FIRMS thermal anomalies with conflict events."""

    def __init__(
        self,
        settings: Settings,
        redis_client: Any = None,
    ) -> None:
        self.settings = settings
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        # redis_client may be injected (tests) or set later via self.redis
        self.redis = redis_client

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    async def _get_last_run_epoch(self) -> float:
        """Return the epoch of the last successful run, or 7 days ago."""
        raw = await self.redis.get(_REDIS_KEY_LAST_RUN)
        if raw is not None:
            return float(raw)
        return datetime.now(UTC).timestamp() - 7 * 86400

    async def _set_last_run(self) -> None:
        """Persist the current timestamp as last_run epoch."""
        await self.redis.set(_REDIS_KEY_LAST_RUN, str(datetime.now(UTC).timestamp()))

    # ------------------------------------------------------------------
    # Qdrant helpers
    # ------------------------------------------------------------------

    async def _scroll_all(self, filter: Filter) -> list[Any]:
        """Paginate through all matching Qdrant points."""
        results: list[Any] = []
        offset = None
        while True:
            points, next_offset = await asyncio.to_thread(
                self.qdrant.scroll,
                collection_name=self.settings.qdrant_collection,
                scroll_filter=filter,
                limit=SCROLL_LIMIT,
                offset=offset,
                with_payload=True,
            )
            results.extend(points)
            if next_offset is None:
                break
            offset = next_offset
        return results

    # ------------------------------------------------------------------
    # Neo4j writer
    # ------------------------------------------------------------------

    async def _write_corroboration(
        self,
        client: httpx.AsyncClient,
        firms_url: str,
        conflict_url: str,
        score: float,
        distance_km: float,
        days_diff: int,
    ) -> None:
        """Write a CORROBORATED_BY relationship between two Document nodes."""
        cypher = (
            "MATCH (f:Document {url: $firms_url}) "
            "MATCH (a:Document {url: $conflict_url}) "
            "MERGE (f)-[r:CORROBORATED_BY]->(a) "
            "SET r.score = $score, "
            "    r.distance_km = $distance_km, "
            "    r.days_diff = $days_diff, "
            "    r.updated_at = datetime()"
        )
        payload = {
            "statements": [
                {
                    "statement": cypher,
                    "parameters": {
                        "firms_url": firms_url,
                        "conflict_url": conflict_url,
                        "score": score,
                        "distance_km": distance_km,
                        "days_diff": days_diff,
                    },
                }
            ]
        }
        resp = await client.post(
            f"{self.settings.neo4j_url}/db/neo4j/tx/commit",
            json=payload,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one correlation pass."""
        last_run_epoch = await self._get_last_run_epoch()
        log.info("correlation.run.start", last_run_epoch=last_run_epoch)

        firms_filter = build_firms_filter(last_run_epoch)
        firms_points = await self._scroll_all(firms_filter)
        log.info("correlation.firms_loaded", count=len(firms_points))

        failed_pairs: list[tuple[str, str]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for fp in firms_points:
                p = fp.payload
                f_lat: float = p["latitude"]
                f_lon: float = p["longitude"]
                f_date: str = p.get("acq_date", "")
                f_url: str = p.get("url", "")
                f_confidence: str = p.get("confidence", "nominal")
                f_explosion: bool = bool(p.get("possible_explosion", False))

                conflict_filter = build_conflict_bbox_filter(f_lat, f_lon)
                conflict_points = await self._scroll_all(conflict_filter)

                for cp in conflict_points:
                    a = cp.payload
                    a_lat: float = a["latitude"]
                    a_lon: float = a["longitude"]
                    a_date: str = _extract_event_date(a)
                    a_url: str = a.get("url", "")
                    a_codebook_type: str = a.get("codebook_type", "")

                    # Precise distance check
                    dist_km = haversine_km(f_lat, f_lon, a_lat, a_lon)
                    if dist_km > self.settings.correlation_radius_km:
                        continue

                    # Time window check
                    if f_date and a_date and not passes_time_filter(
                        f_date,
                        a_date,
                        window_days=self.settings.correlation_time_window_days,
                    ):
                        continue

                    # Compute score
                    days_diff = 0
                    if f_date and a_date:
                        days_diff = abs(
                            (
                                date.fromisoformat(a_date)
                                - date.fromisoformat(f_date)
                            ).days
                        )

                    score = correlation_score(
                        distance_km=dist_km,
                        days_diff=days_diff,
                        possible_explosion=f_explosion,
                        conflict_codebook_type=a_codebook_type,
                        firms_confidence=f_confidence,
                    )

                    if score < self.settings.correlation_min_score:
                        continue

                    # Write to Neo4j
                    try:
                        await self._write_corroboration(
                            client=client,
                            firms_url=f_url,
                            conflict_url=a_url,
                            score=score,
                            distance_km=dist_km,
                            days_diff=days_diff,
                        )
                        log.info(
                            "correlation.pair_written",
                            firms_url=f_url,
                            conflict_url=a_url,
                            score=score,
                            distance_km=dist_km,
                        )
                    except Exception:
                        log.exception(
                            "correlation.write_failed",
                            firms_url=f_url,
                            conflict_url=a_url,
                        )
                        failed_pairs.append((f_url, a_url))

        if failed_pairs:
            log.warning(
                "correlation.run.partial_failure",
                failed_count=len(failed_pairs),
            )
        else:
            await self._set_last_run()
            log.info("correlation.run.complete")
