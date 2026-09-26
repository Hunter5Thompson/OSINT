"""Lifecycle tests for the GDELT clients shared by the CLI and scheduler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_close_clients_releases_neo4j_qdrant_and_redis() -> None:
    from gdelt_raw.clients import GDELTClients

    redis = MagicMock(aclose=AsyncMock())
    state = MagicMock()
    neo4j = MagicMock(close=AsyncMock())
    qdrant = MagicMock(close=AsyncMock())
    tei = MagicMock(aclose=AsyncMock())

    clients = GDELTClients(redis=redis, state=state, neo4j=neo4j, qdrant=qdrant, tei_client=tei)
    await clients.aclose()

    neo4j.close.assert_awaited_once()
    qdrant.close.assert_awaited_once()
    redis.aclose.assert_awaited_once()
    tei.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_clients_passes_active_spatial_index_to_gdelt_writer() -> None:
    from config import settings
    from gdelt_raw.clients import open_clients

    fake_index = object()
    neo4j_writer = MagicMock(return_value=MagicMock())
    qdrant_writer = MagicMock(return_value=MagicMock())

    with (
        patch("gdelt_raw.clients.aioredis.from_url", return_value=MagicMock()),
        patch("gdelt_raw.clients.GDELTState", return_value=MagicMock()),
        patch("gdelt_raw.clients.Neo4jWriter", neo4j_writer),
        patch("gdelt_raw.clients.AsyncQdrantClient", return_value=MagicMock()),
        patch("gdelt_raw.clients.QdrantWriter", qdrant_writer),
        patch(
            "gdelt_raw.clients.load_active_normalization_index",
            return_value=fake_index,
        ) as load_index,
    ):
        await open_clients()

    load_index.assert_called_once_with(
        settings.spatial_catalog_path,
        crosswalk_path=settings.spatial_country_crosswalk_path,
    )
    assert neo4j_writer.call_args.kwargs["spatial_index"] is fake_index
    assert qdrant_writer.call_args.kwargs["spatial_index"] is fake_index
