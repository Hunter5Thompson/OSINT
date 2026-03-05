"""Vessel / ship data endpoints."""

from fastapi import APIRouter, Request

from app.models.vessel import Vessel

router = APIRouter(prefix="/vessels", tags=["vessels"])


@router.get("", response_model=list[Vessel])
async def get_vessels(request: Request) -> list[Vessel]:
    """Return cached vessel data (populated via WebSocket ingestion)."""
    cached = await request.app.state.cache.get("vessels:all")
    if cached is not None:
        return [Vessel(**v) for v in cached]
    return []
