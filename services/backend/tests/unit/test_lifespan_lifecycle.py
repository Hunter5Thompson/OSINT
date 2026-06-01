"""Backend lifespan rollback and singleton cleanup tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.main import lifespan
from app.services import neo4j_client, qdrant_client


@pytest.mark.asyncio
async def test_lifespan_rolls_back_proxy_when_cache_startup_fails() -> None:
    proxy = MagicMock(start=AsyncMock(), stop=AsyncMock())
    cache = MagicMock(
        connect=AsyncMock(side_effect=RuntimeError("redis startup failed")),
        close=AsyncMock(),
    )

    with (
        patch("app.main.ProxyService", return_value=proxy),
        patch("app.main.CacheService", return_value=cache),
    ):
        with pytest.raises(RuntimeError, match="redis startup failed"):
            async with lifespan(FastAPI()):
                pass

    proxy.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_closes_backend_singletons_on_shutdown() -> None:
    proxy = MagicMock(start=AsyncMock(), stop=AsyncMock())
    cache = MagicMock(connect=AsyncMock(), close=AsyncMock())
    promoter_config = SimpleNamespace(
        enabled=False,
        firms_enabled=False,
        telegram_enabled=False,
        severity_enabled=False,
    )

    with (
        patch("app.main.ProxyService", return_value=proxy),
        patch("app.main.CacheService", return_value=cache),
        patch("app.main.vessel_service.start_collector", new=AsyncMock()),
        patch("app.main.vessel_service.stop_collector", new=AsyncMock()),
        patch("app.main.redis_consumer_loop", new=AsyncMock()),
        patch("app.main.ReconManifestLoader") as manifest_loader,
        patch(
            "app.services.incident_promoter.config.PromoterConfig.from_env",
            return_value=promoter_config,
        ),
        patch.object(
            qdrant_client,
            "close_qdrant_client",
            new=AsyncMock(),
        ) as close_qdrant,
        patch.object(
            neo4j_client,
            "close_driver",
            new=AsyncMock(),
            create=True,
        ) as close_neo4j,
    ):
        manifest_loader.return_value.list_scenes.return_value = []
        async with lifespan(FastAPI()):
            pass

    close_qdrant.assert_awaited_once()
    close_neo4j.assert_awaited_once()
