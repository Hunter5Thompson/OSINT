from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from graph_integrity.spatial_batch import (
    APPLY_SPATIAL_BATCH,
    COUNT_UNSTABLE_LOCATION_RECORDS,
    FETCH_LOCATION_BATCHES,
    BatchJob,
    JsonCheckpointStore,
    MemoryCheckpointStore,
    report_fingerprint,
    run_spatial_batch,
    validate_dry_run_approval,
)
from graph_integrity.spatial_normalizer import (
    CountryCodeSystem,
    RawLocationIdentity,
    build_normalization_index,
    load_normalization_index,
    normalize_location,
)
from spatial_catalog.identity import load_country_crosswalk

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        REPOSITORY_ROOT / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799",
        crosswalk_path=(
            REPOSITORY_ROOT / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
        ),
    )


@pytest.fixture(scope="module")
def compatible_index():
    current = "spatial-derive-v1-111111111111"
    compatible = "spatial-derive-v1-000000000000"
    return build_normalization_index(
        catalog_revision="spatial-v1-111111111111",
        country_crosswalk=load_country_crosswalk(
            REPOSITORY_ROOT / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
        ),
        scope_parents={"country:UKR": None},
        scope_derivation_revisions={"country:UKR": current},
        scope_compatible_derivation_revisions={
            "country:UKR": (current, compatible),
        },
        containment={},
    )


def _target_revision(spatial_index) -> str:
    result = normalize_location(
        RawLocationIdentity(
            country_code="UP",
            country_code_system=CountryCodeSystem.GDELT_GEC,
            latitude=48.0,
            longitude=37.8,
        ),
        spatial_index,
    )
    assert result.spatial_derivation_revision is not None
    return result.spatial_derivation_revision


def _row(record_id: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "record_id": record_id,
        "name": "Donetsk, Ukraine",
        "country": "UP",
        "lat": 48.0,
        "lon": 37.8,
        "geo_basis": "gdelt_actiongeo",
        "source_country_code": None,
        "source_country_code_system": None,
        "country_iso3": None,
        "admin1_code": None,
        "admin2_code": None,
        "country_scope_key": None,
        "admin1_scope_key": None,
        "admin2_scope_key": None,
        "spatial_basis": None,
        "spatial_precision": None,
        "spatial_catalog_revision": None,
        "spatial_derivation_revision": None,
        "spatial_conflict": None,
        "spatial_conflict_scope_keys": None,
        "has_geo": False,
    }
    row.update(overrides)
    return row


class FakeClient:
    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        fail_apply_call: int | None = None,
        unstable_count: int = 0,
    ):
        self.rows = {row["record_id"]: dict(row) for row in rows}
        self.fetch_calls: list[dict[str, Any]] = []
        self.apply_calls: list[list[dict[str, Any]]] = []
        self.fail_apply_call = fail_apply_call
        self.unstable_count = unstable_count

    async def run(self, query: str, params: dict[str, Any] | None = None):
        values = params or {}
        if query in COUNT_UNSTABLE_LOCATION_RECORDS.values():
            return [{"count": self.unstable_count}]
        if query in FETCH_LOCATION_BATCHES.values():
            self.fetch_calls.append(dict(values))
            cursor = values["cursor"]
            rows = [
                dict(row)
                for key, row in sorted(self.rows.items())
                if cursor is None or key > cursor
            ]
            return rows[: values["batch_size"]]
        if query == APPLY_SPATIAL_BATCH:
            batch = [dict(row) for row in values["rows"]]
            self.apply_calls.append(batch)
            if self.fail_apply_call == len(self.apply_calls):
                raise RuntimeError("interrupted apply")
            for update in batch:
                stored = self.rows[update["record_id"]]
                if update["action"] == "resolved":
                    for key, value in update.items():
                        if key not in {"record_id", "action", "latitude", "longitude"}:
                            stored[key] = value
                    stored["has_geo"] = update["latitude"] is not None
                else:
                    stored["spatial_catalog_revision"] = update["spatial_catalog_revision"]
                    stored["spatial_conflict"] = True
                    stored["spatial_conflict_scope_keys"] = update["spatial_conflict_scope_keys"]
            return [{"updated": len(batch)}]
        raise AssertionError(f"unexpected query: {query}")


@pytest.mark.asyncio
async def test_dry_run_reports_without_graph_or_checkpoint_writes(spatial_index) -> None:
    target = _target_revision(spatial_index)
    client = FakeClient(
        [
            _row("gdelt:loc:1"),
            _row("gdelt:loc:2", country="ZZ", lat=None, lon=None),
            _row("gdelt:loc:3", lat=91.0),
        ]
    )
    checkpoints = MemoryCheckpointStore()
    job = BatchJob("backfill", "gdelt_raw", target, batch_size=2)

    report = await run_spatial_batch(
        client,
        spatial_index,
        checkpoints,
        job,
        dry_run=True,
    )

    assert report["mode"] == "dry-run"
    assert report["total"] == 3
    assert report["resolvable"] == 1
    assert report["unresolved"] == 1
    assert report["invalid_coordinate"] == 1
    assert report["writes_planned"] == 1
    assert report["writes_applied"] == 0
    assert report["by_source"] == {"gdelt_actiongeo": 3}
    assert report["by_code_system"] == {"gdelt-gec": 3}
    assert client.apply_calls == []
    assert checkpoints.values == {}
    assert [call["batch_size"] for call in client.fetch_calls] == [2, 2]


@pytest.mark.asyncio
async def test_apply_is_idempotent_with_a_fresh_checkpoint(spatial_index) -> None:
    target = _target_revision(spatial_index)
    client = FakeClient([_row("gdelt:loc:1")])
    job = BatchJob("backfill", "gdelt_raw", target, batch_size=10)

    first = await run_spatial_batch(
        client,
        spatial_index,
        MemoryCheckpointStore(),
        job,
        dry_run=False,
    )
    second = await run_spatial_batch(
        client,
        spatial_index,
        MemoryCheckpointStore(),
        job,
        dry_run=False,
    )

    assert first["writes_applied"] == 1
    assert second["already_normalized"] == 1
    assert second["writes_planned"] == 0
    assert len(client.apply_calls) == 1


@pytest.mark.asyncio
async def test_interrupted_apply_resumes_after_last_completed_stable_cursor(
    spatial_index,
) -> None:
    target = _target_revision(spatial_index)
    rows = [_row(f"gdelt:loc:{number}") for number in range(1, 4)]
    client = FakeClient(rows, fail_apply_call=2)
    checkpoints = MemoryCheckpointStore()
    job = BatchJob("backfill", "gdelt_raw", target, batch_size=2)

    with pytest.raises(RuntimeError, match="interrupted apply"):
        await run_spatial_batch(
            client,
            spatial_index,
            checkpoints,
            job,
            dry_run=False,
        )

    assert checkpoints.load(job) == "gdelt:loc:2"

    client.fail_apply_call = None
    resumed = await run_spatial_batch(
        client,
        spatial_index,
        checkpoints,
        job,
        dry_run=False,
    )

    assert resumed["start_cursor"] == "gdelt:loc:2"
    assert resumed["end_cursor"] == "gdelt:loc:3"
    assert resumed["writes_applied"] == 1


@pytest.mark.asyncio
async def test_conflict_is_marked_and_unresolved_record_is_not_mutated(spatial_index) -> None:
    target = _target_revision(spatial_index)
    unresolved = _row("gdelt:loc:2", country="ZZ", lat=None, lon=None)
    conflict = _row(
        "gdelt:loc:1",
        lat=37.0,
        lon=-95.0,
        country_scope_key="country:LEGACY",
    )
    client = FakeClient(
        [
            conflict,
            unresolved,
        ]
    )

    report = await run_spatial_batch(
        client,
        spatial_index,
        MemoryCheckpointStore(),
        BatchJob("backfill", "gdelt_raw", target, batch_size=10),
        dry_run=False,
    )

    assert report["conflict"] == 1
    assert report["unresolved"] == 1
    assert report["writes_applied"] == 1
    assert client.apply_calls[0][0]["action"] == "conflict"
    assert client.apply_calls[0][0]["spatial_conflict_scope_keys"] == [
        "country:UKR",
        "country:USA",
    ]
    assert client.rows["gdelt:loc:1"]["country_scope_key"] == "country:LEGACY"
    assert client.rows["gdelt:loc:2"] == unresolved


@pytest.mark.asyncio
async def test_resolved_and_conflict_actions_share_one_atomic_apply_batch(
    spatial_index,
) -> None:
    target = _target_revision(spatial_index)
    client = FakeClient(
        [
            _row("gdelt:loc:1"),
            _row("gdelt:loc:2", lat=37.0, lon=-95.0),
        ]
    )

    report = await run_spatial_batch(
        client,
        spatial_index,
        MemoryCheckpointStore(),
        BatchJob("backfill", "gdelt_raw", target, batch_size=10),
        dry_run=False,
    )

    assert report["writes_applied"] == 2
    assert len(client.apply_calls) == 1
    assert {row["action"] for row in client.apply_calls[0]} == {
        "resolved",
        "conflict",
    }


@pytest.mark.asyncio
async def test_legacy_rss_centroid_normalizes_as_country_without_invented_point(
    spatial_index,
) -> None:
    normalized = normalize_location(
        RawLocationIdentity(
            country_code="UA",
            country_code_system=CountryCodeSystem.ISO2,
        ),
        spatial_index,
    )
    assert normalized.spatial_derivation_revision is not None
    client = FakeClient(
        [
            _row(
                "centroid:ua",
                country=None,
                name=None,
                lat=48.3794,
                lon=31.1656,
                geo_basis="country_centroid",
            )
        ]
    )

    report = await run_spatial_batch(
        client,
        spatial_index,
        MemoryCheckpointStore(),
        BatchJob(
            "backfill",
            "rss_pipeline",
            normalized.spatial_derivation_revision,
        ),
        dry_run=False,
    )

    assert report["writes_applied"] == 1
    update = client.apply_calls[0][0]
    assert update["latitude"] is None
    assert update["longitude"] is None
    assert update["spatial_precision"] == "country"
    assert client.rows["centroid:ua"]["has_geo"] is False


@pytest.mark.asyncio
async def test_job_does_not_rewrite_record_for_a_different_target_revision(
    spatial_index,
) -> None:
    client = FakeClient([_row("gdelt:loc:1")])

    report = await run_spatial_batch(
        client,
        spatial_index,
        MemoryCheckpointStore(),
        BatchJob("backfill", "gdelt_raw", "different-derivation"),
        dry_run=False,
    )

    assert report["target_revision_mismatch"] == 1
    assert report["writes_applied"] == 0
    assert client.apply_calls == []


@pytest.mark.asyncio
async def test_report_counts_only_reviewed_compatible_stale_revisions(
    compatible_index,
) -> None:
    current = "spatial-derive-v1-111111111111"
    client = FakeClient(
        [
            _row(
                "gdelt:loc:1",
                lat=None,
                lon=None,
                spatial_derivation_revision="spatial-derive-v1-000000000000",
            ),
            _row(
                "gdelt:loc:2",
                lat=None,
                lon=None,
                spatial_derivation_revision="spatial-derive-v1-ffffffffffff",
            ),
        ]
    )

    report = await run_spatial_batch(
        client,
        compatible_index,
        MemoryCheckpointStore(),
        BatchJob("backfill", "gdelt_raw", current),
        dry_run=True,
    )

    assert report["stale_compatible_revision_count"] == 1
    assert report["stale_compatible_revision_rate"] == 0.5


def test_checkpoint_is_scoped_by_job_kind_lane_and_target_revision(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.json"
    store = JsonCheckpointStore(path)
    jobs = (
        BatchJob("backfill", "gdelt_raw", "derive-a"),
        BatchJob("backfill", "gdelt_raw", "derive-b"),
        BatchJob("reenrichment", "gdelt_raw", "derive-a"),
        BatchJob("backfill", "rss_pipeline", "derive-a"),
    )

    for index, job in enumerate(jobs):
        store.save(job, f"cursor-{index}")

    reloaded = JsonCheckpointStore(path)
    assert [reloaded.load(job) for job in jobs] == [
        "cursor-0",
        "cursor-1",
        "cursor-2",
        "cursor-3",
    ]
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == 1
    assert len(payload["checkpoints"]) == 4


def test_cypher_is_static_parameterized_and_preserves_raw_properties() -> None:
    assert set(FETCH_LOCATION_BATCHES) == {
        "gdelt_raw",
        "rss_pipeline",
        "military_aircraft",
        "backend_incident",
    }
    assert set(COUNT_UNSTABLE_LOCATION_RECORDS) == set(FETCH_LOCATION_BATCHES)
    for query in FETCH_LOCATION_BATCHES.values():
        assert "$cursor" in query
        assert "$batch_size" in query
        assert "ORDER BY l.loc_key" in query
    assert "$rows" in APPLY_SPATIAL_BATCH
    assert "point({longitude: row.longitude, latitude: row.latitude})" in (APPLY_SPATIAL_BATCH)
    for raw_property in ("name", "country", "lat", "lon", "geo_basis", "loc_key"):
        assert f"l.{raw_property} =" not in APPLY_SPATIAL_BATCH


@pytest.mark.asyncio
async def test_report_exposes_lane_records_without_a_stable_cursor(spatial_index) -> None:
    target = _target_revision(spatial_index)
    client = FakeClient([], unstable_count=4)

    report = await run_spatial_batch(
        client,
        spatial_index,
        MemoryCheckpointStore(),
        BatchJob("backfill", "military_aircraft", target),
        dry_run=True,
    )

    assert report["unstable_record_id_count"] == 4
    assert report["complete"] is False


def test_dry_run_approval_is_content_addressed_and_rejects_drift() -> None:
    report = {
        "schema_version": 1,
        "mode": "dry-run",
        "job": {"lane": "gdelt_raw", "target_derivation_revision": "derive-a"},
        "complete": True,
        "total": 2,
        "writes_planned": 1,
        "writes_applied": 0,
    }
    approved = {**report, "report_fingerprint": report_fingerprint(report)}

    validate_dry_run_approval(approved, report)
    with pytest.raises(ValueError, match="drift"):
        validate_dry_run_approval(approved, {**report, "total": 3})

    incomplete = {**report, "complete": False}
    incomplete["report_fingerprint"] = report_fingerprint(incomplete)
    with pytest.raises(ValueError, match="incomplete"):
        validate_dry_run_approval(incomplete, incomplete)
