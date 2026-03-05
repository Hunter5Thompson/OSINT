"""Flight data endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.flight import Aircraft
from app.models.intel import APIError
from app.services import flight_service

router = APIRouter(prefix="/flights", tags=["flights"])


@router.get("", response_model=list[Aircraft])
async def get_flights(request: Request) -> list[Aircraft] | JSONResponse:
    try:
        return await flight_service.get_flights(
            request.app.state.proxy,
            request.app.state.cache,
        )
    except Exception:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Upstream unavailable",
                detail="Flight data sources are not responding",
                code="UPSTREAM_TIMEOUT",
                timestamp=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        )


@router.get("/military", response_model=list[Aircraft])
async def get_military_flights(request: Request) -> list[Aircraft] | JSONResponse:
    try:
        all_flights = await flight_service.get_flights(
            request.app.state.proxy,
            request.app.state.cache,
        )
        return [f for f in all_flights if f.is_military]
    except Exception:
        return JSONResponse(
            status_code=502,
            content=APIError(
                error="Upstream unavailable",
                code="UPSTREAM_TIMEOUT",
                timestamp=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        )
