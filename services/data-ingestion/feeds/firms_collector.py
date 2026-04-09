"""NASA FIRMS (Fire Information for Resource Management System) thermal anomaly collector."""

from __future__ import annotations

import asyncio
import csv
import io
import time
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from config import Settings
from feeds.base import BaseCollector
from pipeline import process_item

log = structlog.get_logger(__name__)

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_DAYS = 1  # last N days of data per request

# Geopolitical hotspot bounding boxes: "west,south,east,north"
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

# Heuristic thresholds for explosion detection
_EXPLOSION_FRP_THRESHOLD = 80.0
_EXPLOSION_BRIGHTNESS_THRESHOLD = 380.0


def is_possible_explosion(frp: float, brightness: float) -> bool:
    """Return True when fire radiative power + brightness exceed explosion thresholds.

    Thresholds: frp > 80 MW and brightness > 380 K.
    Natural fires rarely exceed both simultaneously in small scan areas.
    """
    return frp > _EXPLOSION_FRP_THRESHOLD and brightness > _EXPLOSION_BRIGHTNESS_THRESHOLD


class FIRMSCollector(BaseCollector):
    """Fetch NASA FIRMS VIIRS NRT thermal anomalies and ingest into Qdrant + Neo4j."""

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        super().__init__(settings, redis_client)

    # ------------------------------------------------------------------
    # Public helpers (also used by tests)
    # ------------------------------------------------------------------

    def _firms_content_hash(
        self,
        lat: float,
        lon: float,
        acq_date: str,
        acq_time: str,
    ) -> str:
        """Deterministic dedup key: location + time, satellite-agnostic."""
        key = f"{lat:.4f}|{lon:.4f}|{acq_date}|{acq_time}"
        return self._content_hash(key)

    def _parse_csv(self, text: str, bbox_name: str) -> list[dict]:
        """Parse FIRMS CSV response into a list of normalised event dicts."""
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict] = []
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                frp = float(row.get("frp") or 0)
                brightness = float(row.get("bright_ti4") or 0)
                rows.append(
                    {
                        "source": "firms",
                        "bbox_name": bbox_name,
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
                        "possible_explosion": is_possible_explosion(frp, brightness),
                    }
                )
            except (ValueError, KeyError) as exc:
                log.warning("firms_row_parse_error", bbox=bbox_name, error=str(exc))
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
                    chash = self._firms_content_hash(
                        row["latitude"], row["longitude"], row["acq_date"], row["acq_time"]
                    )
                    pid = self._point_id(chash)

                    if await self._dedup_check(pid):
                        continue

                    explosion_flag = " [POSSIBLE EXPLOSION]" if row["possible_explosion"] else ""
                    title = (
                        f"FIRMS thermal anomaly at {row['latitude']:.4f},{row['longitude']:.4f}"
                        f" ({bbox_name}){explosion_flag}"
                    )
                    embed_text = (
                        f"{title}. FRP: {row['frp']} MW, Brightness: {row['brightness']} K, "
                        f"Confidence: {row['confidence']}, "
                        f"Date: {row['acq_date']} {row['acq_time']}."
                    )

                    await process_item(
                        title=title,
                        text=embed_text,
                        url=(
                            f"https://firms.modaps.eosdis.nasa.gov/map/#d:{row['acq_date']};"
                            f"@{row['longitude']:.4f},{row['latitude']:.4f},10z"
                        ),
                        source="firms",
                        settings=self.settings,
                        redis_client=self.redis,
                    )

                    try:
                        point = await self._build_point(embed_text, row, chash)
                        points.append(point)
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
