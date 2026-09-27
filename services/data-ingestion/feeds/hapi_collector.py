"""HAPI — Humanitarian Data Exchange API.

Collects monthly conflict aggregates per country (events, fatalities, event_type).
Standard insert-only dedup (not mutable events).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from datetime import datetime
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
        raw_records = data.get("data", [])
        if not isinstance(raw_records, list):
            return records
        for item in raw_records:
            if not isinstance(item, Mapping):
                log.warning("hapi_record_invalid", country=country, reason="not_object")
                continue
            period_start = item.get("reference_period_start")
            event_type = item.get("event_type")
            if (
                not isinstance(period_start, str)
                or not isinstance(event_type, str)
                or not event_type.strip()
            ):
                log.warning("hapi_record_invalid", country=country, reason="invalid_identity")
                continue
            try:
                parsed_period = datetime.fromisoformat(
                    period_start.strip().replace("Z", "+00:00")
                )
            except ValueError:
                log.warning("hapi_record_invalid", country=country, reason="invalid_identity")
                continue
            period = parsed_period.date().isoformat()[:7]

            try:
                events_count = _optional_count(item.get("events"))
                fatalities = _optional_count(item.get("fatalities"))
            except ValueError as exc:
                log.warning(
                    "hapi_record_invalid",
                    country=country,
                    reason="invalid_count",
                    error=str(exc),
                )
                continue

            records.append({
                "location_code": country,
                "reference_period": period,
                "event_type": event_type,
                "events_count": events_count,
                "fatalities": fatalities,
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
                chash = self._content_hash(
                    record["location_code"], record["reference_period"], record["event_type"]
                )
                point_id = self._point_id(chash)

                # Standard dedup — skip if exists
                is_dup = await self._dedup_check(point_id)
                if is_dup:
                    continue

                description = (
                    f"{record['event_type']}: {_format_count(record['events_count'])} events, "
                    f"{_format_count(record['fatalities'])} fatalities in {country} "
                    f"({record['reference_period']})"
                )

                from pipeline import (
                    ExtractionConfigError,
                    ExtractionTransientError,
                    process_item,
                )

                # Transient/config errors skip Qdrant upsert so the record is
                # retried on the next source re-fetch.
                try:
                    await process_item(
                        title=f"HAPI {country} {record['reference_period']}",
                        text=description,
                        url=_HAPI_URL,
                        source="hapi",
                        content_hash=chash,
                        document_id=f"hapi:conflict-events:{chash}",
                        settings=self.settings,
                        redis_client=self.redis,
                    )
                except ExtractionTransientError as exc:
                    log.warning(
                        "extraction_skipped_transient",
                        url=_HAPI_URL,
                        country=country,
                        error=str(exc),
                    )
                    continue
                except ExtractionConfigError as exc:
                    log.error(
                        "extraction_skipped_config",
                        url=_HAPI_URL,
                        country=country,
                        error=str(exc),
                    )
                    continue
                except Exception:
                    log.warning("hapi_pipeline_failed", country=country)

                payload = {
                    "source": "hapi",
                    "description": description,
                    **record,
                }
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


def _optional_count(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean count")
    if isinstance(value, int):
        count = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("non-integer count")
        count = int(value)
    elif isinstance(value, str):
        try:
            count = int(value.strip())
        except ValueError as exc:
            raise ValueError("invalid integer count") from exc
    else:
        raise ValueError("unsupported count type")
    if count < 0:
        raise ValueError("negative count")
    return count


def _format_count(value: int | None) -> str:
    return str(value) if value is not None else "unknown"
