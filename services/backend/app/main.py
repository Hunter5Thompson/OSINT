"""WorldView Backend — FastAPI Application."""

import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.routers import (
    aircraft,
    almanac,
    cables,
    earthquakes,
    eonet,
    firms,
    flights,
    gdacs,
    graph,
    hotspots,
    incidents,
    intel,
    landing,
    rag,
    reports,
    satellites,
    signals,
    vessels,
)
from app.routers import recon as recon_router_module
from app.services import vessel_service
from app.services.cache_service import CacheService
from app.services.proxy_service import ProxyService
from app.services.recon_manifest import (
    ReconManifestLoader,
    ReconManifestMissingError,
)
from app.services.signal_stream import get_signal_stream, redis_consumer_loop
from app.static.cached_static import CachedStaticFiles
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

    # Report schema — idempotent unique constraints (id + scope_key) for briefing dossiers
    from app.services.report_store import bootstrap_report_schema
    app.state.report_schema_ready = False
    try:
        await bootstrap_report_schema()
        app.state.report_schema_ready = True
    except Exception as exc:  # noqa: BLE001
        # bootstrap failed → report_schema_ready stays False; save endpoint (Task 8) returns 503
        logger.warning("report_schema_bootstrap_failed", error=str(exc))

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

    # Recon manifest — load into app.state for the recon router
    recon_manifest_path = Path(os.environ.get(
        "RECON_MANIFEST_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "recon_manifest.json"),
    ))
    recon_loader = ReconManifestLoader(recon_manifest_path)
    try:
        recon_loader.load()
        logger.info("recon_manifest_loaded",
                    path=str(recon_manifest_path),
                    scenes=len(recon_loader.list_scenes()))
    except ReconManifestMissingError:
        logger.warning("recon_manifest_missing",
                       path=str(recon_manifest_path),
                       hint="run ./odin.sh recon bootstrap")
    app.state.recon_manifest = recon_loader

    # --- Auto-promoter (full wiring) ---
    from app.services import incident_store as _incident_store_module
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector
    from app.services.incident_promoter.promoter import Promoter
    from app.services.incident_stream import get_incident_stream

    def _promoter_clock() -> datetime:
        return datetime.now(UTC)
    _promoter_cfg = PromoterConfig.from_env()
    _cluster_store = ClusterStore(clock=_promoter_clock)
    app.state.cluster_store = _cluster_store
    app.state.promoter_config = _promoter_cfg

    _detectors: list = []
    if _promoter_cfg.firms_enabled:
        _detectors.append(FIRMSGeoClusterDetector(config=_promoter_cfg, clock=_promoter_clock))
    if _promoter_cfg.telegram_enabled:
        _detectors.append(TelegramTopicDetector(config=_promoter_cfg, clock=_promoter_clock))
    if _promoter_cfg.severity_enabled:
        _detectors.append(SeverityBurstDetector(config=_promoter_cfg, clock=_promoter_clock))

    _promoter = Promoter(
        signal_stream=get_signal_stream(),
        cluster_store=_cluster_store,
        incident_store=_incident_store_module,
        incident_event_stream=get_incident_stream(),
        config=_promoter_cfg,
        clock=_promoter_clock,
        detectors=_detectors,
    )
    if _promoter_cfg.enabled:
        _promoter_task = asyncio.create_task(_promoter.run(), name="promoter")
        _sweeper_task = asyncio.create_task(_promoter.sweeper_loop(), name="promoter-sweeper")
    else:
        _promoter_task = None
        _sweeper_task = None

    logger.info("backend_started", vllm_url=settings.vllm_url, vllm_model=settings.vllm_model)
    yield

    # Shutdown
    _promoter.request_stop()
    for _t in (_promoter_task, _sweeper_task):
        if _t is None:
            continue
        _t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _t

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

# REST Routers — unified prefix with /api/v1 back-compat aliases (remove 2026-05-21)
for r in (
    flights.router, satellites.router, earthquakes.router, vessels.router,
    hotspots.router, intel.router, rag.router, graph.router, cables.router,
    firms.router, aircraft.router, eonet.router, gdacs.router, reports.router,
):
    app.include_router(r, prefix="/api")
    app.include_router(r, prefix="/api/v1")

# Recon router — dual /api + /api/v1 prefix (matches existing convention)
app.include_router(recon_router_module.router, prefix="/api")
app.include_router(recon_router_module.router, prefix="/api/v1")

# Static PLY assets for recon (immutable Cache-Control, Range supported)
_recon_static_dir = Path(os.environ.get(
    "RECON_STATIC_DIR",
    str(Path(__file__).resolve().parent.parent / "static" / "recon"),
))
_recon_static_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/recon",
    CachedStaticFiles(directory=str(_recon_static_dir)),
    name="recon_static",
)

# S1 Hlidskjalf routers (already at /api, no alias needed)
app.include_router(signals.router, prefix="/api")
app.include_router(almanac.router, prefix="/api")
app.include_router(landing.router, prefix="/api")
app.include_router(incidents.router, prefix="/api")

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


async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(UTC),
        version="0.1.0",
    )


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


# Primary mounts at /api + /api/v1 back-compat aliases (remove 2026-05-21)
app.add_api_route("/api/health", health, response_model=HealthResponse, methods=["GET"])
app.add_api_route("/api/config", client_config, response_model=ClientConfig, methods=["GET"])
app.add_api_route(
    "/api/v1/health",
    health,
    response_model=HealthResponse,
    methods=["GET"],
    include_in_schema=False,
)
app.add_api_route(
    "/api/v1/config",
    client_config,
    response_model=ClientConfig,
    methods=["GET"],
    include_in_schema=False,
)
