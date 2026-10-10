"""GP orbit reader with an independent versioned cache and visible group failures."""

from datetime import UTC, datetime

import structlog
from pydantic import ValidationError

from app.config import settings
from app.models.satellite_orbits import (
    OMMOrbit,
    OrbitCoverage,
    OrbitGroupCoverage,
    OrbitRejection,
    OrbitSatellite,
    OrbitSnapshot,
)
from app.orbit_elements import OrbitElementError, normalize_omm
from app.services import satellite_service
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService

logger = structlog.get_logger()
CACHE_KEY = "satellites:orbits:v1"
CACHE_TTL = 7200


class OrbitUpstreamError(RuntimeError):
    """No configured group can produce a valid orbit snapshot."""

    def __init__(self, code: str) -> None:
        super().__init__("No usable CelesTrak orbit group")
        self.code = code


def _failed_group(group: str, code: str) -> OrbitGroupCoverage:
    return OrbitGroupCoverage.model_validate(
        {
            "group": group,
            "status": "failed",
            "accepted_records": 0,
            "rejected_invalid": 0,
            "rejected_unsupported": 0,
            "rejections": [],
            "failure_code": code,
        }
    )


async def get_orbit_snapshot(proxy: ProxyService, cache: CacheService) -> OrbitSnapshot:
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        try:
            return OrbitSnapshot.model_validate(cached)
        except (ValidationError, ValueError):
            logger.warning("satellite_orbit_cache_invalid", generation=1)

    satellites: dict[int, OrbitSatellite] = {}
    coverage: list[OrbitGroupCoverage] = []
    for group in satellite_service._CELESTRAK_GROUPS:
        url = f"{settings.celestrak_gp_url}?GROUP={group}&FORMAT=JSON"
        try:
            payload: object = await proxy.get_json(url)
        except Exception:
            coverage.append(_failed_group(group, "transport"))
            logger.warning("satellite_orbit_group_failed", group=group, reason="transport")
            continue
        if not isinstance(payload, list):
            coverage.append(_failed_group(group, "invalid_payload"))
            continue
        rejected: list[OrbitRejection] = []
        accepted = 0
        for index, raw in enumerate(payload):
            try:
                elements = normalize_omm(raw)
            except OrbitElementError as exc:
                rejected.append(OrbitRejection(index=index, code=exc.code, reason=exc.reason))
                continue
            name = elements["OBJECT_NAME"]
            category = satellite_service._categorize(name, elements["INCLINATION"])
            satellite = OrbitSatellite(
                norad_id=elements["NORAD_CAT_ID"],
                name=name,
                orbit=OMMOrbit(format="omm", elements=elements),
                category=category,
                inclination_deg=round(elements["INCLINATION"], 2),
                period_min=1440.0 / elements["MEAN_MOTION"],
                operator_country=satellite_service._detect_country(name),
                satellite_type=satellite_service._detect_type(name, category),
            )
            existing = satellites.get(satellite.norad_id)
            if existing is None or (
                isinstance(existing.orbit, OMMOrbit)
                and elements["EPOCH"] > existing.orbit.elements["EPOCH"]
            ):
                satellites[satellite.norad_id] = satellite
            accepted += 1
        failed = bool(payload) and not accepted
        coverage.append(
            OrbitGroupCoverage(
                group=group,
                status="failed" if failed else "partial" if rejected else "ok",
                accepted_records=accepted,
                rejected_invalid=sum(item.code == "invalid" for item in rejected),
                rejected_unsupported=sum(item.code == "unsupported" for item in rejected),
                rejections=rejected,
                failure_code="no_usable_records" if failed else None,
            )
        )
    if not coverage or all(group.status == "failed" for group in coverage):
        transport_only = bool(coverage) and all(
            group.failure_code == "transport" for group in coverage
        )
        raise OrbitUpstreamError("UPSTREAM_TIMEOUT" if transport_only else "UPSTREAM_INVALID_DATA")
    snapshot = OrbitSnapshot(
        schema_version=1,
        fetched_at=datetime.now(UTC),
        satellites=list(satellites.values()),
        coverage=OrbitCoverage(
            completeness="complete"
            if all(group.status == "ok" for group in coverage)
            else "partial",
            groups=coverage,
        ),
    )
    await cache.set(CACHE_KEY, snapshot.model_dump(mode="json"), CACHE_TTL)
    return snapshot
