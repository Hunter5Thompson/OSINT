"""Tests for the refinery enrichment builder."""

import json
from pathlib import Path

from pytest_httpx import HTTPXMock

from infra_atlas.build_refineries import build_refineries

FIXTURE = Path(__file__).parent / "fixtures"


def test_existing_image_is_preserved(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())

    jam = next(f for f in data["features"] if f["properties"]["name"] == "Jamnagar Refinery")
    # Existing image must NOT be overwritten by Wikidata's image
    assert jam["properties"]["image_url"].endswith("Existing_Jamnagar.jpg")
    # Wikidata enrichment still adds qid + source_url
    assert jam["properties"]["qid"] == "Q3417395"
    assert jam["properties"]["source_url"] == "https://www.wikidata.org/wiki/Q3417395"
    # Existing spec is preserved AND Wikidata description is appended
    specs = jam["properties"]["specs"]
    assert "Existing curated note about Jamnagar." in specs
    assert any("Largest" in s for s in specs)


def test_existing_capacity_and_operator_not_overwritten(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())

    jam = next(f for f in data["features"] if f["properties"]["name"] == "Jamnagar Refinery")
    assert jam["properties"]["operator"] == "Reliance Industries"
    assert jam["properties"]["capacity_bpd"] == 1240000


def test_existing_without_image_gets_wikidata_image(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())

    rt = next(f for f in data["features"] if f["properties"]["name"] == "Ras Tanura Refinery")
    assert rt["properties"]["image_url"].endswith("Ras_Tanura.jpg")
    assert rt["properties"]["qid"] == "Q860840"


def test_wikidata_only_entry_appended_with_zero_capacity(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    count = build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())
    # 3 existing + 1 wikidata-only = 4 (Jamnagar + Ras Tanura matched in-place)
    assert count == 4
    new_entry = next(f for f in data["features"] if f["properties"]["name"] == "New Wikidata Refinery")
    assert new_entry["properties"]["capacity_bpd"] == 0
    assert new_entry["properties"]["coord_quality"] == "wikidata_verified"
    assert new_entry["properties"]["coord_source"] == "wikidata"


def test_existing_unmatched_entry_marked_legacy(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())
    bay = next(f for f in data["features"] if f["properties"]["name"] == "Baytown Refinery")
    # Baytown isn't in the wikidata fixture
    assert bay["properties"].get("qid") is None
    assert bay["properties"].get("coord_quality") == "legacy"


def test_count_never_falls_below_existing(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    """If Wikidata is empty, output must equal existing count exactly."""
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    out = tmp_path / "refineries.geojson"
    count = build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    assert count == 3  # exactly the existing 3
