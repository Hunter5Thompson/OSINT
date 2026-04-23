"""UCDP GED (Georeferenced Event Dataset) conflict data collector."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from qdrant_client.models import PointStruct

from config import Settings
from feeds.base import BaseCollector
from pipeline import ExtractionConfigError, ExtractionTransientError, process_item

log = structlog.get_logger(__name__)

UCDP_BASE_URL = "https://ucdpapi.pcr.uu.se/api/gedevents"
UCDP_TIMEOUT = 90.0
PAGE_SIZE = 100
MAX_PAGES = 3

VIOLENCE_TYPES: dict[int, str] = {
    1: "state-based",
    2: "non-state",
    3: "one-sided",
}


class UCDPCollector(BaseCollector):
    """Fetch conflict events from UCDP GED API and ingest into Qdrant + Neo4j."""

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        super().__init__(settings, redis_client)
        self._api_version: str | None = None

    def _version_candidates(self) -> list[str]:
        """Return API version candidates to try, most recent first.

        GED yearly releases (e.g. 25.1) lag the calendar year.
        GED Candidate monthly releases (e.g. 26.0.2) have more current data.
        We try candidate (monthly) first, then yearly, newest to oldest.
        """
        year = datetime.now(UTC).year
        yy = year - 2000  # e.g. 26 for 2026
        month = datetime.now(UTC).month
        candidates = [
            # GED Candidate: current year, latest month
            f"{yy}.0.{month}",
            f"{yy}.0.{month - 1}" if month > 1 else f"{yy - 1}.0.12",
            # GED yearly: previous year (most likely available)
            f"{yy - 1}.1",
            f"{yy - 2}.1",
        ]
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    async def _discover_version(self) -> str | None:
        """Try version candidates sequentially; return the first that responds."""
        headers = self._auth_headers()
        if not headers:
            log.error("ucdp_access_token_missing")
            return None
        for version in self._version_candidates():
            url = f"{UCDP_BASE_URL}/{version}"
            try:
                resp = await self.http.get(
                    url,
                    params={"pagesize": 1, "page": 1},
                    headers=headers,
                    timeout=UCDP_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("Result"):
                        log.info("ucdp_version_discovered", version=version)
                        self._api_version = version
                        return version
            except Exception as exc:
                log.debug("ucdp_version_probe_failed", version=version, error=str(exc))
        log.warning("ucdp_version_discovery_failed")
        return None

    def _build_url(self, version: str, page: int = 1) -> str:
        return f"{UCDP_BASE_URL}/{version}"

    def _build_params(self, page: int = 1) -> dict:
        today = datetime.now(UTC).date()
        date_from = today - timedelta(days=365)
        params: dict[str, Any] = {
            "StartDate": date_from.isoformat(),
            "EndDate": today.isoformat(),
            "pagesize": PAGE_SIZE,
            "page": page,
        }
        return params

    def _auth_headers(self) -> dict[str, str]:
        token = getattr(self.settings, "ucdp_access_token", "")
        if token:
            return {"x-ucdp-access-token": token}
        return {}

    def _parse_event(self, raw: dict) -> dict:
        lat_str = raw.get("latitude", "")
        lon_str = raw.get("longitude", "")
        vtype = int(raw.get("type_of_violence", 0) or 0)
        return {
            "source": "ucdp",
            "ucdp_id": str(raw.get("id", "")),
            "title": (
                f"{VIOLENCE_TYPES.get(vtype, 'conflict')} conflict in {raw.get('country', '')}"
            ),
            "url": f"https://ucdp.uu.se/event/{raw.get('id', '')}",
            "violence_type": vtype,
            "violence_type_label": VIOLENCE_TYPES.get(vtype, "unknown"),
            "best_estimate": int(raw.get("best", 0) or 0),
            "low_estimate": int(raw.get("low", 0) or 0),
            "high_estimate": int(raw.get("high", 0) or 0),
            "country": raw.get("country", ""),
            "region": raw.get("region", ""),
            "latitude": float(lat_str) if lat_str else None,
            "longitude": float(lon_str) if lon_str else None,
            "date_start": raw.get("date_start", ""),
            "date_end": raw.get("date_end", ""),
            "side_a": raw.get("side_a", ""),
            "side_b": raw.get("side_b", ""),
            "source_article": raw.get("source_article", ""),
        }

    async def collect(self) -> None:
        log.info("ucdp_collection_started")
        start = time.monotonic()

        await self._ensure_collection()

        version = await self._discover_version()
        if version is None:
            log.error("ucdp_no_valid_version_found")
            return

        base_url = self._build_url(version)
        headers = self._auth_headers()

        total_new = 0
        last_resp: dict = {}

        for page in range(1, MAX_PAGES + 1):
            params = self._build_params(page=page)
            try:
                resp = await self.http.get(
                    base_url,
                    params=params,
                    headers=headers,
                    timeout=UCDP_TIMEOUT,
                )
                resp.raise_for_status()
            except Exception as exc:
                log.error("ucdp_fetch_failed", page=page, error=str(exc))
                break

            last_resp = resp.json()
            results = last_resp.get("Result", [])
            if not results:
                break

            points: list[PointStruct] = []
            for raw_event in results:
                event_id = str(raw_event.get("id", ""))
                if not event_id:
                    continue

                chash = self._content_hash(event_id)
                pid = self._point_id(chash)

                if await self._dedup_check(pid):
                    continue

                payload = self._parse_event(raw_event)
                source_text = raw_event.get("source_article", "")
                embed_text = f"{payload['title']}. {source_text}"[:2000]

                # Intelligence extraction. Transient/config errors skip Qdrant
                # upsert so the event is retried on the next source re-fetch.
                try:
                    await process_item(
                        title=payload["title"],
                        text=embed_text,
                        url=payload["url"],
                        source="ucdp",
                        settings=self.settings,
                        redis_client=self.redis,
                    )
                except ExtractionTransientError as exc:
                    log.warning(
                        "extraction_skipped_transient",
                        url=payload["url"],
                        error=str(exc),
                    )
                    continue
                except ExtractionConfigError as exc:
                    log.error(
                        "extraction_skipped_config",
                        url=payload["url"],
                        error=str(exc),
                    )
                    continue

                try:
                    point = await self._build_point(embed_text, payload, chash)
                    points.append(point)
                except Exception as exc:
                    log.warning("ucdp_embed_failed", event_id=event_id, error=str(exc))

            await self._batch_upsert(points)
            total_new += len(points)
            log.info("ucdp_page_ingested", page=page, new=len(points), fetched=len(results))

            if len(results) < PAGE_SIZE:
                break

            await asyncio.sleep(0.5)

        total_count = last_resp.get("TotalCount", 0)
        if total_count > MAX_PAGES * PAGE_SIZE:
            log.warning(
                "ucdp_data_truncated",
                total_count=total_count,
                max_fetched=MAX_PAGES * PAGE_SIZE,
            )

        elapsed = round(time.monotonic() - start, 2)
        log.info("ucdp_collection_finished", total_new=total_new, elapsed_seconds=elapsed)
