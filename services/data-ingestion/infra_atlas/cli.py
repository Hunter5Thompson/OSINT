"""odin-infra-atlas CLI — regenerate static infra GeoJSON datasets."""

from __future__ import annotations

from pathlib import Path

import click

from infra_atlas.build_pipelines import build_pipelines_from_seed, load_seed

REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS_DIR = Path(__file__).resolve().parent / "seeds"
FRONTEND_DATA = REPO_ROOT / "services" / "frontend" / "public" / "data"


@click.group()
def cli() -> None:
    """Regenerate Worldview infrastructure GeoJSON datasets."""


@cli.command()
@click.option(
    "--seed",
    type=click.Path(exists=True, path_type=Path),
    default=SEEDS_DIR / "pipelines.yaml",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=FRONTEND_DATA / "pipelines.geojson",
)
def pipelines(seed: Path, out: Path) -> None:
    """Build pipelines.geojson from the curated seed."""
    seeds = load_seed(seed)
    build_pipelines_from_seed(seeds, out)
    click.echo(f"Wrote {len(seeds)} pipelines → {out.relative_to(REPO_ROOT)}")
