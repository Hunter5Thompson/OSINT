"""Submarine cable data endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.cable import CableDataset
from app.models.intel import APIError
from app.services import cable_service

router = APIRouter(prefix="/cables", tags=["cables"])


@router.get("", response_model=CableDataset)
async def get_cables(request: Request) -> CableDataset | JSONResponse:
    try:
        return await cable_service.get_cable_dataset(
            request.app.state.proxy,
            request.app.state.cache,
        )
    except Exception:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Cable data unavailable",
                detail="Failed to load submarine cable data",
                code="CABLE_FETCH_ERROR",
                timestamp=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        )
