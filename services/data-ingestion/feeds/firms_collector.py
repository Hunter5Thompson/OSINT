"""NASA FIRMS (Fire Information for Resource Management System) thermal anomaly collector."""

from __future__ import annotations

import asyncio
import csv
import io
import re
import time
from datetime import UTC, datetime
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from config import Settings
from feeds.base import BaseCollector
from graph_integrity.spatial_normalizer import (
    RawLocationIdentity,
    SpatialNormalizationIndex,
    load_active_normalization_index,
    normalize_location,
)
from pipeline import ExtractionConfigError, ExtractionTransientError, process_item

log = structlog.get_logger(__name__)

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_DAYS = 1  # last N days of data per request


def _firms_observed_at(acq_date: str, acq_time: str | int | None) -> str | None:
    """Validated UTC minute; unknown/invalid source time has no observation identity."""
    if not isinstance(acq_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", acq_date):
        return None
    if type(acq_time) not in (str, int) or not re.fullmatch(r"[0-9]{1,4}", str(acq_time)):
        return None
    hhmm = str(acq_time).zfill(4)
    try:
        return (
            datetime.strptime(f"{acq_date}T{hhmm}", "%Y-%m-%dT%H%M").replace(tzinfo=UTC).isoformat()
        )
    except ValueError:
        return None


# Fetch areas around geopolitical hotspots: "west,south,east,north". They
# overlap and are not countries: a pixel's place comes from the spatial catalog.
FIRMS_BBOXES: dict[str, str] = {
    "ukraine": "22.0,44.0,40.0,52.5",
    "russia": "30.0,50.0,60.0,70.0",
    "iran": "44.0,25.0,63.5,39.8",
    "israel_gaza": "34.0,29.5,35.9,33.5",
    "syria": "35.5,32.0,42.5,37.5",
    "taiwan": "119.0,21.5,122.5,25.5",
    "north_korea": "124.0,37.5,130.5,42.5",
    "saudi_arabia": "36.5,16.0,55.5,32.2",
    "turkey": "26.0,36.0,44.8,42.2",
}

FIRMS_SATELLITES: list[str] = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
]


class FIRMSCollector(BaseCollector):
    """Fetch NASA FIRMS VIIRS NRT thermal anomalies and ingest into Qdrant + Neo4j."""

    def __init__(
        self,
        settings: Settings,
        redis_client: Any | None = None,
        *,
        spatial_index: SpatialNormalizationIndex | None = None,
    ) -> None:
        super().__init__(settings, redis_client)
        self._spatial_index = spatial_index

    def _country_iso3(self, lat: float, lon: float) -> str | None:
        if self._spatial_index is None:
            self._spatial_index = load_active_normalization_index(
                self.settings.spatial_catalog_path,
                crosswalk_path=self.settings.spatial_country_crosswalk_path,
            )
        return normalize_location(
            RawLocationIdentity(latitude=lat, longitude=lon),
            self._spatial_index,
        ).country_iso3

    # ------------------------------------------------------------------
    # Public helpers (also used by tests)
    # ------------------------------------------------------------------

    def _firms_content_hash(
        self,
        lat: float,
        lon: float,
        acq_date: str,
        acq_time: str | int | None,
    ) -> str:
        """Deterministic dedup key: location + time, satellite-agnostic."""
        observed = _firms_observed_at(acq_date, acq_time)
        if observed is None:
            raise ValueError("FIRMS identity requires a valid acquisition minute")
        hhmm = observed[11:13] + observed[14:16]
        key = f"{lat:.4f}|{lon:.4f}|{observed[:10]}|{hhmm}"
        return self._content_hash(key)

    def _identity_hashes(
        self, lat: float, lon: float, acq_date: str, acq_time: str | int | None
    ) -> tuple[str, ...]:
        """Canonical first, then at most three older valid zero-padding aliases."""
        canonical = self._firms_content_hash(lat, lon, acq_date, acq_time)
        unpadded = str(int(str(acq_time)))  # canonical validation has already succeeded
        aliases = [
            self._content_hash(f"{lat:.4f}|{lon:.4f}|{acq_date}|{unpadded.zfill(width)}")
            for width in range(1, 5)
        ]
        return tuple(dict.fromkeys([canonical, *aliases]))

    async def _dedup_check(self, point_id: int, legacy_ids: tuple[int, ...] = ()) -> bool:
        """One database lookup covers canonical and retained legacy identities."""
        existing = await asyncio.to_thread(
            self.qdrant.retrieve,
            collection_name=self.settings.qdrant_collection,
            ids=list(dict.fromkeys((point_id, *legacy_ids))),
        )
        return len(existing) > 0

    def _parse_csv(self, text: str, fetch_area: str) -> list[dict]:
        """Parse FIRMS CSV response into a list of normalised event dicts."""
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict] = []
        for row in reader:
            try:
                if _firms_observed_at(row.get("acq_date", ""), row.get("acq_time")) is None:
                    raise ValueError("FIRMS acquisition minute is invalid or missing")
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                frp = float(row.get("frp") or 0)
                # VIIRS I4 saturates near 367 K, so brightness cannot separate
                # explosions from large fires; no explosion flag is derived.
                brightness = float(row.get("bright_ti4") or 0)
                rows.append(
                    {
                        "source": "firms",
                        "fetch_area": fetch_area,
                        "latitude": lat,
                        "longitude": lon,
                        "brightness": brightness,
                        "frp": frp,
                        "acq_date": row.get("acq_date", ""),
                        "acq_time": row.get("acq_time", ""),
                        "satellite": row.get("satellite", ""),
                        "confidence": row.get("confidence", ""),
                        "daynight": row.get("daynight", ""),
                        "scan": float(row.get("scan") or 0),
                        "track": float(row.get("track") or 0),
                    }
                )
            except (ValueError, KeyError) as exc:
                log.warning("firms_row_parse_error", bbox=fetch_area, error=str(exc))
        return rows

    # ------------------------------------------------------------------
    # Internal fetch
    # ------------------------------------------------------------------

    def _build_url(self, api_key: str, satellite: str, bbox: str) -> str:
        return f"{FIRMS_BASE_URL}/{api_key}/{satellite}/{bbox}/{FIRMS_DAYS}"

    async def _fetch_csv(self, satellite: str, bbox_name: str, bbox: str) -> str | None:
        api_key = self.settings.nasa_earthdata_key
        if not api_key:
            log.warning("firms_api_key_missing")
            return None
        url = self._build_url(api_key, satellite, bbox)
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            log.error("firms_fetch_failed", satellite=satellite, bbox=bbox_name, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Main collect loop
    # ------------------------------------------------------------------

    async def collect(self) -> None:
        log.info("firms_collection_started")
        start = time.monotonic()

        if not self.settings.nasa_earthdata_key:
            log.warning("firms_api_key_missing_skip")
            return

        await self._ensure_collection()

        total_new = 0
        first_request = True
        seen_ids: set[int] = set()

        for satellite in FIRMS_SATELLITES:
            for bbox_name, bbox in FIRMS_BBOXES.items():
                if not first_request:
                    await asyncio.sleep(6)  # NASA rate limit: 6s between requests
                first_request = False

                csv_text = await self._fetch_csv(satellite, bbox_name, bbox)
                if not csv_text:
                    continue

                rows = self._parse_csv(csv_text, bbox_name)
                if not rows:
                    log.debug("firms_no_rows", satellite=satellite, bbox=bbox_name)
                    continue

                points: list[PointStruct] = []
                for row in rows:
                    hashes = self._identity_hashes(
                        row["latitude"], row["longitude"], row["acq_date"], row["acq_time"]
                    )
                    chash = hashes[0]
                    pid = self._point_id(chash)
                    if pid in seen_ids or await self._dedup_check(
                        pid, tuple(self._point_id(value) for value in hashes[1:])
                    ):
                        continue

                    row["identity_schema"] = "firms-location-hhmm-v2"

                    row["country_iso3"] = self._country_iso3(row["latitude"], row["longitude"])
                    title = (
                        f"FIRMS thermal anomaly at {row['latitude']:.4f},{row['longitude']:.4f}"
                        f" ({row['country_iso3'] or 'country unresolved'})"
                    )
                    embed_text = (
                        f"{title}. FRP: {row['frp']} MW, Brightness: {row['brightness']} K, "
                        f"Confidence: {row['confidence']}, "
                        f"Date: {row['acq_date']} {row['acq_time']}."
                    )

                    url = (
                        f"https://firms.modaps.eosdis.nasa.gov/map/#d:{row['acq_date']};"
                        f"@{row['longitude']:.4f},{row['latitude']:.4f},10z"
                    )
                    row["url"] = url
                    # Intelligence extraction. Transient/config errors skip Qdrant
                    # upsert so the row is retried on the next source re-fetch
                    # (Hash-Dedup doesn't trip).
                    observed = _firms_observed_at(row.get("acq_date", ""), row.get("acq_time"))
                    row["observed_at"] = observed
                    try:
                        await process_item(
                            title=title,
                            text=embed_text,
                            url=url,
                            source="firms",
                            source_evidence={**row, "source": "firms", "content_hash": chash},
                            settings=self.settings,
                            redis_client=self.redis,
                            observed_at=observed,
                        )
                    except ExtractionTransientError as exc:
                        log.warning("extraction_skipped_transient", url=url, error=str(exc))
                        continue
                    except ExtractionConfigError as exc:
                        log.error("extraction_skipped_config", url=url, error=str(exc))
                        continue

                    try:
                        point = await self._build_point(embed_text, row, chash)
                        points.append(point)
                        seen_ids.add(pid)
                    except Exception as exc:
                        log.warning(
                            "firms_embed_failed",
                            lat=row["latitude"],
                            lon=row["longitude"],
                            error=str(exc),
                        )

                await self._batch_upsert(points)
                total_new += len(points)
                log.info(
                    "firms_bbox_ingested",
                    satellite=satellite,
                    bbox=bbox_name,
                    new=len(points),
                    fetched=len(rows),
                )

        elapsed = round(time.monotonic() - start, 2)
        log.info("firms_collection_finished", total_new=total_new, elapsed_seconds=elapsed)
