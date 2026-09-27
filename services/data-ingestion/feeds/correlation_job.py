"""FIRMS cross-correlation batch job.

Correlates structured FIRMS thermal observations with canonical graph Events.
Distance/time proximity is an observation, not independent corroboration.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
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
from graph_integrity.spatial_normalizer import load_active_normalization_index

log = structlog.get_logger(__name__)

SCROLL_LIMIT = 200

_REDIS_KEY_LAST_RUN = "correlation:last_run"


# Codebook types that indicate conflict/violence (boost score)
CONFLICT_CODEBOOK_TYPES = frozenset(
    {
        "military.airstrike",
        "military.drone_attack",
        "military.shelling",
        "military.ground_combat",
        "political.armed_clash",
    }
)


def correlation_score(
    distance_km: float,
    days_diff: int,
    conflict_codebook_type: str,
    firms_confidence: str,
) -> float:
    """Compute an uncalibrated proximity ranking between a FIRMS and a conflict event.

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
    if conflict_codebook_type in CONFLICT_CODEBOOK_TYPES:
        bonus += 0.2
    if firms_confidence == "high":
        bonus += 0.1

    return min(1.0, round(base + bonus, 2))


def build_firms_filter(last_run_epoch: float) -> Filter:
    """Build a Qdrant filter for FIRMS points since *last_run_epoch*.

    Only returns points with source=firms and
    ingested_epoch >= last_run_epoch.
    """
    return Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value="firms")),
            FieldCondition(
                key="ingested_epoch",
                range=Range(gte=last_run_epoch),
            ),
        ]
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

    async def _graph_rows(self, client, statement, parameters):
        response = await client.post(
            f"{self.settings.neo4j_http_url}/db/neo4j/tx/commit",
            json={"statements": [{"statement": statement, "parameters": parameters}]},
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            raise RuntimeError(f"Neo4j correlation query failed: {body['errors']}")
        result = body["results"][0]
        return [dict(zip(result["columns"], row["row"], strict=True)) for row in result["data"]]

    async def _event_candidates(self, client, observation):
        index = load_active_normalization_index(
            self.settings.spatial_catalog_path,
            crosswalk_path=self.settings.spatial_country_crosswalk_path,
        )
        observed = date.fromisoformat(observation["acq_date"])
        window = timedelta(days=self.settings.correlation_time_window_days)
        # Join canonical Events, never a document-level GKG coordinate proxy.
        # Indexed GDELT time remains explicitly labelled on the resulting edge.
        return await self._graph_rows(
            client,
            """
MATCH (e:Event)-[:OCCURRED_AT]->(l:Location)
WHERE e.codebook_type IN $types
  AND e.timeline_at >= datetime($start) AND e.timeline_at < datetime($end)
  AND l.spatial_conflict = false AND l.geo IS NOT NULL
  AND l.spatial_derivation_revision IN $derivations
  AND point.distance(l.geo, point({latitude: $latitude, longitude: $longitude})) <= $radius_m
RETURN DISTINCT coalesce(e.event_id, e.event_key) AS event_id,
       l.lat AS latitude, l.lon AS longitude,
       toString(date(e.timeline_at)) AS event_date, e.time_basis AS time_basis,
       e.codebook_type AS codebook_type
""",
            {
                "derivations": sorted(
                    {
                        revision
                        for scope in index.scopes.values()
                        for revision in scope.compatible_derivation_revisions
                    }
                ),
                "types": sorted(CONFLICT_CODEBOOK_TYPES),
                "start": (observed - window).isoformat() + "T00:00:00Z",
                "end": (observed + window + timedelta(days=1)).isoformat() + "T00:00:00Z",
                "latitude": observation["latitude"],
                "longitude": observation["longitude"],
                "radius_m": self.settings.correlation_radius_km * 1000,
            },
        )

    async def _write_proximity(
        self,
        client,
        *,
        firms_url,
        event_id,
        score,
        distance_km,
        days_diff,
        time_basis,
    ) -> int:
        rows = await self._graph_rows(
            client,
            """
MATCH (f:Document {url: $firms_url})
MATCH (e:Event)
WHERE e.event_id = $event_id OR e.event_key = $event_id
MERGE (f)-[r:SPATIOTEMPORAL_PROXIMITY {method: 'distance-time-v1'}]->(e)
SET r.score = $score, r.distance_km = $distance_km, r.days_diff = $days_diff,
    r.event_time_basis = $time_basis, r.updated_at = datetime()
RETURN count(r) AS written
""",
            {
                "firms_url": firms_url,
                "event_id": event_id,
                "score": score,
                "distance_km": distance_km,
                "days_diff": days_diff,
                "time_basis": time_basis,
            },
        )
        written = int(rows[0]["written"])
        if written != 1:
            raise RuntimeError("observation and event not linked uniquely")
        return written

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one correlation pass."""
        last_run_epoch = await self._get_last_run_epoch()
        log.info("correlation.run.start", last_run_epoch=last_run_epoch)

        replay_from = min(last_run_epoch, datetime.now(UTC).timestamp() - 7 * 86400)
        firms_filter = build_firms_filter(replay_from)
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
                if not f_url or not f_date:
                    log.warning("correlation.observation_missing_identity_or_time")
                    continue
                try:
                    conflict_points = await self._event_candidates(client, p)
                except Exception:
                    log.exception("correlation.event_lookup_failed", firms_url=f_url)
                    failed_pairs.append((f_url, "lookup"))
                    continue

                for a in conflict_points:
                    a_lat: float = a["latitude"]
                    a_lon: float = a["longitude"]
                    a_date: str = _extract_event_date(a)
                    event_id = a.get("event_id")
                    if not event_id or not a.get("event_date"):
                        continue
                    a_url = str(event_id)
                    a_codebook_type: str = a.get("codebook_type", "")

                    # Precise distance check
                    dist_km = haversine_km(f_lat, f_lon, a_lat, a_lon)
                    if dist_km > self.settings.correlation_radius_km:
                        continue

                    # Time window check
                    if (
                        f_date
                        and a_date
                        and not passes_time_filter(
                            f_date,
                            a_date,
                            window_days=self.settings.correlation_time_window_days,
                        )
                    ):
                        continue

                    # Compute score
                    days_diff = 0
                    if f_date and a_date:
                        days_diff = abs(
                            (date.fromisoformat(a_date) - date.fromisoformat(f_date)).days
                        )

                    score = correlation_score(
                        distance_km=dist_km,
                        days_diff=days_diff,
                        conflict_codebook_type=a_codebook_type,
                        firms_confidence=f_confidence,
                    )

                    if score < self.settings.correlation_min_score:
                        continue

                    # Write to Neo4j
                    try:
                        await self._write_proximity(
                            client=client,
                            firms_url=f_url,
                            event_id=event_id,
                            score=score,
                            distance_km=dist_km,
                            days_diff=days_diff,
                            time_basis=a.get("time_basis"),
                        )
                        log.info(
                            "correlation.proximity_written",
                            firms_url=f_url,
                            event_id=event_id,
                            score=score,
                            distance_km=dist_km,
                        )
                    except Exception:
                        log.exception(
                            "correlation.write_failed",
                            firms_url=f_url,
                            event_id=event_id,
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

    async def close(self) -> None:
        await asyncio.to_thread(self.qdrant.close)
