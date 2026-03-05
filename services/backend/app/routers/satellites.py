"""Satellite TLE data endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.intel import APIError
from app.models.satellite import Satellite
from app.services import satellite_service

router = APIRouter(prefix="/satellites", tags=["satellites"])


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
                timestamp=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        )
