"""Regression tests for feeds.gdelt_raw_collector.

Focused on the name-shadowing bug introduced in commit e334440: the local
rebind ``settings = get_settings()`` inside ``run_once()`` shadowed the
module-level import of project ``Settings``, causing ``settings.qdrant_collection``
to read from ``GDELTSettings`` (which has no such field) and raise AttributeError
at scheduler-tick time.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


async def test_run_once_uses_project_qdrant_collection():
    """Regression: run_once must pass project-level settings.qdrant_collection
    to QdrantWriter, NOT the GDELTSettings local rebind (which has no such field).

    This test would have failed on the broken form because GDELTSettings raises
    AttributeError on .qdrant_collection.
    """
    captured: dict = {}

    class FakeQdrantWriter:
        def __init__(self, *, client, embed, collection: str):
            captured["collection"] = collection

    fake_redis = AsyncMock()
    fake_state = MagicMock()

    fake_neo4j = MagicMock()
    fake_neo4j.close = AsyncMock()

    fake_qdrant_client = MagicMock()

    with (
        patch(
            "feeds.gdelt_raw_collector.aioredis.from_url",
            return_value=fake_redis,
        ),
        patch(
            "feeds.gdelt_raw_collector.GDELTState",
            return_value=fake_state,
        ),
        patch(
            "feeds.gdelt_raw_collector.Neo4jWriter",
            return_value=fake_neo4j,
        ),
        patch(
            "feeds.gdelt_raw_collector.AsyncQdrantClient",
            return_value=fake_qdrant_client,
        ),
        patch(
            "feeds.gdelt_raw_collector.QdrantWriter",
            FakeQdrantWriter,
        ),
        patch(
            "feeds.gdelt_raw_collector.run_forward",
            new=AsyncMock(),
        ),
    ):
        from feeds.gdelt_raw_collector import run_once
        from config import settings as project_settings

        await run_once()

    assert "collection" in captured, "QdrantWriter was never constructed"
    assert captured["collection"] == project_settings.qdrant_collection, (
        f"run_once passed collection={captured['collection']!r} "
        f"but expected project-level {project_settings.qdrant_collection!r}. "
        "This indicates run_once() is reading qdrant_collection from GDELTSettings "
        "(the shadowed local) instead of the module-level project Settings."
    )


async def test_run_once_passes_gdelt_parquet_path_to_run_forward():
    """run_once must pass the GDELT-specific parquet_path (from GDELTSettings,
    env_prefix GDELT_) to run_forward, not some other settings object."""
    captured: dict = {}

    class FakeQdrantWriter:
        def __init__(self, *, client, embed, collection):
            pass

    fake_neo4j = MagicMock()
    fake_neo4j.close = AsyncMock()

    mock_run_forward = AsyncMock()

    with (
        patch("feeds.gdelt_raw_collector.aioredis.from_url", return_value=AsyncMock()),
        patch("feeds.gdelt_raw_collector.GDELTState", return_value=MagicMock()),
        patch("feeds.gdelt_raw_collector.Neo4jWriter", return_value=fake_neo4j),
        patch("feeds.gdelt_raw_collector.AsyncQdrantClient", return_value=MagicMock()),
        patch("feeds.gdelt_raw_collector.QdrantWriter", FakeQdrantWriter),
        patch("feeds.gdelt_raw_collector.run_forward", new=mock_run_forward),
    ):
        from feeds.gdelt_raw_collector import run_once
        from gdelt_raw.config import get_settings as get_gdelt_settings

        await run_once()

        gdelt_cfg = get_gdelt_settings()
        _, call_kwargs = mock_run_forward.call_args
        positional_args = mock_run_forward.call_args[0]

        # run_forward(state, neo4j, qdrant, Path(gdelt_cfg.parquet_path))
        # 4th positional argument is the parquet path
        assert len(positional_args) == 4, (
            f"Expected run_forward to be called with 4 positional args, got {len(positional_args)}"
        )
        actual_path = positional_args[3]
        assert actual_path == Path(gdelt_cfg.parquet_path), (
            f"run_forward received parquet_path={actual_path!r} "
            f"but expected GDELTSettings.parquet_path={gdelt_cfg.parquet_path!r}"
        )
