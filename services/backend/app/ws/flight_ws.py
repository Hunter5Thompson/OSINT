"""WebSocket endpoint for live flight position streaming."""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import flight_service

logger = structlog.get_logger()

router = APIRouter()


@router.websocket("/ws/flights")
async def flight_stream(websocket: WebSocket) -> None:
    """Push flight position updates every 10 seconds."""
    await websocket.accept()
    logger.info("flight_ws_connected")

    try:
        while True:
            try:
                flights = await flight_service.get_flights(
                    websocket.app.state.proxy,
                    websocket.app.state.cache,
                )
                data = [f.model_dump(mode="json") for f in flights]
                await websocket.send_text(json.dumps({"type": "flights", "data": data, "count": len(data)}))
            except Exception:
                logger.warning("flight_ws_fetch_error")
                await websocket.send_text(json.dumps({"type": "error", "message": "Failed to fetch flights"}))

            await asyncio.sleep(10)
    except WebSocketDisconnect:
        logger.info("flight_ws_disconnected")
    except Exception:
        logger.error("flight_ws_error")
