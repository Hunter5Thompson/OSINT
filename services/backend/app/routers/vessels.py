"""Vessel / ship data endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.intel import APIError
from app.models.vessel import Vessel
from app.services import vessel_service

router = APIRouter(prefix="/vessels", tags=["vessels"])


@router.get("", response_model=list[Vessel])
async def get_vessels(request: Request) -> list[Vessel] | JSONResponse:
    """Return vessels from AISStream cache or Digitraffic REST fallback."""
    try:
        return await vessel_service.get_vessels(
            request.app.state.proxy,
            request.app.state.cache,
        )
    except Exception:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Vessel data unavailable",
                detail="Failed to load vessel data",
                code="VESSEL_FETCH_ERROR",
                timestamp=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        )
