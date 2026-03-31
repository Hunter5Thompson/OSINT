"""WorldView Backend — FastAPI Application."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.routers import cables, earthquakes, flights, graph, hotspots, intel, rag, satellites, vessels
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService
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

    logger.info("backend_started", vllm_url=settings.vllm_url, vllm_model=settings.vllm_model)
    yield

    # Shutdown
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
        timestamp=datetime.now(timezone.utc),
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
        },
        api_version="v1",
    )
