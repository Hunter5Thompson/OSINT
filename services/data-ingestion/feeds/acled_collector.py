"""ACLED Armed Conflict Location & Event Data collector."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import structlog
from qdrant_client.models import PointStruct

from config import Settings
from feeds.base import BaseCollector
from pipeline import process_item

log = structlog.get_logger(__name__)

ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_URL = "https://acleddata.com/api/acled/read"
ACLED_EVENT_TYPES = "Battles|Explosions/Remote violence|Violence against civilians"


class ACLEDCollector(BaseCollector):
    """Fetch conflict events from ACLED and ingest into Qdrant + Neo4j."""

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        super().__init__(settings, redis_client)
        self._token: str | None = None

    async def _authenticate(self) -> None:
        resp = await self.http.post(
            ACLED_TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": "acled",
                "username": self.settings.acled_email,
                "password": self.settings.acled_password,
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        log.info("acled_authenticated")

    def _build_query_url(self, page: int = 1) -> str:
        today = datetime.now(UTC).date()
        date_from = today - timedelta(days=30)
        params = {
            "event_type": ACLED_EVENT_TYPES,
            "event_date": f"{date_from.isoformat()}|{today.isoformat()}",
            "event_date_where": "BETWEEN",
            "limit": "500",
            "page": str(page),
            "_format": "json",
        }
        return f"{ACLED_API_URL}?{urlencode(params)}"

    def _parse_event(self, raw: dict) -> dict:
        lat_str = raw.get("latitude", "")
        lon_str = raw.get("longitude", "")
        return {
            "source": "acled",
            "title": (
                f"{raw.get('event_type', '')} in "
                f"{raw.get('admin1', '')}, {raw.get('country', '')}"
            ),
            "url": f"https://acleddata.com/data/{raw.get('event_id_cnty', '')}",
            "acled_event_id": raw.get("event_id_cnty", ""),
            "event_type": raw.get("event_type", ""),
            "sub_event_type": raw.get("sub_event_type", ""),
            "fatalities": int(raw.get("fatalities", 0) or 0),
            "actor1": raw.get("actor1", ""),
            "actor2": raw.get("actor2", ""),
            "admin1": raw.get("admin1", ""),
            "country": raw.get("country", ""),
            "latitude": float(lat_str) if lat_str else None,
            "longitude": float(lon_str) if lon_str else None,
            "event_date": raw.get("event_date", ""),
        }

    async def collect(self) -> None:
        log.info("acled_collection_started")
        start = time.monotonic()

        if not self.settings.acled_email or not self.settings.acled_password:
            log.warning("acled_credentials_missing")
            return

        await self._ensure_collection()
        await self._authenticate()

        total_new = 0
        page = 1

        while True:
            url = self._build_query_url(page=page)
            try:
                resp = await self.http.get(
                    url,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if resp.status_code == 401:
                    log.info("acled_token_refresh")
                    await self._authenticate()
                    resp = await self.http.get(
                        url,
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                resp.raise_for_status()
            except Exception as exc:
                log.error("acled_fetch_failed", page=page, error=str(exc))
                break

            data = resp.json().get("data", [])
            if not data:
                break

            points: list[PointStruct] = []
            for raw_event in data:
                event_id = raw_event.get("event_id_cnty", "")
                if not event_id:
                    continue

                chash = self._content_hash(event_id)
                pid = self._point_id(chash)

                if await self._dedup_check(pid):
                    continue

                payload = self._parse_event(raw_event)
                notes = raw_event.get("notes", "")
                embed_text = f"{payload['title']}. {notes}"[:2000]

                await process_item(
                    title=payload["title"],
                    text=embed_text,
                    url=payload["url"],
                    source="acled",
                    settings=self.settings,
                    redis_client=self.redis,
                )

                try:
                    point = await self._build_point(embed_text, payload, chash)
                    points.append(point)
                except Exception as exc:
                    log.warning("acled_embed_failed", event_id=event_id, error=str(exc))

            await self._batch_upsert(points)
            total_new += len(points)
            log.info("acled_page_ingested", page=page, new=len(points), fetched=len(data))

            page += 1
            await asyncio.sleep(0.3)  # 300ms defensive rate limit

        elapsed = round(time.monotonic() - start, 2)
        log.info("acled_collection_finished", total_new=total_new, elapsed_seconds=elapsed)
