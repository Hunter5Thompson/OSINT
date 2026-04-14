"""WorldView Backend — FastAPI Application."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.routers import (
    aircraft,
    cables,
    earthquakes,
    eonet,
    firms,
    flights,
    gdacs,
    graph,
    hotspots,
    intel,
    rag,
    satellites,
    signals,
    vessels,
)
from app.services import vessel_service
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService
from app.services.signal_stream import get_signal_stream, redis_consumer_loop
from app.ws import flight_ws, vessel_ws

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize and cleanup shared resources."""
    # Startup
    proxy = ProxyService()
    await proxy.start()
    app.state.proxy = proxy

    cache = CacheService(settings.redis_url)
    await cache.connect()
    app.state.cache = cache

    # Start AISStream background collector
    await vessel_service.start_collector(cache)

    # Start Redis signals consumer
    signal_stream = get_signal_stream()
    signal_stop_event = asyncio.Event()
    signal_task = asyncio.create_task(
        redis_consumer_loop(signal_stream, signal_stop_event)
    )
    app.state.signal_stop_event = signal_stop_event
    app.state.signal_task = signal_task

    logger.info("backend_started", vllm_url=settings.vllm_url, vllm_model=settings.vllm_model)
    yield

    # Shutdown
    signal_stop_event.set()
    signal_task.cancel()
    try:
        await signal_task
    except (asyncio.CancelledError, Exception):
        pass
    await vessel_service.stop_collector()
    await proxy.stop()
    await cache.close()
    logger.info("backend_stopped")


app = FastAPI(
    title="WorldView Tactical Intelligence Platform",
    version="0.1.0",
    description="Backend API for WorldView — Tactical Intelligence Platform",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST Routers
app.include_router(flights.router, prefix="/api/v1")
app.include_router(satellites.router, prefix="/api/v1")
app.include_router(earthquakes.router, prefix="/api/v1")
app.include_router(vessels.router, prefix="/api/v1")
app.include_router(hotspots.router, prefix="/api/v1")
app.include_router(intel.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(cables.router, prefix="/api/v1")
app.include_router(firms.router, prefix="/api/v1")
app.include_router(aircraft.router, prefix="/api/v1")
app.include_router(eonet.router, prefix="/api/v1")
app.include_router(gdacs.router, prefix="/api/v1")
app.include_router(signals.router, prefix="/api")

# WebSocket Routers
app.include_router(flight_ws.router)
app.include_router(vessel_ws.router)


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str


class ClientConfig(BaseModel):
    cesium_ion_token: str
    default_layers: dict[str, bool]
    api_version: str


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(UTC),
        version="0.1.0",
    )


@app.get("/api/v1/config", response_model=ClientConfig)
async def client_config() -> ClientConfig:
    """Return client configuration. Never exposes secret keys."""
    return ClientConfig(
        cesium_ion_token=settings.cesium_ion_token,
        default_layers={
            "flights": True,
            "satellites": True,
            "earthquakes": True,
            "vessels": False,
            "cctv": False,
            "events": False,
            "cables": False,
            "pipelines": False,
            "firmsHotspots": True,
            "milAircraft": True,
            "eonet": False,
            "gdacs": False,
        },
        api_version="v1",
    )
