"""USGS Earthquake collector with nuclear test site proximity enrichment."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from config import Settings
from feeds.base import BaseCollector
from feeds.geo import haversine_km
from pipeline import ExtractionConfigError, ExtractionTransientError, process_item

log = structlog.get_logger(__name__)


def _safe_feature_id(feature: object) -> str | None:
    if not isinstance(feature, Mapping):
        return None
    value = feature.get("id")
    return str(value)[:100] if isinstance(value, (str, int)) else None

USGS_FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"

# Radius around a nuclear test site that triggers enrichment
PROXIMITY_RADIUS_KM = 100.0

# Known nuclear test sites: name -> (lat, lon)
NUCLEAR_TEST_SITES: dict[str, tuple[float, float]] = {
    "Punggye-ri (DPRK)": (41.28, 129.08),
    "Lop Nur (China)": (41.60, 88.33),
    "Novaya Zemlya (Russia)": (73.40, 54.90),
    "Nevada NTS (USA)": (37.12, -116.04),
    "Semipalatinsk (Kazakhstan)": (50.07, 78.43),
}


# ---------------------------------------------------------------------------
# Pure utility functions (importable by tests without instantiating collector)
# ---------------------------------------------------------------------------


def concern_score(magnitude: float, distance_km: float, depth_km: float) -> float:
    """Heuristic concern score 0–100 for a seismic event near a nuclear test site.

    Formula:
        mag_factor   = (mag / 9.0) * 0.45
        prox_factor  = max(0, (40 - dist) / 40) * 0.35
        depth_factor = max(0, 1 - depth / 10) * 0.15

    Score = (mag_factor + prox_factor + depth_factor) * 100
    """
    mag_factor = (min(magnitude, 9.0) / 9.0) * 0.45
    prox_factor = max(0.0, (40.0 - min(distance_km, 40.0)) / 40.0) * 0.35
    depth_factor = max(0.0, 1.0 - depth_km / 10.0) * 0.15
    return round((mag_factor + prox_factor + depth_factor) * 100.0, 2)


def concern_level(score: float) -> str | None:
    """Map a numeric concern score to a human-readable level.

    Returns None when the score is below 25 (not noteworthy).
    """
    if score >= 75:
        return "critical"
    if score >= 50:
        return "elevated"
    if score >= 25:
        return "moderate"
    return None


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class USGSCollector(BaseCollector):
    """Fetch USGS M4.5+ earthquakes and enrich events near nuclear test sites."""

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        super().__init__(settings, redis_client)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _nearest_test_site(
        self, lat: float, lon: float
    ) -> tuple[str, float] | tuple[None, None]:
        """Return (site_name, distance_km) for the closest nuclear test site within
        PROXIMITY_RADIUS_KM, or (None, None) if none are within range."""
        best_name: str | None = None
        best_dist = float("inf")
        for name, (slat, slon) in NUCLEAR_TEST_SITES.items():
            d = haversine_km(lat, lon, slat, slon)
            if d < best_dist:
                best_dist = d
                best_name = name
        if best_dist <= PROXIMITY_RADIUS_KM:
            return best_name, round(best_dist, 2)
        return None, None

    def _parse_features(self, features: list[dict]) -> list[dict]:
        """Parse GeoJSON feature list into normalised event dicts."""
        results: list[dict] = []
        for feature in features:
            try:
                if not isinstance(feature, Mapping):
                    raise ValueError("feature must be an object")
                props = feature.get("properties")
                geo = feature.get("geometry")
                if not isinstance(props, Mapping) or not isinstance(geo, Mapping):
                    raise ValueError("feature properties and geometry must be objects")
                coords = geo.get("coordinates")
                if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                    raise ValueError("coordinates must contain longitude and latitude")
                raw_lon, raw_lat = coords[0], coords[1]
                if any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in (raw_lon, raw_lat)
                ):
                    raise ValueError("coordinates must be numeric")
                lon = float(raw_lon)
                lat = float(raw_lat)
                if not math.isfinite(lon) or not math.isfinite(lat):
                    raise ValueError("coordinates must be finite")
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValueError("coordinates out of range")
                raw_depth = coords[2] if len(coords) > 2 else None
                if raw_depth is not None and (
                    isinstance(raw_depth, bool) or not isinstance(raw_depth, (int, float))
                ):
                    raise ValueError("depth must be numeric or null")
                depth_km = None if raw_depth is None else float(raw_depth)
                if depth_km is not None and not math.isfinite(depth_km):
                    raise ValueError("depth must be finite")
            except (TypeError, ValueError, IndexError, OverflowError):
                log.warning("usgs_bad_geometry", feature_id=_safe_feature_id(feature))
                continue

            try:
                raw_magnitude = props.get("mag")
                if (
                    isinstance(raw_magnitude, bool)
                    or not isinstance(raw_magnitude, (int, float))
                ):
                    raise ValueError("magnitude missing or not numeric")
                magnitude = float(raw_magnitude)
                if not math.isfinite(magnitude):
                    raise ValueError("magnitude must be finite")
            except (TypeError, ValueError, OverflowError):
                log.warning("usgs_bad_magnitude", feature_id=_safe_feature_id(feature))
                continue

            try:
                raw_time = props.get("time")
                if (
                    isinstance(raw_time, bool)
                    or not isinstance(raw_time, (int, float, str))
                    or (isinstance(raw_time, str) and not raw_time.strip())
                ):
                    raise ValueError("time missing or not numeric")
                ts_ms = float(raw_time)
                if not math.isfinite(ts_ms):
                    raise ValueError("time must be finite milliseconds")
                event_time = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                log.warning("usgs_bad_time", feature_id=_safe_feature_id(feature))
                continue

            site_name, site_dist = self._nearest_test_site(lat, lon)

            # Compute enrichment only for events near a test site
            cscore: float | None = None
            clevel: str | None = None
            if site_name is not None and site_dist is not None and depth_km is not None:
                cscore = concern_score(magnitude, site_dist, depth_km)
                clevel = concern_level(cscore)

            results.append(
                {
                    "source": "usgs",
                    "usgs_id": feature.get("id", ""),
                    "magnitude": magnitude,
                    "place": props.get("place", ""),
                    "event_time": event_time,
                    "latitude": lat,
                    "longitude": lon,
                    "depth_km": depth_km,
                    "url": props.get("url", ""),
                    "nearest_test_site": site_name,
                    "distance_to_site_km": site_dist,
                    "concern_score": cscore,
                    "concern_level": clevel,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Neo4j nuclear enrichment write (eventual consistency)
    # ------------------------------------------------------------------

    async def _write_near_test_site(self, event: dict) -> int:
        """Write NEAR_TEST_SITE relationship to Neo4j after process_item() completes.

        This is intentionally NOT atomic with process_item() — the relationship
        enrichment is a separate concern that runs after the core Document/Event
        graph has been written. Eventual consistency is acceptable here: the event
        is already in the graph; the proximity annotation arrives shortly after.
        """
        site_name = event["nearest_test_site"]
        if not site_name:
            return 0

        cypher = """
MERGE (nts:NuclearTestSite {name: $site_name})
ON CREATE SET nts.latitude  = $site_lat,
              nts.longitude = $site_lon
WITH nts
MATCH (d:Document {url: $event_url})-[:DESCRIBES]->(e:Event)
MERGE (e)-[r:NEAR_TEST_SITE]->(nts)
ON CREATE SET r.distance_km   = $distance_km,
              r.concern_score  = $concern_score,
              r.concern_level  = $concern_level
RETURN count(r) AS written
"""
        site_lat, site_lon = NUCLEAR_TEST_SITES[site_name]
        params = {
            "site_name": site_name,
            "site_lat": site_lat,
            "site_lon": site_lon,
            "event_url": event["url"],
            "distance_km": event["distance_to_site_km"],
            "concern_score": event["concern_score"],
            "concern_level": event["concern_level"],
        }

        neo4j_tx_url = f"{self.settings.neo4j_http_url}/db/neo4j/tx/commit"
        payload = {"statements": [{"statement": cypher, "parameters": params}]}
        auth = (self.settings.neo4j_user, self.settings.neo4j_password)

        try:
            resp = await self.http.post(neo4j_tx_url, json=payload, auth=auth)
            resp.raise_for_status()
            errors = resp.json().get("errors", [])
            if errors:
                log.warning(
                    "usgs_neo4j_near_test_site_errors",
                    errors=errors,
                    usgs_id=event["usgs_id"],
                )
            else:
                written = int(resp.json()["results"][0]["data"][0]["row"][0])
                if not written:
                    log.warning("usgs_neo4j_event_missing", usgs_id=event["usgs_id"])
                    return 0
                log.debug(
                    "usgs_neo4j_near_test_site_written",
                    usgs_id=event["usgs_id"],
                    site=site_name,
                )
                return written
        except Exception as exc:
            log.warning(
                "usgs_neo4j_near_test_site_failed",
                usgs_id=event["usgs_id"],
                site=site_name,
                error=str(exc),
            )

        return 0

    # ------------------------------------------------------------------
    # Main collect loop
    # ------------------------------------------------------------------

    async def collect(self) -> None:
        log.info("usgs_collection_started")
        start = time.monotonic()

        await self._ensure_collection()

        try:
            resp = await self.http.get(USGS_FEED_URL)
            resp.raise_for_status()
        except Exception as exc:
            log.error("usgs_fetch_failed", error=str(exc))
            return

        features = resp.json().get("features", [])
        events = self._parse_features(features)
        log.info("usgs_features_parsed", total=len(events))

        total_new = 0
        points: list[PointStruct] = []

        for event in events:
            usgs_id = event["usgs_id"]
            if not usgs_id:
                continue

            chash = self._content_hash(usgs_id)
            pid = self._point_id(chash)

            if await self._dedup_check(pid):
                # Proximity is a separate idempotent write; Qdrant dedup must not
                # hide an earlier missing Event or a transient Neo4j failure.
                if event["nearest_test_site"]:
                    await self._write_near_test_site(event)
                continue

            title = (
                f"M{event['magnitude']} earthquake {event['place']}"
                if event["place"]
                else f"M{event['magnitude']} earthquake"
            )
            if event["nearest_test_site"]:
                title += f" — {event['distance_to_site_km']} km from {event['nearest_test_site']}"

            depth_text = (
                f"{event['depth_km']} km" if event["depth_km"] is not None else "unknown"
            )
            embed_text = f"{title}. Depth: {depth_text}, Time: {event['event_time']}."
            if event["concern_level"]:
                embed_text += f" Nuclear concern level: {event['concern_level']}."

            # Intelligence extraction. Transient/config errors skip Qdrant upsert
            # so the event is retried on the next source re-fetch (dedup doesn't trip).
            try:
                await process_item(
                    title=title,
                    text=embed_text,
                    url=event["url"],
                    source="usgs",
                    source_evidence={**event, "source": "usgs"},
                    settings=self.settings,
                    redis_client=self.redis,
                    occurred_at=event.get("event_time"),
                )
            except ExtractionTransientError as exc:
                log.warning("extraction_skipped_transient", url=event["url"], error=str(exc))
                continue
            except ExtractionConfigError as exc:
                log.error("extraction_skipped_config", url=event["url"], error=str(exc))
                continue

            # Nuclear proximity (eventual consistency, see docstring)
            if event["nearest_test_site"]:
                await self._write_near_test_site(event)

            try:
                point = await self._build_point(embed_text, event, chash)
                points.append(point)
            except Exception as exc:
                log.warning("usgs_embed_failed", usgs_id=usgs_id, error=str(exc))

        await self._batch_upsert(points)
        total_new = len(points)

        elapsed = round(time.monotonic() - start, 2)
        log.info(
            "usgs_collection_finished",
            total_new=total_new,
            total_fetched=len(events),
            elapsed_seconds=elapsed,
        )
