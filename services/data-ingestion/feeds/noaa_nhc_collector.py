"""NOAA NHC — National Hurricane Center Tropical Weather.

Collects active tropical cyclone advisories. Standard insert-only dedup.
"""

from __future__ import annotations

from typing import Any

import structlog

from feeds.base import BaseCollector

log = structlog.get_logger("noaa_nhc_collector")

_NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"

_CLASSIFICATION_MAP = {
    "TD": "Tropical Depression",
    "TS": "Tropical Storm",
    "HU": "Hurricane",
    "STD": "Subtropical Depression",
    "STS": "Subtropical Storm",
    "PTC": "Post-Tropical Cyclone",
    "TW": "Tropical Weather Outlook",
}


_COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _movement_text(direction_deg: Any, speed_kt: Any) -> str:
    """NHC movementDir (degrees, 0 = north) + movementSpeed (knots)."""
    if speed_kt is None or direction_deg is None:
        return "unknown"
    speed = _as_int(speed_kt)
    if speed == 0:
        return "stationary"
    point = _COMPASS[int((_as_int(direction_deg) % 360 + 11.25) // 22.5) % 16]
    return f"{point} at {speed} kt"


class NOAANHCCollector(BaseCollector):
    """Collect tropical weather advisories from NOAA NHC."""

    def _parse_storms(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse NHC CurrentStorms.json (numbers arrive as strings, position in
        latitudeNumeric/longitudeNumeric, movement as degrees + knots)."""
        storms: list[dict[str, Any]] = []
        for storm in data.get("activeStorms", []):
            lat = storm.get("latitudeNumeric")
            lon = storm.get("longitudeNumeric")
            if lat is None or lon is None:
                log.warning("noaa_nhc_storm_without_position", storm_id=storm.get("id"))
                continue

            classification_code = str(storm.get("classification", ""))
            advisory = storm.get("publicAdvisory") or {}
            storms.append({
                "storm_id": str(storm.get("id", "")),
                "storm_name": str(storm.get("name", "")),
                "classification": _CLASSIFICATION_MAP.get(
                    classification_code, classification_code),
                "wind_speed_kt": _as_int(storm.get("intensity")),
                "pressure_mb": _as_int(storm.get("pressure")),
                "latitude": float(lat),
                "longitude": float(lon),
                "movement": _movement_text(
                    storm.get("movementDir"), storm.get("movementSpeed")),
                "advisory_number": str(advisory.get("advNum", "")),
                "advisory_url": advisory.get("url"),
                "last_update": storm.get("lastUpdate"),
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

            from pipeline import (
                ExtractionConfigError,
                ExtractionTransientError,
                process_item,
            )

            storm_url = storm["advisory_url"] or (
                f"https://www.nhc.noaa.gov/text/refresh/{storm['storm_id']}+shtml"
            )
            # Transient/config errors skip Qdrant upsert so the storm advisory
            # is retried on the next source re-fetch.
            try:
                await process_item(
                    title=f"NHC Advisory: {storm['storm_name']}",
                    text=description,
                    url=storm_url,
                    source="noaa_nhc",
                    settings=self.settings,
                    redis_client=self.redis,
                )
            except ExtractionTransientError as exc:
                log.warning(
                    "extraction_skipped_transient",
                    url=storm_url,
                    error=str(exc),
                )
                continue
            except ExtractionConfigError as exc:
                log.error(
                    "extraction_skipped_config",
                    url=storm_url,
                    error=str(exc),
                )
                continue
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
