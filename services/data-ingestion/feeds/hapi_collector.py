"""HAPI — Humanitarian Data Exchange API.

Collects monthly conflict aggregates per country (events, fatalities, event_type).
Standard insert-only dedup (not mutable events).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from feeds.base import BaseCollector

log = structlog.get_logger("hapi_collector")

_HAPI_URL = "https://hapi.humdata.org/api/v2/coordination-context/conflict-events"

FOCUS_COUNTRIES = [
    "AFG", "SYR", "UKR", "SDN", "SSD",
    "SOM", "COD", "MMR", "YEM", "ETH",
    "IRQ", "PSE", "LBY", "MLI", "BFA",
    "NER", "NGA", "CMR", "MOZ", "HTI",
]


class HAPICollector(BaseCollector):
    """Collect humanitarian conflict data from HAPI."""

    def _parse_records(self, data: dict[str, Any], country: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in data.get("data", []):
            period_start = str(item.get("reference_period_start", ""))
            period = period_start[:7] if len(period_start) >= 7 else period_start

            records.append({
                "location_code": country,
                "reference_period": period,
                "event_type": str(item.get("event_type", "")),
                "events_count": int(item.get("events", 0)),
                "fatalities": int(item.get("fatalities", 0)),
            })
        return records

    async def collect(self) -> None:
        await self._ensure_collection()

        headers = {}
        if self.settings.hapi_app_identifier:
            headers["app_identifier"] = self.settings.hapi_app_identifier

        total_ingested = 0

        for country in FOCUS_COUNTRIES:
            params = {
                "output_format": "json",
                "limit": 1000,
                "location_code": country,
            }
            try:
                resp = await self.http.get(_HAPI_URL, params=params, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                log.warning("hapi_fetch_failed", country=country)
                continue

            records = self._parse_records(data, country)
            points = []

            for record in records:
                chash = self._content_hash(record["location_code"], record["reference_period"], record["event_type"])
                point_id = self._point_id(chash)

                # Standard dedup — skip if exists
                is_dup = await self._dedup_check(point_id)
                if is_dup:
                    continue

                description = (
                    f"{record['event_type']}: {record['events_count']} events, "
                    f"{record['fatalities']} fatalities in {country} ({record['reference_period']})"
                )

                try:
                    from pipeline import process_item
                    await process_item(
                        title=f"HAPI {country} {record['reference_period']}",
                        text=description,
                        url=_HAPI_URL,
                        source="hapi",
                        settings=self.settings,
                        redis_client=self.redis,
                    )
                except Exception:
                    log.warning("hapi_pipeline_failed", country=country)

                payload = {
                    "source": "hapi",
                    **record,
                }
                chash = self._content_hash(record["location_code"], record["reference_period"], record["event_type"])
                try:
                    point = await self._build_point(description, payload, chash)
                    points.append(point)
                except Exception:
                    log.warning("hapi_embed_failed", country=country)

            if points:
                await self._batch_upsert(points)
                total_ingested += len(points)

            # Rate limiting between country queries
            await asyncio.sleep(1)

        log.info("hapi_complete", total_ingested=total_ingested, countries=len(FOCUS_COUNTRIES))
