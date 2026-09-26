"""One client builder for scheduler and CLI.

The CLI (backfill/resume) used to build its own QdrantWriter without
embed_batch, so a backfill embedded ~900 GKG docs per slice one HTTP call at
a time (~27 s/slice) while the scheduler batched them (PR #109)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner


@pytest.fixture
def fake_backends(monkeypatch):
    redis = MagicMock(aclose=AsyncMock())
    neo4j = MagicMock(close=AsyncMock())
    qdrant_client = MagicMock(close=AsyncMock())
    monkeypatch.setattr("gdelt_raw.clients.load_active_normalization_index",
                        lambda *a, **k: None)
    monkeypatch.setattr("gdelt_raw.clients.aioredis.from_url", lambda *a, **k: redis)
    monkeypatch.setattr("gdelt_raw.clients.Neo4jWriter", lambda **k: neo4j)
    monkeypatch.setattr("gdelt_raw.clients.AsyncQdrantClient", lambda **k: qdrant_client)
    return redis, neo4j, qdrant_client


@pytest.mark.asyncio
async def test_open_clients_batches_tei_embeds_and_closes_everything(fake_backends):
    from gdelt_raw.clients import open_clients

    redis, neo4j, qdrant_client = fake_backends
    clients = await open_clients()
    assert clients.qdrant._embed_batch is not None
    await clients.aclose()
    neo4j.close.assert_awaited_once()
    qdrant_client.close.assert_awaited_once()
    redis.aclose.assert_awaited_once()
    assert clients.tei_client.is_closed


def test_cli_backfill_uses_batched_embeds(fake_backends, monkeypatch):
    captured = {}

    async def fake_run_backfill(start, end, **kwargs):
        captured["qdrant"] = kwargs["qdrant_writer"]

    monkeypatch.setattr("gdelt_raw.cli.run_backfill", fake_run_backfill)
    from gdelt_raw.cli import main

    result = CliRunner().invoke(main, ["backfill", "--from", "2026-08-14T18:00",
                                       "--to", "2026-08-14T18:15"])
    assert result.exit_code == 0, result.output
    assert captured["qdrant"]._embed_batch is not None
