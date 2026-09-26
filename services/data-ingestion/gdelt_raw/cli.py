"""click-based CLI for GDELT raw ingestion."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import httpx

from gdelt_raw.clients import open_clients
from gdelt_raw.config import get_settings
from gdelt_raw.recovery import reconcile_forward_state, replay_pending
from gdelt_raw.run import run_backfill, run_forward


def _run(coro):
    return asyncio.run(coro)


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


@click.group()
def main():
    """GDELT raw-files ingestion CLI."""


@main.command()
def status():
    """Show last processed slice and pending counts."""
    async def _go():
        clients = await open_clients()
        state = clients.state
        try:
            for store in ("parquet", "neo4j", "qdrant"):
                last = await state.get_last_slice(store)
                click.echo(f"last_slice[{store:>7}]: {last}")
            for store in ("neo4j", "qdrant"):
                pending = await state.list_pending(store, limit=100)
                click.echo(f"pending[{store:>6}]: {len(pending)}")
        finally:
            await clients.aclose()
    _run(_go())


@main.command()
def reconcile():
    """Report stores whose last_slice trails the parquet checkpoint (WP-10)."""
    async def _go():
        clients = await open_clients()
        state = clients.state
        try:
            report = await reconcile_forward_state(state)
            click.echo(f"parquet last_slice: {report['parquet']}")
            for store in ("neo4j", "qdrant"):
                flag = "  LAGS" if store in report["lagging"] else ""
                click.echo(f"{store:>7} last_slice: {report[store]}{flag}")
            if report["lagging"]:
                click.echo(f"\nLagging: {report['lagging']} — run `forward` "
                           f"or `resume <job>` to replay pending slices.")
        finally:
            await clients.aclose()
    _run(_go())


@main.command()
def forward():
    """Run a single forward tick."""
    async def _go():
        settings = get_settings()
        clients = await open_clients()
        state, neo4j, qdrant = clients.state, clients.neo4j, clients.qdrant
        try:
            await run_forward(state, neo4j, qdrant, Path(settings.parquet_path))
        finally:
            await clients.aclose()
    _run(_go())
    click.echo("forward tick complete")


# Minute precision lets a backfill target a gap's exact slices instead of whole days.
_BACKFILL_FORMATS = ["%Y-%m-%d", "%Y-%m-%dT%H:%M"]


@main.command()
@click.option("--from", "from_date", required=True,
              type=click.DateTime(formats=_BACKFILL_FORMATS),
              help="Backfill start (inclusive, UTC), YYYY-MM-DD or YYYY-MM-DDTHH:MM")
@click.option("--to", "to_date", default=None,
              type=click.DateTime(formats=_BACKFILL_FORMATS),
              help="Backfill end (inclusive, UTC), YYYY-MM-DD or YYYY-MM-DDTHH:MM; "
                   "default=yesterday UTC")
@click.option("--parallel", default=4, type=int)
def backfill(from_date: datetime, to_date: datetime | None, parallel: int):
    """Historical backfill."""
    _now = datetime.now(UTC).replace(tzinfo=None)
    to_date = to_date or (_now - timedelta(days=1))
    job_id = f"backfill-{_now.strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:4]}"
    click.echo(f"Job: {job_id}  {from_date:%Y-%m-%d %H:%M} → {to_date:%Y-%m-%d %H:%M}")

    async def _go():
        settings = get_settings()
        clients = await open_clients()
        state, neo4j, qdrant = clients.state, clients.neo4j, clients.qdrant
        try:
            await run_backfill(
                from_date, to_date,
                state=state, neo4j_writer=neo4j, qdrant_writer=qdrant,
                parquet_base=Path(settings.parquet_path),
                job_id=job_id, parallel=parallel,
            )
        finally:
            await clients.aclose()
    _run(_go())


@main.command()
@click.argument("job_id")
def resume(job_id: str):
    """Resume a backfill job: re-enqueue failed slices, then replay neo4j/qdrant pending."""
    async def _go():
        from gdelt_raw.run import resume_backfill_pending
        settings = get_settings()
        clients = await open_clients()
        state, neo4j, qdrant = clients.state, clients.neo4j, clients.qdrant
        try:
            n = await resume_backfill_pending(state, job_id)
            click.echo(f"Re-enqueued {n} failed slice(s) for job {job_id}")
            await replay_pending(
                state, parquet_base=Path(settings.parquet_path),
                neo4j_writer=neo4j, qdrant_writer=qdrant,
            )
            click.echo("replay_pending complete")
        finally:
            await clients.aclose()
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
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
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
            clients = await open_clients()
            state, neo4j, qdrant = clients.state, clients.neo4j, clients.qdrant
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

        if state is not None and neo4j is not None and qdrant is not None:
            with contextlib.suppress(Exception):
                await clients.aclose()

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
