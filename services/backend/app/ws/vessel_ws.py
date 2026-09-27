"""WebSocket endpoint for AIS vessel data with burst pattern."""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import vessel_service

logger = structlog.get_logger()

router = APIRouter()
_BURST_SECONDS = 20.0


@router.websocket("/ws/vessels")
async def vessel_stream(websocket: WebSocket) -> None:
    """Push vessel data: cached positions, otherwise a short AISStream burst."""
    await websocket.accept()
    logger.info("vessel_ws_connected")

    try:
        while True:
            await _push_vessels_once(websocket)
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        logger.info("vessel_ws_disconnected")
    except Exception:
        logger.error("vessel_ws_error")


async def _push_vessels_once(websocket: WebSocket) -> None:
    cache = websocket.app.state.cache
    cached = vessel_service.vessels_from_cache(await cache.get(vessel_service.CACHE_KEY))
    if cached is None:
        fetched = await vessel_service.collect_ais_positions(window_s=_BURST_SECONDS)
        await vessel_service.publish_vessel_snapshot(cache, fetched)
        vessels = fetched
    else:
        vessels = cached
    payload = [item.model_dump(mode="json") for item in vessels]
    await websocket.send_text(
        json.dumps({"type": "vessels", "data": payload, "count": len(payload)})
    )
