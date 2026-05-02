"""odin-infra-atlas CLI — regenerate static infra GeoJSON datasets."""

from __future__ import annotations

from pathlib import Path

import click

from infra_atlas.build_datacenters import build_datacenters
from infra_atlas.build_pipelines import build_pipelines_from_seed, load_seed
from infra_atlas.build_refineries import build_refineries

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


@cli.command()
@click.option(
    "--existing",
    type=click.Path(exists=True, path_type=Path),
    default=FRONTEND_DATA / "refineries.geojson",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=FRONTEND_DATA / "refineries.geojson",
)
def refineries(existing: Path, out: Path) -> None:
    """Enrich existing refineries.geojson with Wikidata image + provenance."""
    n = build_refineries(out, existing_path=existing)
    click.echo(f"Wrote {n} refineries → {out.relative_to(REPO_ROOT)}")


@cli.command()
@click.option(
    "--existing",
    type=click.Path(exists=True, path_type=Path),
    default=FRONTEND_DATA / "datacenters.geojson",
)
@click.option(
    "--seed",
    type=click.Path(exists=True, path_type=Path),
    default=SEEDS_DIR / "datacenters_hyperscaler.yaml",
)
@click.option(
    "--centroids",
    type=click.Path(exists=True, path_type=Path),
    default=SEEDS_DIR / "known_city_centroids.json",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=FRONTEND_DATA / "datacenters.geojson",
)
def datacenters(existing: Path, seed: Path, centroids: Path, out: Path) -> None:
    """Enrich existing datacenters.geojson + apply hyperscaler seed."""
    n = build_datacenters(
        out, existing_path=existing, seed_path=seed, centroids_path=centroids
    )
    click.echo(f"Wrote {n} datacenters → {out.relative_to(REPO_ROOT)}")
