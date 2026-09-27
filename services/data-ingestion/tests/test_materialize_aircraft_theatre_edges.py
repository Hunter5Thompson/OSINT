"""Historical aircraft SPOTTED_AT edges on theatre aggregates → observation Locations."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from graph_integrity.materialize_aircraft_theatre_edges import (
    APPLY_MATERIALIZATION,
    COUNT_EXISTING_OBSERVATION_KEYS,
    FETCH_THEATRE_EDGES,
    MATERIALIZATION_REVISION,
    REVERT_MATERIALIZATION,
    plan_edge,
    revert,
    run,
)
from graph_integrity.spatial_batch import report_fingerprint, validate_dry_run_approval
from graph_integrity.spatial_normalizer import load_normalization_index

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        REPOSITORY_ROOT / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799",
        crosswalk_path=(
            REPOSITORY_ROOT / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
        ),
    )


def _edge_row(
    dedup_key: str,
    *,
    theatre: str = "ukraine",
    lat: Any = 48.5,
    lon: Any = 35.2,
    **edge_overrides: Any,
) -> dict[str, Any]:
    icao24 = dedup_key.split("|", 1)[0]
    edge = {
        "dedup_key": dedup_key,
        "latitude": lat,
        "longitude": lon,
        "altitude_m": 10668.0,
        "speed_ms": 231.5,
        "heading": 90.0,
        "timestamp": 1775775056001,
        "source": "adsb.fi",
        **edge_overrides,
    }
    return {"icao24": icao24, "theatre": theatre, "dedup_key": dedup_key, "edge": edge}


class _FakeGraph:
    """Serves FETCH pages from a mutable edge list; APPLY moves edges off it."""

    def __init__(self, rows: list[dict[str, Any]], *, existing_keys: int = 0) -> None:
        self.rows = sorted(rows, key=lambda row: row["dedup_key"])
        self.existing_keys = existing_keys
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.moved: list[dict[str, Any]] = []
        self.apply_drops: int = 0

    async def run(self, cypher: str, params: dict[str, Any] | None = None):
        self.calls.append((cypher, params))
        assert params is not None
        if cypher == FETCH_THEATRE_EDGES:
            cursor = params["cursor"]
            page = [r for r in self.rows if cursor is None or r["dedup_key"] > cursor]
            return copy.deepcopy(page[: params["batch_size"]])
        if cypher == COUNT_EXISTING_OBSERVATION_KEYS:
            return [{"count": self.existing_keys}]
        if cypher == APPLY_MATERIALIZATION:
            keys = {row["dedup_key"] for row in params["rows"]}
            applied = params["rows"][: len(params["rows"]) - self.apply_drops]
            self.moved.extend(applied)
            applied_keys = {row["dedup_key"] for row in applied}
            self.rows = [r for r in self.rows if r["dedup_key"] not in applied_keys]
            assert applied_keys <= keys
            return [{"moved": len(applied)}]
        raise AssertionError(f"unexpected cypher: {cypher[:60]}")

    def writes(self) -> list[str]:
        return [c for c, _ in self.calls if c == APPLY_MATERIALIZATION]


# --------------------------------------------------------------------- planner


def test_plan_edge_builds_observation_location_like_the_live_producer(spatial_index) -> None:
    row = _edge_row("adf7c8|1775775056001")

    write, skip = plan_edge(row, spatial_index)

    assert skip is None
    assert write["loc_key"] == "aircraft-observation:adf7c8|1775775056001"
    assert write["name"] == "UKR"
    assert write["country_scope_key"] == "country:UKR"
    assert write["spatial_precision"] == "point"
    assert write["spatial_catalog_revision"] == spatial_index.catalog_revision
    assert write["latitude"] == 48.5 and write["longitude"] == 35.2
    assert write["theatre"] == "ukraine"
    assert write["icao24"] == "adf7c8"
    assert write["materialization_revision"] == MATERIALIZATION_REVISION
    # The complete original edge map travels unchanged: it is the drift guard
    # and the evidence copied onto the new relationship.
    assert write["edge"] == row["edge"]


def test_plan_edge_names_theatre_label_by_catalog_not_by_box(spatial_index) -> None:
    # The "ukraine" hotspot box reaches Rostov; the catalog decides the country.
    write, _ = plan_edge(_edge_row("aa0001|1", lat=47.2, lon=39.7), spatial_index)
    assert write["name"] == "RUS"


def test_plan_edge_keeps_honest_unresolved_label(spatial_index) -> None:
    # Baghdad: IRQ is not in the fixture catalog.
    row = _edge_row("aa0002|1", theatre="iran", lat=33.3, lon=44.4)
    write, skip = plan_edge(row, spatial_index)
    assert skip is None
    assert write["name"] == "unresolved"
    assert write["country_iso3"] is None


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (_edge_row("aa0003|1", lat=0.0, lon=0.0), "null_island"),
        (_edge_row("aa0004|1", lat=None), "missing_coordinate"),
        (_edge_row("aa0005|1", lat=91.0), "invalid_coordinate"),
        (_edge_row("aa0006|1", lon=float("nan")), "invalid_coordinate"),
        (_edge_row("aa0007|1", lat="48.5"), "invalid_coordinate"),
        (_edge_row("aa0008|1", lat=True), "invalid_coordinate"),
        (_edge_row("aa0009|1", timestamp=None), "invalid_timestamp"),
        (_edge_row("aa0010|1", timestamp=1.5), "invalid_timestamp"),
        ({**_edge_row("aa0011|1"), "icao24": ""}, "invalid_identity"),
        ({**_edge_row("aa0012|1"), "theatre": None}, "invalid_identity"),
        (
            {**_edge_row("aa0013|1"), "edge": {**_edge_row("aa0013|1")["edge"], "dedup_key": "x"}},
            "invalid_identity",
        ),
    ],
)
def test_plan_edge_skips_unmaterializable_evidence(spatial_index, row, reason) -> None:
    write, skip = plan_edge(row, spatial_index)
    assert write is None
    assert skip == reason


# ----------------------------------------------------------------------- runner


@pytest.mark.asyncio
async def test_dry_run_reports_without_writes(spatial_index) -> None:
    graph = _FakeGraph([
        _edge_row("aa0001|1"),
        _edge_row("aa0002|1", theatre="iran", lat=33.3, lon=44.4),
        _edge_row("aa0003|1", lat=0.0, lon=0.0),
    ])

    report = await run(graph, spatial_index, batch_size=2, dry_run=True)

    assert graph.writes() == []
    assert report["mode"] == "dry-run"
    assert report["complete"] is True
    assert report["total"] == 3
    assert report["writes_planned"] == 2
    assert report["writes_applied"] == 0
    assert report["by_theatre"] == {"iran": 1, "ukraine": 2}
    assert report["by_name"] == {"UKR": 1, "unresolved": 1}
    assert report["skipped"] == {"null_island": 1}
    assert report["materialization_revision"] == MATERIALIZATION_REVISION
    assert report["catalog_revision"] == spatial_index.catalog_revision
    assert report["report_fingerprint"] == report_fingerprint(report)


@pytest.mark.asyncio
async def test_dry_run_is_deterministic_and_detects_drift(spatial_index) -> None:
    rows = [_edge_row("aa0001|1"), _edge_row("aa0002|1")]
    approved = await run(_FakeGraph(rows), spatial_index, batch_size=10, dry_run=True)
    fresh = await run(_FakeGraph(rows), spatial_index, batch_size=10, dry_run=True)
    validate_dry_run_approval(approved, fresh)

    drifted_rows = [_edge_row("aa0001|1"), _edge_row("aa0002|1", heading=91.0)]
    drifted = await run(_FakeGraph(drifted_rows), spatial_index, batch_size=10, dry_run=True)
    with pytest.raises(ValueError, match="drifted"):
        validate_dry_run_approval(approved, drifted)


@pytest.mark.asyncio
async def test_existing_observation_key_makes_dry_run_incomplete(spatial_index) -> None:
    graph = _FakeGraph([_edge_row("aa0001|1")], existing_keys=1)
    report = await run(graph, spatial_index, batch_size=10, dry_run=True)
    assert report["existing_observation_keys"] == 1
    assert report["complete"] is False


@pytest.mark.asyncio
async def test_apply_moves_every_planned_edge_and_skips_the_rest(spatial_index) -> None:
    graph = _FakeGraph([
        _edge_row("aa0001|1"),
        _edge_row("aa0002|1"),
        _edge_row("aa0003|1", lat=0.0, lon=0.0),
        _edge_row("aa0004|1"),
    ])

    report = await run(graph, spatial_index, batch_size=2, dry_run=False)

    assert report["mode"] == "apply"
    assert report["writes_applied"] == 3
    assert sorted(r["dedup_key"] for r in graph.moved) == ["aa0001|1", "aa0002|1", "aa0004|1"]
    # Skipped evidence stays on its theatre aggregate.
    assert [r["dedup_key"] for r in graph.rows] == ["aa0003|1"]


@pytest.mark.asyncio
async def test_apply_is_idempotent(spatial_index) -> None:
    graph = _FakeGraph([_edge_row("aa0001|1"), _edge_row("aa0002|1")])
    await run(graph, spatial_index, batch_size=1, dry_run=False)
    again = await run(graph, spatial_index, batch_size=1, dry_run=False)
    assert again["total"] == 0 and again["writes_applied"] == 0


@pytest.mark.asyncio
async def test_apply_refuses_when_graph_moves_fewer_edges_than_planned(spatial_index) -> None:
    graph = _FakeGraph([_edge_row("aa0001|1"), _edge_row("aa0002|1")])
    graph.apply_drops = 1
    with pytest.raises(RuntimeError, match="moved 1 of 2"):
        await run(graph, spatial_index, batch_size=10, dry_run=False)


@pytest.mark.asyncio
async def test_apply_refuses_with_existing_observation_keys(spatial_index) -> None:
    graph = _FakeGraph([_edge_row("aa0001|1")], existing_keys=1)
    with pytest.raises(RuntimeError, match="existing observation"):
        await run(graph, spatial_index, batch_size=10, dry_run=False)
    assert graph.writes() == []


@pytest.mark.asyncio
async def test_runner_rejects_unordered_or_repeated_pages(spatial_index) -> None:
    class _Repeating(_FakeGraph):
        async def run(self, cypher, params=None):
            if cypher == FETCH_THEATRE_EDGES:
                return [_edge_row("aa0002|1"), _edge_row("aa0001|1")]
            return await super().run(cypher, params)

    with pytest.raises(RuntimeError, match="strictly ordered"):
        await run(_Repeating([]), spatial_index, batch_size=10, dry_run=True)


# ------------------------------------------------------------ cypher contracts


def test_fetch_selects_only_coordinate_free_theatre_aggregates() -> None:
    assert "t.loc_key IS NULL" in FETCH_THEATRE_EDGES
    assert "t.type = 'geopolitical_hotspot'" in FETCH_THEATRE_EDGES
    for prop in ("t.lat", "t.lon", "t.geo"):
        assert f"{prop} IS NULL" in FETCH_THEATRE_EDGES
    assert "ORDER BY r.dedup_key" in FETCH_THEATRE_EDGES
    assert "properties(r) AS edge" in FETCH_THEATRE_EDGES


def test_apply_moves_edge_atomically_with_drift_guard() -> None:
    q = APPLY_MATERIALIZATION
    assert "UNWIND $rows AS row" in q
    assert "properties(old) = row.edge" in q
    # CREATE (not MERGE) so a loc_key collision fails the batch under the
    # location_loc_key_unique constraint instead of merging foreign evidence.
    assert "CREATE (l:Location {loc_key: row.loc_key})" in q
    assert "CREATE (a)-[n:SPOTTED_AT]->(l)" in q
    assert "SET n = row.edge" in q
    assert "DELETE old" in q
    assert "l.type = 'aircraft_observation'" in q
    assert "point({longitude: row.longitude, latitude: row.latitude})" in q
    # No theatre node is ever removed.
    assert "DELETE t" not in q and "DETACH" not in q


def test_revert_restores_theatre_edges_and_fails_closed() -> None:
    q = REVERT_MATERIALIZATION
    assert "n.materialization_revision = $materialization_revision" in q
    assert "l.materialization_revision = $materialization_revision" in q
    assert "CREATE (a)-[old:SPOTTED_AT]->(t)" in q
    assert "DELETE n" in q
    # Plain DELETE: a node that gained foreign relationships aborts the revert.
    assert "DETACH" not in q


@pytest.mark.asyncio
async def test_revert_dry_run_counts_and_apply_loops_until_empty() -> None:
    class _RevertGraph:
        def __init__(self) -> None:
            self.remaining = 5
            self.calls: list[dict[str, Any]] = []

        async def run(self, cypher, params=None):
            self.calls.append(params)
            if cypher == REVERT_MATERIALIZATION:
                assert params["materialization_revision"] == MATERIALIZATION_REVISION
                n = min(self.remaining, params["batch_size"])
                self.remaining -= n
                return [{"reverted": n}]
            return [{"count": self.remaining}]

    graph = _RevertGraph()
    assert await revert(graph, batch_size=2, dry_run=True) == 5
    assert graph.remaining == 5
    assert await revert(graph, batch_size=2, dry_run=False) == 5
    assert graph.remaining == 0


def test_revert_requires_exactly_one_theatre_target() -> None:
    assert "size(theatres) = 1" in REVERT_MATERIALIZATION


@pytest.mark.asyncio
async def test_revert_refuses_to_finish_with_unrevertable_edges() -> None:
    class _StuckGraph:
        async def run(self, cypher, params=None):
            if cypher == REVERT_MATERIALIZATION:
                return [{"reverted": 0}]
            return [{"count": 3}]

    with pytest.raises(RuntimeError, match="3 materialized edges could not be reverted"):
        await revert(_StuckGraph(), batch_size=2, dry_run=False)
