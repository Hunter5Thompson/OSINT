"""Lifecycle tests for GDELT raw CLI clients."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_close_clients_releases_neo4j_qdrant_and_redis() -> None:
    from gdelt_raw.cli import _close_clients

    state = MagicMock()
    state.r = MagicMock(aclose=AsyncMock())
    neo4j = MagicMock(close=AsyncMock())
    qdrant = MagicMock(close=AsyncMock())

    await _close_clients(state, neo4j, qdrant)

    neo4j.close.assert_awaited_once()
    qdrant.close.assert_awaited_once()
    state.r.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_clients_passes_active_spatial_index_to_gdelt_writer() -> None:
    from config import settings
    from gdelt_raw.cli import _get_clients

    fake_index = object()
    neo4j_writer = MagicMock(return_value=MagicMock())
    qdrant_writer = MagicMock(return_value=MagicMock())

    with (
        patch("gdelt_raw.cli.aioredis.from_url", return_value=MagicMock()),
        patch("gdelt_raw.cli.GDELTState", return_value=MagicMock()),
        patch("gdelt_raw.cli.Neo4jWriter", neo4j_writer),
        patch("gdelt_raw.cli.AsyncQdrantClient", return_value=MagicMock()),
        patch("gdelt_raw.cli.QdrantWriter", qdrant_writer),
        patch(
            "gdelt_raw.cli.load_active_normalization_index",
            return_value=fake_index,
        ) as load_index,
    ):
        await _get_clients()

    load_index.assert_called_once_with(
        settings.spatial_catalog_path,
        crosswalk_path=settings.spatial_country_crosswalk_path,
    )
    assert neo4j_writer.call_args.kwargs["spatial_index"] is fake_index
    assert qdrant_writer.call_args.kwargs["spatial_index"] is fake_index
