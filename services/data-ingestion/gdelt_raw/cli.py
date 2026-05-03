"""click-based CLI for GDELT raw ingestion."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import httpx
import redis.asyncio as aioredis
from qdrant_client import AsyncQdrantClient

from config import Settings
from gdelt_raw.config import get_settings
from gdelt_raw.recovery import replay_pending
from gdelt_raw.run import run_backfill, run_forward
from gdelt_raw.state import GDELTState
from gdelt_raw.writers.neo4j_writer import Neo4jWriter
from gdelt_raw.writers.qdrant_writer import QdrantWriter, default_tei_embed


def _run(coro):
    return asyncio.run(coro)


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


async def _get_clients():
    r = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    state = GDELTState(r)
    neo4j = Neo4jWriter(
        uri=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
    )
    qdrant_client = AsyncQdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333")
    )
    tei_url = os.getenv("TEI_EMBED_URL", "http://localhost:8001")

    async def embed(text: str) -> list[float]:
        return await default_tei_embed(text, tei_url=tei_url)

    qdrant = QdrantWriter(
        client=qdrant_client,
        embed=embed,
        collection=Settings(_env_file=None).qdrant_collection,
    )
    return state, neo4j, qdrant


@click.group()
def main():
    """GDELT raw-files ingestion CLI."""


@main.command()
def status():
    """Show last processed slice and pending counts."""
    async def _go():
        state, neo4j, _ = await _get_clients()
        try:
            for store in ("parquet", "neo4j", "qdrant"):
                last = await state.get_last_slice(store)
                click.echo(f"last_slice[{store:>7}]: {last}")
            for store in ("neo4j", "qdrant"):
                pending = await state.list_pending(store, limit=100)
                click.echo(f"pending[{store:>6}]: {len(pending)}")
        finally:
            await neo4j.close()
    _run(_go())


@main.command()
def forward():
    """Run a single forward tick."""
    async def _go():
        settings = get_settings()
        state, neo4j, qdrant = await _get_clients()
        try:
            await run_forward(state, neo4j, qdrant, Path(settings.parquet_path))
        finally:
            await neo4j.close()
    _run(_go())
    click.echo("forward tick complete")


@main.command()
@click.option("--from", "from_date", required=True,
              type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Backfill start (inclusive), format YYYY-MM-DD")
@click.option("--to", "to_date", default=None,
              type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Backfill end (inclusive), default=yesterday UTC")
@click.option("--parallel", default=4, type=int)
def backfill(from_date: datetime, to_date: datetime | None, parallel: int):
    """Historical backfill."""
    _now = datetime.now(UTC).replace(tzinfo=None)
    to_date = to_date or (_now - timedelta(days=1))
    job_id = f"backfill-{_now.strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:4]}"
    click.echo(f"Job: {job_id}  {from_date:%Y-%m-%d} → {to_date:%Y-%m-%d}")

    async def _go():
        settings = get_settings()
        state, neo4j, qdrant = await _get_clients()
        try:
            await run_backfill(
                from_date, to_date,
                state=state, neo4j_writer=neo4j, qdrant_writer=qdrant,
                parquet_base=Path(settings.parquet_path),
                job_id=job_id, parallel=parallel,
            )
        finally:
            await neo4j.close()
    _run(_go())


@main.command()
@click.argument("job_id")
def resume(job_id: str):
    """Resume a backfill job: re-enqueue failed slices, then replay neo4j/qdrant pending."""
    async def _go():
        from gdelt_raw.run import resume_backfill_pending
        settings = get_settings()
        state, neo4j, qdrant = await _get_clients()
        try:
            n = await resume_backfill_pending(state, job_id)
            click.echo(f"Re-enqueued {n} failed slice(s) for job {job_id}")
            await replay_pending(
                state, parquet_base=Path(settings.parquet_path),
                neo4j_writer=neo4j, qdrant_writer=qdrant,
            )
            click.echo("replay_pending complete")
        finally:
            await neo4j.close()
    _run(_go())


@main.command()
def doctor():
    """Health-check all dependencies."""
    async def _check():
        settings = get_settings()
        errors = []
        state = neo4j = qdrant = None

        # GDELT CDN
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{settings.base_url}/lastupdate.txt")
                r.raise_for_status()
            click.echo("GDELT CDN:       ✓")
        except Exception as e:
            click.echo(f"GDELT CDN:       ✗ {e}")
            errors.append("gdelt")

        # Parquet volume
        path = Path(settings.parquet_path)
        if path.exists() and os.access(path, os.W_OK):
            click.echo(f"Parquet volume:  ✓ {path} (writable)")
        else:
            click.echo(f"Parquet volume:  ✗ {path} missing/not-writable")
            errors.append("parquet")

        # Redis
        try:
            state, neo4j, qdrant = await _get_clients()
            await state.r.ping()
            click.echo("Redis:           ✓")
        except Exception as e:
            click.echo(f"Redis:           ✗ {e}")
            errors.append("redis")

        # Neo4j
        try:
            async with neo4j._driver.session() as s:
                await s.run("RETURN 1")
            click.echo("Neo4j:           ✓")
        except Exception as e:
            click.echo(f"Neo4j:           ✗ {e}")
            errors.append("neo4j")

        # Qdrant — real call, not just assume
        try:
            cols = await qdrant._client.get_collections()
            names = [c.name for c in cols.collections]
            click.echo(f"Qdrant:          ✓ collections={names}")
        except Exception as e:
            click.echo(f"Qdrant:          ✗ {e}")
            errors.append("qdrant")

        # TEI — send a tiny embedding to confirm the dim
        try:
            tei_url = os.getenv("TEI_EMBED_URL", "http://localhost:8001")
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{tei_url}/embed", json={"inputs": "health"})
                r.raise_for_status()
                data = r.json()
                vec = data[0] if isinstance(data[0], list) else data
                click.echo(f"TEI:             ✓ dim={len(vec)}")
        except Exception as e:
            click.echo(f"TEI:             ✗ {e}")
            errors.append("tei")

        try:
            if neo4j is not None:
                await neo4j.close()
        except Exception:
            pass

        # Filter config summary (quick sanity check)
        click.echo(f"Filter mode:     {settings.filter_mode}")
        click.echo(f"CAMEO roots:     {settings.cameo_root_allowlist}")
        click.echo(f"Themes: α={len(settings.theme_allowlist)} "
                   f"nuclear={len(settings.nuclear_override_themes)}")

        if errors:
            raise SystemExit(1)

    _run(_check())


@main.command()
def config():
    """Dump current settings."""
    settings = get_settings()
    click.echo(json.dumps(settings.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    main()
