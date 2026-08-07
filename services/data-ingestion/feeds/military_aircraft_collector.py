"""Military aircraft collector — adsb.fi primary, OpenSky fallback (deferred stub).

Primary source: GET https://opendata.adsb.fi/api/v2/mil — no auth, no rate limit.
Fallback: OpenSky Network (OAuth2 client-credentials) — stub only, deferred.

Dedup key: {icao24}|{timestamp_rounded_to_15min}
Neo4j write: MERGE MilitaryAircraft → MERGE Location → MERGE SPOTTED_AT
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from config import Settings
from feeds.base import BaseCollector
from graph_integrity.spatial_normalizer import (
    RawLocationIdentity,
    SpatialNormalizationIndex,
    load_active_normalization_index,
    normalize_location,
    spatial_property_parameters,
)

log = structlog.get_logger(__name__)

ADSB_FI_MIL_URL = "https://opendata.adsb.fi/api/v2/mil"

# ---------------------------------------------------------------------------
# ICAO hex ranges per military branch
# Each entry: (start_int, end_int, branch_name)
# ---------------------------------------------------------------------------
MILITARY_ICAO_RANGES: list[tuple[int, int, str]] = [
    # USAF — US Military block (AD0000–AFFFFF)
    (0xAD0000, 0xAFFFFF, "USAF"),
    # RAF — UK Military (400000–43FFFF)
    (0x400000, 0x43FFFF, "RAF"),
    # FAF — French Air & Space Force (388000–3AFFFF)
    (0x388000, 0x3AFFFF, "FAF"),
    # GAF — German Air Force (3C0000–3EFFFF)
    (0x3C0000, 0x3EFFFF, "GAF"),
    # IAF — Israeli Air Force (738000–73BFFF)
    (0x738000, 0x73BFFF, "IAF"),
    # NATO (aggregated / AWACS) (4D0000–4DFFFF)
    (0x4D0000, 0x4DFFFF, "NATO"),
]

# ---------------------------------------------------------------------------
# Region bounding boxes — (lat_min, lat_max, lon_min, lon_max)
# Same 9 hotspots as FIRMS + pacific + western meta-regions
# ---------------------------------------------------------------------------
REGION_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "ukraine":     (44.0,  52.5,  22.0,  40.0),
    "russia":      (50.0,  70.0,  30.0,  60.0),
    "iran":        (25.0,  39.8,  44.0,  63.5),
    "israel_gaza": (29.5,  33.5,  34.0,  35.9),
    "syria":       (32.0,  37.5,  35.5,  42.5),
    "taiwan":      (21.5,  25.5, 119.0, 122.5),
    "north_korea": (37.5,  42.5, 124.0, 130.5),
    "saudi_arabia":(16.0,  32.2,  36.5,  55.5),
    "turkey":      (36.0,  42.2,  26.0,  44.8),
    # Meta-regions (not used for region classification, presence only)
    "pacific":     (  0.0,  60.0, 100.0, 180.0),
    "western":     ( 25.0,  75.0, -25.0,  45.0),
}

# Regions to skip when classifying a specific point (meta-regions)
_SKIP_CLASSIFY = {"pacific", "western"}

_FT_TO_M = 0.3048
_KNOTS_TO_MS = 0.514444


def identify_branch(icao24: str) -> str | None:
    """Return military branch name for the given ICAO24 hex string, or None.

    Args:
        icao24: 6-character hex string (case-insensitive).

    Returns:
        Branch name string or None if not in any known military range.
    """
    try:
        val = int(icao24.upper(), 16)
    except ValueError:
        return None
    for start, end, branch in MILITARY_ICAO_RANGES:
        if start <= val <= end:
            return branch
    return None


def classify_region(lat: float, lon: float) -> str:
    """Return the geopolitical hotspot region name for a lat/lon coordinate.

    Meta-regions ("pacific", "western") are skipped so they don't shadow
    specific hotspot matches.  Returns "unknown" when no box matches.
    """
    for region, (lat_min, lat_max, lon_min, lon_max) in REGION_BBOXES.items():
        if region in _SKIP_CLASSIFY:
            continue
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return region
    return "unknown"


def build_aircraft_location_statement(
    aircraft: dict[str, Any],
    spatial_index: SpatialNormalizationIndex,
) -> dict[str, Any]:
    """Build one observation-keyed, parameterized Location write."""

    normalized = normalize_location(
        RawLocationIdentity(
            latitude=aircraft["latitude"],
            longitude=aircraft["longitude"],
        ),
        spatial_index,
    )
    return {
        "statement": (
            "MERGE (l:Location {loc_key: $loc_key}) "
            "ON CREATE SET l.name = $name, l.type = 'aircraft_observation', "
            "              l.region = $region, "
            "              l.lat = $latitude, l.lon = $longitude "
            "SET l.source_country_code = $source_country_code, "
            "    l.source_country_code_system = $source_country_code_system, "
            "    l.country_iso3 = $country_iso3, "
            "    l.admin1_code = $admin1_code, l.admin2_code = $admin2_code, "
            "    l.country_scope_key = $country_scope_key, "
            "    l.admin1_scope_key = $admin1_scope_key, "
            "    l.admin2_scope_key = $admin2_scope_key, "
            "    l.spatial_basis = $spatial_basis, "
            "    l.spatial_precision = $spatial_precision, "
            "    l.spatial_catalog_revision = $spatial_catalog_revision, "
            "    l.spatial_derivation_revision = $spatial_derivation_revision, "
            "    l.spatial_conflict = $spatial_conflict, "
            "    l.spatial_conflict_scope_keys = $spatial_conflict_scope_keys, "
            "    l.geo = point({longitude: $longitude, latitude: $latitude})"
        ),
        "parameters": {
            "loc_key": f"aircraft-observation:{aircraft['dedup_key']}",
            "name": aircraft["region"],
            "region": aircraft["region"],
            "latitude": aircraft["latitude"],
            "longitude": aircraft["longitude"],
            **spatial_property_parameters(normalized),
        },
    }


class MilitaryAircraftCollector(BaseCollector):
    """Collect military aircraft positions from adsb.fi, write to Neo4j."""

    def __init__(
        self,
        settings: Settings,
        redis_client: Any | None = None,
        *,
        spatial_index: SpatialNormalizationIndex | None = None,
    ) -> None:
        super().__init__(settings, redis_client)
        self._spatial_index = spatial_index

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def _parse_adsb_fi(self, data: dict) -> list[dict]:
        """Parse adsb.fi /v2/mil JSON response into normalised aircraft dicts.

        Conversions:
        - icao24: lowercase
        - callsign: stripped of whitespace
        - altitude: feet → metres (rounded to 1 dp)
        - ground_speed: knots → m/s (rounded to 2 dp)
        """
        aircraft: list[dict] = []
        now_ts = data.get("now", time.time())

        for ac in data.get("ac", []):
            hex_id = ac.get("hex", "")
            if not hex_id:
                continue

            icao24 = hex_id.lower()
            callsign = (ac.get("flight") or "").strip()
            lat = ac.get("lat")
            lon = ac.get("lon")
            alt_baro = ac.get("alt_baro")  # feet, may be "ground" string
            gs = ac.get("gs")  # knots

            # Convert altitude ft → m
            try:
                altitude_m = round(float(alt_baro) * _FT_TO_M, 1)
            except (TypeError, ValueError):
                altitude_m = None

            # Convert ground speed knots → m/s
            try:
                speed_ms = round(float(gs) * _KNOTS_TO_MS, 2)
            except (TypeError, ValueError):
                speed_ms = None

            branch = identify_branch(icao24)
            has_pos = lat is not None and lon is not None
            region = classify_region(lat, lon) if has_pos else "unknown"

            # Dedup key: icao24 + 15-minute bucket
            ts_bucket = _round_to_15min(int(now_ts))

            aircraft.append({
                "icao24": icao24,
                "callsign": callsign,
                "registration": ac.get("r", ""),
                "type_code": ac.get("t", ""),
                "latitude": lat,
                "longitude": lon,
                "altitude_m": altitude_m,
                "speed_ms": speed_ms,
                "heading": ac.get("track"),
                "military_branch": branch,
                "region": region,
                "timestamp": int(now_ts),
                "dedup_key": f"{icao24}|{ts_bucket}",
                "source": "adsb.fi",
            })

        return aircraft

    # ------------------------------------------------------------------
    # Internal Neo4j write
    # ------------------------------------------------------------------

    async def _write_aircraft_neo4j(self, ac: dict) -> None:
        """Write a single aircraft observation to Neo4j with 3 statements:
        1. MERGE MilitaryAircraft node
        2. MERGE Location node
        3. MERGE SPOTTED_AT relationship with observation metadata
        """
        spatial_index = self._spatial_index
        if spatial_index is None:
            try:
                spatial_index = load_active_normalization_index(
                    self.settings.spatial_catalog_path,
                    crosswalk_path=self.settings.spatial_country_crosswalk_path,
                )
            except (OSError, ValueError) as exc:
                log.warning(
                    "spatial_location_writer_unsupported",
                    lane="military_aircraft",
                    cause="normalization_index_unavailable",
                    error=str(exc),
                )
                raise RuntimeError("spatial normalization index unavailable") from exc
            self._spatial_index = spatial_index

        location_write = build_aircraft_location_statement(ac, spatial_index)
        statements = [
            # 1. MilitaryAircraft node
            {
                "statement": (
                    "MERGE (a:MilitaryAircraft {icao24: $icao24}) "
                    "SET a.callsign = $callsign, "
                    "    a.registration = $registration, "
                    "    a.type_code = $type_code, "
                    "    a.military_branch = $military_branch, "
                    "    a.last_seen = datetime()"
                ),
                "parameters": {
                    "icao24": ac["icao24"],
                    "callsign": ac["callsign"],
                    "registration": ac["registration"],
                    "type_code": ac["type_code"],
                    "military_branch": ac["military_branch"],
                },
            },
            # 2. Observation-keyed Location node
            location_write,
            # 3. SPOTTED_AT relationship
            {
                "statement": (
                    "MATCH (a:MilitaryAircraft {icao24: $icao24}) "
                    "MATCH (l:Location {loc_key: $loc_key}) "
                    "MERGE (a)-[r:SPOTTED_AT {dedup_key: $dedup_key}]->(l) "
                    "SET r.latitude = $latitude, "
                    "    r.longitude = $longitude, "
                    "    r.altitude_m = $altitude_m, "
                    "    r.speed_ms = $speed_ms, "
                    "    r.heading = $heading, "
                    "    r.timestamp = $timestamp, "
                    "    r.source = $source"
                ),
                "parameters": {
                    "icao24": ac["icao24"],
                    "loc_key": location_write["parameters"]["loc_key"],
                    "dedup_key": ac["dedup_key"],
                    "latitude": ac["latitude"],
                    "longitude": ac["longitude"],
                    "altitude_m": ac["altitude_m"],
                    "speed_ms": ac["speed_ms"],
                    "heading": ac["heading"],
                    "timestamp": ac["timestamp"],
                    "source": ac["source"],
                },
            },
        ]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.settings.neo4j_http_url}/db/neo4j/tx/commit",
                json={"statements": statements},
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            resp.raise_for_status()
            errors = resp.json().get("errors", [])
            if errors:
                log.warning("military_aircraft_neo4j_errors", icao24=ac["icao24"], errors=errors)
                raise RuntimeError("Neo4j rejected the atomic aircraft write")

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    async def _fetch_adsb_fi(self) -> dict | None:
        """Fetch military aircraft list from adsb.fi (no auth, no rate limit)."""
        try:
            resp = await self.http.get(ADSB_FI_MIL_URL)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.error("military_aircraft_adsb_fi_failed", error=str(exc))
            return None

    async def _fetch_opensky(self) -> list[dict]:
        """OpenSky fallback — DEFERRED STUB.

        Full implementation would require:
        1. OAuth2 client-credentials flow using settings.opensky_client_id /
           settings.opensky_client_secret against https://auth.opensky-network.org/...
        2. GET https://opensky-network.org/api/states/all with bbox params
        3. Filter by military ICAO24 ranges (MILITARY_ICAO_RANGES)
        4. Map OpenSky state vector format to the normalised dict schema used by
           _parse_adsb_fi (fields: icao24, callsign, lat, lon, alt_baro in m,
           velocity in m/s, true_track, on_ground, etc.)
        5. Handle 10-second rate limit (anonymous: 10s, authenticated: 5s)

        Until implemented, this stub logs a warning and returns an empty list
        so callers can proceed without crashing.
        """
        log.warning(
            "military_aircraft_opensky_stub",
            message="OpenSky fallback is a deferred stub — no data returned",
        )
        return []

    # ------------------------------------------------------------------
    # Main collect loop
    # ------------------------------------------------------------------

    async def collect(self) -> None:
        """Fetch military aircraft, deduplicate, write to Neo4j."""
        log.info("military_aircraft_collection_started")
        start = time.monotonic()

        raw = await self._fetch_adsb_fi()
        if raw is None:
            log.warning("military_aircraft_adsb_fi_unavailable_trying_opensky")
            aircraft = await self._fetch_opensky()
        else:
            aircraft = self._parse_adsb_fi(raw)

        if not aircraft:
            log.info("military_aircraft_no_data")
            return

        # Dedup via in-memory set for this run; Neo4j MERGE handles persistent dedup
        seen: set[str] = set()
        written = 0

        for ac in aircraft:
            dedup_key = ac.get("dedup_key", "")
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Only write aircraft in known hotspot regions (skip "unknown")
            if ac["region"] == "unknown":
                continue

            try:
                await self._write_aircraft_neo4j(ac)
                written += 1
            except Exception as exc:
                log.error(
                    "military_aircraft_write_failed",
                    icao24=ac.get("icao24"),
                    error=str(exc),
                )

        elapsed = round(time.monotonic() - start, 2)
        log.info(
            "military_aircraft_collection_finished",
            total_parsed=len(aircraft),
            written=written,
            elapsed_seconds=elapsed,
        )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _round_to_15min(ts: int) -> int:
    """Round a Unix timestamp down to the nearest 15-minute boundary."""
    return (ts // 900) * 900
