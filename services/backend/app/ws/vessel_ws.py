"""WebSocket endpoint for AIS vessel data with burst pattern."""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

logger = structlog.get_logger()

router = APIRouter()


@router.websocket("/ws/vessels")
async def vessel_stream(websocket: WebSocket) -> None:
    """Push vessel data using burst pattern: 20s connect to AISStream, 60s from cache."""
    await websocket.accept()
    logger.info("vessel_ws_connected")

    try:
        while True:
            # Try to get cached vessel data
            cached = await websocket.app.state.cache.get("vessels:all")
            if cached:
                await websocket.send_text(
                    json.dumps({"type": "vessels", "data": cached, "count": len(cached)})
                )
            else:
                # Burst: connect to AISStream for 20 seconds
                vessels = await _burst_fetch_ais(websocket)
                if vessels:
                    await websocket.app.state.cache.set("vessels:all", vessels, ttl_seconds=60)
                    await websocket.send_text(
                        json.dumps({"type": "vessels", "data": vessels, "count": len(vessels)})
                    )
                else:
                    await websocket.send_text(
                        json.dumps({"type": "vessels", "data": [], "count": 0})
                    )

            # Wait 60 seconds before next cycle
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        logger.info("vessel_ws_disconnected")
    except Exception:
        logger.error("vessel_ws_error")


async def _burst_fetch_ais(websocket: WebSocket) -> list[dict[str, object]]:
    """Connect to AISStream for a burst of 20 seconds, collecting vessel positions."""
    if not settings.aisstream_api_key:
        logger.warning("aisstream_no_api_key")
        return []

    vessels: list[dict[str, object]] = []

    try:
        import websockets

        subscribe_msg = json.dumps({
            "APIKey": settings.aisstream_api_key,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
        })

        async with websockets.connect(settings.aisstream_ws_url) as ws:
            await ws.send(subscribe_msg)

            try:
                async with asyncio.timeout(20):
                    async for msg in ws:
                        data = json.loads(msg)
                        meta = data.get("MetaData", {})
                        pos = data.get("Message", {}).get("PositionReport", {})
                        if pos:
                            vessels.append({
                                "mmsi": meta.get("MMSI", 0),
                                "name": meta.get("ShipName", "").strip() or None,
                                "latitude": pos.get("Latitude", 0),
                                "longitude": pos.get("Longitude", 0),
                                "speed_knots": pos.get("Sog", 0),
                                "course": pos.get("Cog", 0),
                                "ship_type": meta.get("ShipType", 0),
                                "destination": None,
                            })
            except TimeoutError:
                pass

        logger.info("ais_burst_complete", count=len(vessels))
    except ImportError:
        logger.warning("websockets_not_installed")
    except Exception:
        logger.warning("ais_burst_failed")

    return vessels
