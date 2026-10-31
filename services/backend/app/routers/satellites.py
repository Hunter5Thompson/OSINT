"""Satellite TLE data endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.intel import APIError
from app.models.satellite import Satellite
from app.models.satellite_orbits import OrbitSnapshot
from app.services import satellite_orbit_service, satellite_service

router = APIRouter(prefix="/satellites", tags=["satellites"])


@router.get("/orbits", response_model=OrbitSnapshot)
async def get_satellite_orbits(request: Request) -> OrbitSnapshot | JSONResponse:
    try:
        return await satellite_orbit_service.get_orbit_snapshot(
            request.app.state.proxy,
            request.app.state.cache,
        )
    except satellite_orbit_service.OrbitUpstreamError as exc:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Upstream unavailable",
                detail="No usable CelesTrak orbit group",
                code=exc.code,
                timestamp=datetime.now(UTC),
            ).model_dump(mode="json"),
        )


@router.get("", response_model=list[Satellite])
async def get_satellites(request: Request) -> list[Satellite] | JSONResponse:
    try:
        return await satellite_service.get_satellites(
            request.app.state.proxy,
            request.app.state.cache,
        )
    except Exception:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Upstream unavailable",
                detail="CelesTrak is not responding",
                code="UPSTREAM_TIMEOUT",
                timestamp=datetime.now(UTC),
            ).model_dump(mode="json"),
        )
