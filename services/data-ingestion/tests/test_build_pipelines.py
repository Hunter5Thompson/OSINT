"""Tests for the pipeline builder."""

import json
from pathlib import Path

import pytest

from infra_atlas.build_pipelines import (
    PipelineSeed,
    build_pipelines_from_seed,
    load_seed,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_load_seed_returns_seeds() -> None:
    seeds = load_seed(FIXTURE_DIR / "pipeline_seed_sample.yaml")
    assert len(seeds) == 2
    assert seeds[0].name == "Nord Stream 1"
    assert seeds[0].source_url.startswith("https://en.wikipedia.org/")
    assert seeds[0].route[0] == (28.7, 60.5)


def test_load_seed_rejects_route_with_one_point(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "pipelines:\n"
        "  - name: Bad\n"
        "    tier: major\n"
        "    type: oil\n"
        "    status: active\n"
        "    operator: X\n"
        "    capacity_bcm: null\n"
        "    length_km: null\n"
        "    countries: [X]\n"
        "    source_url: https://example.com\n"
        "    route: [[0, 0]]\n"
    )
    with pytest.raises(ValueError, match="route must have"):
        load_seed(bad)


def test_load_seed_rejects_missing_source_url(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "pipelines:\n"
        "  - name: Bad\n"
        "    tier: major\n"
        "    type: oil\n"
        "    status: active\n"
        "    operator: X\n"
        "    capacity_bcm: null\n"
        "    length_km: null\n"
        "    countries: [X]\n"
        "    route: [[0, 0], [1, 1]]\n"
    )
    with pytest.raises(KeyError, match="source_url"):
        load_seed(bad)


def test_build_emits_valid_geojson(tmp_path: Path) -> None:
    seeds = load_seed(FIXTURE_DIR / "pipeline_seed_sample.yaml")
    out = tmp_path / "pipelines.geojson"
    build_pipelines_from_seed(seeds, out)
    data = json.loads(out.read_text())

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2

    nord = data["features"][0]
    assert nord["type"] == "Feature"
    assert nord["geometry"]["type"] == "LineString"
    assert nord["geometry"]["coordinates"][0] == [28.7, 60.5]
    assert nord["properties"]["name"] == "Nord Stream 1"
    assert nord["properties"]["source_url"].startswith("https://en.wikipedia.org/")
    assert "qid" not in nord["properties"]  # Q-ID is optional, sample lacks it


def test_seed_dataclass_route_is_list_of_tuples() -> None:
    seeds = load_seed(FIXTURE_DIR / "pipeline_seed_sample.yaml")
    assert isinstance(seeds[0], PipelineSeed)
    assert all(isinstance(p, tuple) and len(p) == 2 for p in seeds[0].route)
