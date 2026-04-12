"""IMF PortWatch — Chokepoint Trade Flows and Disruption Events.

ArcGIS FeatureServer with paginated queries. Standard insert-only dedup.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from feeds.base import BaseCollector

log = structlog.get_logger("portwatch_collector")

_BASE_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
_CHOKEPOINTS_URL = f"{_BASE_URL}/Daily_Chokepoints_Data/FeatureServer/0/query"
_DISRUPTIONS_URL = f"{_BASE_URL}/portwatch_disruptions_database/FeatureServer/0/query"

_PAGE_SIZE = 1000

# Center coordinates for known chokepoints (lat, lon)
CHOKEPOINT_COORDS: dict[str, tuple[float, float]] = {
    "Strait of Hormuz": (26.57, 56.25),
    "Bab el-Mandeb": (12.58, 43.33),
    "Suez Canal": (30.46, 32.34),
    "Strait of Malacca": (2.50, 101.20),
    "Panama Canal": (9.08, -79.68),
    "Cape of Good Hope": (-34.35, 18.50),
    "Strait of Gibraltar": (35.96, -5.50),
    "Turkish Straits": (41.12, 29.08),
}


class PortWatchCollector(BaseCollector):
    """Collect chokepoint trade flows and disruptions from IMF PortWatch."""

    def _parse_chokepoint_data(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            chokepoint = str(attrs.get("chokepoint_name", ""))
            records.append({
                "record_type": "daily_flow",
                "chokepoint": chokepoint,
                "date": str(attrs.get("date", "")),
                "trade_value_usd": float(attrs.get("trade_value_usd", 0)),
                "vessel_count": int(attrs.get("vessel_count", 0)),
            })
        return records

    def _parse_disruption_data(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            records.append({
                "record_type": "disruption",
                "disruption_id": str(attrs.get("objectid", "")),
                "chokepoint": str(attrs.get("chokepoint_name", "")),
                "description": str(attrs.get("disruption_description", "")),
                "start_date": str(attrs.get("start_date", "")),
                "end_date": attrs.get("end_date"),
            })
        return records

    async def _fetch_paginated(self, url: str) -> list[dict[str, Any]]:
        """Fetch all pages from ArcGIS FeatureServer."""
        all_features: list[dict[str, Any]] = []
        offset = 0

        while True:
            params = {
                "where": "1=1",
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

        # 1. Chokepoint daily flows
        log.info("portwatch_fetching_chokepoints")
        chokepoint_data = await self._fetch_paginated(_CHOKEPOINTS_URL)
        flow_records = self._parse_chokepoint_data(chokepoint_data)
        log.info("portwatch_flows_parsed", count=len(flow_records))

        flow_points = []
        for record in flow_records:
            chash = self._content_hash(record["chokepoint"], record["date"], "daily_flow")
            point_id = self._point_id(chash)
            is_dup = await self._dedup_check(point_id)
            if is_dup:
                continue

            coords = CHOKEPOINT_COORDS.get(record["chokepoint"], (0.0, 0.0))
            description = (
                f"PortWatch: {record['chokepoint']} on {record['date']} — "
                f"${record['trade_value_usd']:,.0f} trade, {record['vessel_count']} vessels"
            )

            chash = self._content_hash(record["chokepoint"], record["date"], "daily_flow")

            try:
                from pipeline import process_item
                await process_item(
                    title=f"PortWatch {record['chokepoint']}",
                    text=description,
                    url=_CHOKEPOINTS_URL,
                    source="portwatch",
                    settings=self.settings,
                    redis_client=self.redis,
                )
            except Exception:
                log.warning("portwatch_pipeline_failed", chokepoint=record["chokepoint"])

            payload = {
                "source": "portwatch",
                **record,
                "latitude": coords[0],
                "longitude": coords[1],
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

            coords = CHOKEPOINT_COORDS.get(record["chokepoint"], (0.0, 0.0))
            description = f"PortWatch Disruption: {record['chokepoint']} — {record['description']}"

            chash = self._content_hash("disruption", record["disruption_id"])

            try:
                from pipeline import process_item
                await process_item(
                    title=f"PortWatch Disruption: {record['chokepoint']}",
                    text=description,
                    url=_DISRUPTIONS_URL,
                    source="portwatch",
                    settings=self.settings,
                    redis_client=self.redis,
                )
            except Exception:
                log.warning("portwatch_disruption_pipeline_failed")

            payload = {
                "source": "portwatch",
                **record,
                "latitude": coords[0],
                "longitude": coords[1],
            }
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
