"""Tests for the datacenter enrichment builder."""

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from infra_atlas.build_datacenters import (
    CityCentroidViolation,
    build_datacenters,
    haversine_km,
)

FIXTURE = Path(__file__).parent / "fixtures"
SEEDS_DIR = Path(__file__).resolve().parents[1] / "infra_atlas" / "seeds"


def test_existing_coord_replaced_when_wikidata_distance_exceeds_5km(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_datacenter_sample.json").read_text()))
    seed = tmp_path / "seed.yaml"
    seed.write_text("datacenters: []\n")
    out = tmp_path / "datacenters.geojson"

    build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    data = json.loads(out.read_text())

    ld8 = next(f for f in data["features"] if f["properties"]["name"] == "Equinix LD8")
    # Wikidata says (-0.0066, 51.5142); existing said (-0.5, 51.5). Distance > 5 km.
    assert ld8["geometry"]["coordinates"] == [-0.0066, 51.5142]
    assert ld8["properties"]["coord_quality"] == "wikidata_verified"
    assert ld8["properties"]["coord_source"] == "wikidata"
    assert ld8["properties"]["qid"] == "Q5234567"


def test_existing_unmatched_marked_legacy(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_datacenter_sample.json").read_text()))
    seed = tmp_path / "seed.yaml"
    seed.write_text("datacenters: []\n")
    out = tmp_path / "datacenters.geojson"

    build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    data = json.loads(out.read_text())
    rand = next(f for f in data["features"] if f["properties"]["name"] == "Random Existing DC")
    assert rand["properties"]["coord_quality"] == "legacy"


def test_seed_overrides_existing_and_marks_campus_verified(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_datacenter_sample.json").read_text()))
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "datacenters:\n"
        "  - name: AWS US-East-1 (Ashburn)\n"
        "    operator: Amazon Web Services\n"
        "    tier: hyperscaler\n"
        "    capacity_mw: 700\n"
        "    country: US\n"
        "    city: Ashburn\n"
        "    lon: -77.4575\n"
        "    lat: 39.0260\n"
        "    coord_source: https://baxtel.com/data-center/aws-us-east-1\n"
    )
    out = tmp_path / "datacenters.geojson"

    build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    data = json.loads(out.read_text())
    aws = next(f for f in data["features"] if f["properties"]["name"] == "AWS US-East-1 (Ashburn)")
    assert aws["geometry"]["coordinates"] == [-77.4575, 39.0260]
    assert aws["properties"]["capacity_mw"] == 700
    assert aws["properties"]["coord_quality"] == "campus_verified"
    assert aws["properties"]["coord_source"].startswith("https://")


def test_seed_with_city_centroid_coords_is_rejected(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "datacenters:\n"
        "  - name: Lazy DC\n"
        "    operator: Acme\n"
        "    tier: hyperscaler\n"
        "    capacity_mw: 100\n"
        "    country: DE\n"
        "    city: Frankfurt\n"
        "    lon: 8.6821\n"
        "    lat: 50.1109\n"
        "    coord_source: https://example.com\n"
    )
    out = tmp_path / "datacenters.geojson"

    with pytest.raises(CityCentroidViolation, match="Frankfurt"):
        build_datacenters(
            out,
            existing_path=FIXTURE / "existing_datacenters_sample.geojson",
            seed_path=seed,
            centroids_path=SEEDS_DIR / "known_city_centroids.json",
        )


def test_seed_without_coord_source_is_rejected(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "datacenters:\n"
        "  - name: Unsourced DC\n"
        "    operator: Acme\n"
        "    tier: hyperscaler\n"
        "    capacity_mw: 100\n"
        "    country: US\n"
        "    city: Somewhere\n"
        "    lon: -100.0\n"
        "    lat: 40.0\n"
    )
    out = tmp_path / "datacenters.geojson"

    with pytest.raises(KeyError, match="coord_source"):
        build_datacenters(
            out,
            existing_path=FIXTURE / "existing_datacenters_sample.geojson",
            seed_path=seed,
            centroids_path=SEEDS_DIR / "known_city_centroids.json",
        )


def test_count_never_falls_below_existing(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    seed = tmp_path / "seed.yaml"
    seed.write_text("datacenters: []\n")
    out = tmp_path / "datacenters.geojson"
    count = build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    assert count == 3


def test_haversine_known_distance() -> None:
    # London to Paris ≈ 344 km
    d = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340 < d < 350
