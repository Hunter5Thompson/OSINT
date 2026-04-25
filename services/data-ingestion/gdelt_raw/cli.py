"""click-based CLI for GDELT raw ingestion."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import click

from gdelt_raw.config import get_settings


def _run(coro):
    return asyncio.run(coro)


@click.group()
def main():
    """GDELT raw-files ingestion CLI."""


@main.command()
def status():
    """Show last processed slice per store, pending counts, today's totals."""
    settings = get_settings()
    click.echo(f"Config mode: {settings.filter_mode}")
    click.echo(f"CAMEO allowlist: {settings.cameo_root_allowlist}")
    click.echo("(full implementation wires Redis client via get_redis)")


@main.command()
def forward():
    """Run a single forward tick (useful for debugging)."""
    click.echo("forward tick (wires via get_clients and run_forward) — stub")


@main.command()
@click.option("--from", "from_date", required=True,
              type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Backfill start (inclusive), format YYYY-MM-DD")
@click.option("--to", "to_date", default=None,
              type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Backfill end (inclusive), default=yesterday UTC")
def backfill(from_date: datetime, to_date: datetime | None):
    """Historical backfill for a date range."""
    to_date = to_date or (datetime.utcnow() - timedelta(days=1))
    job_id = f"backfill-{datetime.utcnow().strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:4]}"
    click.echo(f"Job: {job_id}  {from_date:%Y-%m-%d} → {to_date:%Y-%m-%d}")
    click.echo("(full implementation awaits get_clients + run_backfill wiring)")


@main.command()
@click.argument("job_id")
def resume(job_id: str):
    """Resume a backfill job."""
    click.echo(f"Resume job: {job_id}")


@main.command()
def doctor():
    """Health-check GDELT CDN, Neo4j, Qdrant, TEI, Parquet volume."""
    click.echo("doctor checks (wires via httpx/neo4j/qdrant clients) — stub")


@main.command()
def config():
    """Dump current settings."""
    settings = get_settings()
    click.echo(json.dumps(settings.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    main()
