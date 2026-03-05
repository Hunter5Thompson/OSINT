"""Earthquake data endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.earthquake import Earthquake
from app.models.intel import APIError
from app.services import earthquake_service

router = APIRouter(prefix="/earthquakes", tags=["earthquakes"])


@router.get("", response_model=list[Earthquake])
async def get_earthquakes(request: Request) -> list[Earthquake] | JSONResponse:
    try:
        return await earthquake_service.get_earthquakes(
            request.app.state.proxy,
            request.app.state.cache,
        )
    except Exception:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Upstream unavailable",
                detail="USGS is not responding",
                code="UPSTREAM_TIMEOUT",
                timestamp=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        )
