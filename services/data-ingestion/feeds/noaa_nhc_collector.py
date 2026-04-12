"""NOAA NHC — National Hurricane Center Tropical Weather.

Collects active tropical cyclone advisories. Standard insert-only dedup.
"""

from __future__ import annotations

from typing import Any

import structlog

from feeds.base import BaseCollector

log = structlog.get_logger("noaa_nhc_collector")

_NHC_URL = "https://www.nhc.noaa.gov/CurrentSummaries.json"

_CLASSIFICATION_MAP = {
    "TD": "Tropical Depression",
    "TS": "Tropical Storm",
    "HU": "Hurricane",
    "STD": "Subtropical Depression",
    "STS": "Subtropical Storm",
    "PTC": "Post-Tropical Cyclone",
    "TW": "Tropical Weather Outlook",
}


class NOAANHCCollector(BaseCollector):
    """Collect tropical weather advisories from NOAA NHC."""

    def _parse_storms(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        storms: list[dict[str, Any]] = []
        for storm in data.get("activeStorms", []):
            classification_code = str(storm.get("classification", ""))
            classification = _CLASSIFICATION_MAP.get(classification_code, classification_code)

            movement = storm.get("movement", {})
            movement_text = movement.get("text", "") if isinstance(movement, dict) else str(movement)

            storms.append({
                "storm_id": str(storm.get("id", "")),
                "storm_name": str(storm.get("name", "")),
                "classification": classification,
                "wind_speed_kt": int(storm.get("intensity", 0)),
                "pressure_mb": int(storm.get("pressure", 0)),
                "latitude": float(storm.get("lat", 0)),
                "longitude": float(storm.get("lon", 0)),
                "movement": movement_text,
                "advisory_number": str(storm.get("advisoryNumber", "")),
            })
        return storms

    async def collect(self) -> None:
        await self._ensure_collection()

        try:
            resp = await self.http.get(_NHC_URL, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            log.exception("noaa_nhc_fetch_failed")
            return

        storms = self._parse_storms(data)
        log.info("noaa_nhc_parsed", count=len(storms))

        if not storms:
            log.info("noaa_nhc_no_active_storms")
            return

        points = []
        for storm in storms:
            chash = self._content_hash(storm["storm_id"], storm["advisory_number"])
            point_id = self._point_id(chash)

            is_dup = await self._dedup_check(point_id)
            if is_dup:
                continue

            description = (
                f"{storm['classification']} {storm['storm_name']} — "
                f"winds {storm['wind_speed_kt']}kt, pressure {storm['pressure_mb']}mb, "
                f"moving {storm['movement']}"
            )

            try:
                from pipeline import process_item
                await process_item(
                    title=f"NHC Advisory: {storm['storm_name']}",
                    text=description,
                    url=f"https://www.nhc.noaa.gov/text/refresh/{storm['storm_id']}+shtml",
                    source="noaa_nhc",
                    settings=self.settings,
                    redis_client=self.redis,
                )
            except Exception:
                log.warning("noaa_nhc_pipeline_failed", storm_id=storm["storm_id"])

            payload = {
                "source": "noaa_nhc",
                "description": description,
                **storm,
            }
            try:
                point = await self._build_point(description, payload, chash)
                points.append(point)
            except Exception:
                log.warning("noaa_nhc_embed_failed", storm_id=storm["storm_id"])

        if points:
            await self._batch_upsert(points)

        log.info("noaa_nhc_complete", storms=len(storms), ingested=len(points))
