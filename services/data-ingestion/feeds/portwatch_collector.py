"""IMF PortWatch — Chokepoint Trade Flows and Disruption Events.

ArcGIS FeatureServer with paginated queries. Standard insert-only dedup.

Daily flows are numeric time series: they are embedded and stored, never sent through
LLM extraction, and only a recent window is fetched per run (the full history is ~79k
rows). Disruptions are narrative events and do go through extraction.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from feeds.base import BaseCollector

log = structlog.get_logger("portwatch_collector")

_BASE_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
_CHOKEPOINTS_URL = f"{_BASE_URL}/Daily_Chokepoints_Data/FeatureServer/0/query"
_DISRUPTIONS_URL = f"{_BASE_URL}/portwatch_disruptions_database/FeatureServer/0/query"

_PAGE_SIZE = 1000
# PortWatch publishes with a few days lag; re-reading two weeks is cheap and dedup-safe.
_FLOW_LOOKBACK_DAYS = 14

# Center coordinates (lat, lon) keyed by the stable PortWatch `portid` — display names
# drift ("Bab el-Mandeb" -> "Bab el-Mandeb Strait"). Unknown ids get no coordinates.
CHOKEPOINT_COORDS: dict[str, tuple[float, float]] = {
    "chokepoint1": (30.46, 32.34),     # Suez Canal
    "chokepoint2": (9.08, -79.68),     # Panama Canal
    "chokepoint3": (41.12, 29.08),     # Bosporus Strait
    "chokepoint4": (12.58, 43.33),     # Bab el-Mandeb Strait
    "chokepoint5": (2.50, 101.20),     # Malacca Strait
    "chokepoint6": (26.57, 56.25),     # Strait of Hormuz
    "chokepoint7": (-34.35, 18.50),    # Cape of Good Hope
    "chokepoint8": (35.96, -5.50),     # Gibraltar Strait
}


def _epoch_ms_to_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, UTC).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _coords(lat: Any, lon: Any) -> dict[str, float]:
    try:
        return {"latitude": float(lat), "longitude": float(lon)}
    except (TypeError, ValueError):
        return {}


class PortWatchCollector(BaseCollector):
    """Collect chokepoint trade flows and disruptions from IMF PortWatch."""

    def _parse_chokepoint_data(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            records.append({
                "record_type": "daily_flow",
                "portid": str(attrs.get("portid") or ""),
                "chokepoint": str(attrs.get("portname") or ""),
                "date": str(attrs.get("date") or ""),
                "vessel_count": int(attrs.get("n_total") or 0),
                "tanker_count": int(attrs.get("n_tanker") or 0),
                "container_count": int(attrs.get("n_container") or 0),
                "cargo_count": int(attrs.get("n_cargo") or 0),
                "capacity": float(attrs.get("capacity") or 0),
            })
        return records

    def _parse_disruption_data(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            records.append({
                "record_type": "disruption",
                "disruption_id": str(attrs.get("eventid") or ""),
                "event_type": str(attrs.get("eventtype") or ""),
                "name": str(attrs.get("eventname") or ""),
                "description": str(attrs.get("htmldescription") or ""),
                "alert_level": str(attrs.get("alertlevel") or ""),
                "country": str(attrs.get("country") or ""),
                "affected_ports": str(attrs.get("affectedports") or ""),
                "start_date": _epoch_ms_to_date(attrs.get("fromdate")),
                "end_date": _epoch_ms_to_date(attrs.get("todate")),
                **_coords(attrs.get("lat"), attrs.get("long")),
            })
        return records

    async def _fetch_paginated(self, url: str, *, where: str = "1=1") -> dict[str, Any]:
        """Fetch all pages matching `where` from ArcGIS FeatureServer."""
        all_features: list[dict[str, Any]] = []
        offset = 0

        while True:
            params = {
                "where": where,
                "outFields": "*",
                "f": "json",
                "resultRecordCount": _PAGE_SIZE,
                "resultOffset": offset,
            }
            try:
                resp = await self.http.get(url, params=params, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                log.warning("portwatch_page_failed", url=url, offset=offset)
                break

            features = data.get("features", [])
            all_features.extend(features)

            if not features or not data.get("exceededTransferLimit", False):
                break

            offset += len(features)
            await asyncio.sleep(1)

        return {"features": all_features}

    async def collect(self) -> None:
        await self._ensure_collection()

        # 1. Chokepoint daily flows — recent window only, no LLM extraction.
        since = (datetime.now(UTC).date() - timedelta(days=_FLOW_LOOKBACK_DAYS)).isoformat()
        log.info("portwatch_fetching_chokepoints", since=since)
        chokepoint_data = await self._fetch_paginated(
            _CHOKEPOINTS_URL, where=f"date >= '{since}'"
        )
        flow_records = self._parse_chokepoint_data(chokepoint_data)
        log.info("portwatch_flows_parsed", count=len(flow_records))

        flow_points = []
        for record in flow_records:
            chash = self._content_hash(record["portid"], record["date"], "daily_flow")
            point_id = self._point_id(chash)
            if await self._dedup_check(point_id):
                continue

            description = (
                f"PortWatch: {record['chokepoint']} on {record['date']} — "
                f"{record['vessel_count']} vessels ({record['tanker_count']} tankers), "
                f"capacity {record['capacity']:,.0f} t"
            )
            coords = CHOKEPOINT_COORDS.get(record["portid"])
            payload = {
                "source": "portwatch",
                "description": description,
                **record,
                **(_coords(*coords) if coords else {}),
            }
            try:
                point = await self._build_point(description, payload, chash)
                flow_points.append(point)
            except Exception:
                log.warning("portwatch_embed_failed", chokepoint=record["chokepoint"])

        if flow_points:
            await self._batch_upsert(flow_points)

        # 2. Disruption events
        log.info("portwatch_fetching_disruptions")
        disruption_data = await self._fetch_paginated(_DISRUPTIONS_URL)
        disruption_records = self._parse_disruption_data(disruption_data)
        log.info("portwatch_disruptions_parsed", count=len(disruption_records))

        disruption_points = []
        for record in disruption_records:
            chash = self._content_hash("disruption", record["disruption_id"])
            point_id = self._point_id(chash)
            is_dup = await self._dedup_check(point_id)
            if is_dup:
                continue

            description = f"PortWatch Disruption: {record['name']} — {record['description']}"

            from pipeline import (
                ExtractionConfigError,
                ExtractionTransientError,
                process_item,
            )

            # Transient/config errors skip Qdrant upsert so the disruption
            # record is retried on the next source re-fetch.
            try:
                await process_item(
                    title=f"PortWatch Disruption: {record['name']}",
                    text=description,
                    url=_DISRUPTIONS_URL,
                    source="portwatch",
                    settings=self.settings,
                    redis_client=self.redis,
                )
            except ExtractionTransientError as exc:
                log.warning(
                    "extraction_skipped_transient",
                    url=_DISRUPTIONS_URL,
                    disruption_id=record["disruption_id"],
                    error=str(exc),
                )
                continue
            except ExtractionConfigError as exc:
                log.error(
                    "extraction_skipped_config",
                    url=_DISRUPTIONS_URL,
                    disruption_id=record["disruption_id"],
                    error=str(exc),
                )
                continue
            except Exception:
                log.warning("portwatch_disruption_pipeline_failed")

            payload = {"source": "portwatch", "description": description, **record}
            try:
                point = await self._build_point(description, payload, chash)
                disruption_points.append(point)
            except Exception:
                log.warning("portwatch_disruption_embed_failed")

        if disruption_points:
            await self._batch_upsert(disruption_points)

        log.info(
            "portwatch_complete",
            flows=len(flow_points),
            disruptions=len(disruption_points),
        )
