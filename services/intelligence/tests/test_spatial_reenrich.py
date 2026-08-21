from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PAYLOAD_CONTRACT_PATH = (
    REPOSITORY_ROOT / "contracts/qdrant-spatial-payload-v1.json"
)
CATALOG_MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799/manifest.json"
)
BATCH_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/spatial-batch-file-formats-v1.json"


def _projection(
    target_revision: str,
    *,
    status: str = "filterable",
    conflict: bool | None = None,
) -> dict[str, object]:
    has_conflict = status == "conflict" if conflict is None else conflict
    filterable = status == "filterable"
    return {
        "spatial_about_scope_revision_tokens": [],
        "spatial_occurrence_scope_revision_tokens": (
            ["sr1|country:UKR|spatial-derive-v1-d30efa07e141"]
            if filterable
            else []
        ),
        "spatial_basis": ["source"],
        "spatial_precision": "country",
        "spatial_catalog_revision": "spatial-v1-e76a16bff799",
        "spatial_projection_revision": target_revision,
        "spatial_derivation_version": "spatial-deriver-v2",
        "spatial_conflict": has_conflict,
        "spatial_conflict_scope_keys": (
            ["country:UKR", "country:USA"] if has_conflict else []
        ),
        "spatial_derivation_status": status,
        "spatial_derivations": [],
        "source_country_code": ["UKR"],
        "source_country_code_system": ["iso3"],
        "country_iso3": ["UKR"],
        "admin1_code": [],
        "admin2_code": [],
    }


class FakeProjector:
    def __init__(self, statuses: dict[str, str] | None = None) -> None:
        self.statuses = statuses or {}

    def project(self, point, job):
        return _projection(
            job.target_projection_revision,
            status=self.statuses.get(str(point.point_id), "filterable"),
        )


class FakeStore:
    def __init__(self, payloads: list[dict[str, object]], *, fail_replace_call: int | None = None):
        from rag.spatial_reenrich import ReenrichmentPoint

        self.points = [
            ReenrichmentPoint(
                point_id=f"point-{index + 1}",
                vector=[float(index + 1), 0.0],
                payload=deepcopy(payload),
            )
            for index, payload in enumerate(payloads)
        ]
        self.replace_calls: list[tuple] = []
        self.fetch_cursors: list[str | int | None] = []
        self.fail_replace_call = fail_replace_call

    async def fetch_page(self, lane, cursor, limit):
        from rag.spatial_reenrich import ReenrichmentPage

        self.fetch_cursors.append(cursor)
        start = int(cursor) if cursor is not None else 0
        end = min(start + limit, len(self.points))
        next_cursor = str(end) if end < len(self.points) else None
        return ReenrichmentPage(
            points=tuple(self.points[start:end]),
            next_cursor=next_cursor,
        )

    async def replace_points(self, lane, replacements):
        self.replace_calls.append(tuple(replacements))
        if self.fail_replace_call == len(self.replace_calls):
            raise RuntimeError("interrupted replace")
        by_id = {point.point_id: index for index, point in enumerate(self.points)}
        for replacement in replacements:
            index = by_id[replacement.point_id]
            self.points[index] = replacement
        return len(replacements)


def _old_payload(*, projection_revision: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "rss",
        "content": "preserve me",
        "spatial_about_scope_revision_tokens": ["old-about"],
        "spatial_occurrence_scope_revision_tokens": ["old-occurrence"],
        "spatial_derivation_revision": "obsolete-scalar",
        "spatial_legacy_field": "must disappear",
        "spatial_conflict": False,
        "geo": {"lon": 1.0, "lat": 2.0},
        "source_country_code": ["OLD"],
        "source_country_code_system": ["legacy"],
        "country_iso3": ["OLD"],
        "admin1_code": ["OLD-1"],
        "admin2_code": ["OLD-2"],
    }
    if projection_revision is not None:
        payload["spatial_projection_revision"] = projection_revision
    return payload


@pytest.mark.asyncio
async def test_dry_run_plans_replacements_but_performs_zero_writes() -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore([_old_payload(), _old_payload()])
    report = await preview_spatial_reenrichment(
        store,
        FakeProjector(),
        ReenrichmentJob(lane="analysis", target_projection_revision=target, batch_size=1),
    )

    assert report["mode"] == "dry-run"
    assert report["writes_planned"] == 2
    assert report["writes_applied"] == 0
    assert store.replace_calls == []
    assert report["report_fingerprint"]


@pytest.mark.asyncio
async def test_publish_coverage_snapshot_combines_verified_index_lanes(tmp_path) -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
        publish_spatial_coverage_snapshot,
    )
    from spatial import SpatialCoverageSnapshotV1

    target = "spatial-projection-v1-47fec701a2a2"
    reports = []
    for lane in ("analysis", "documents"):
        store = FakeStore([_projection(target), _projection(target)])
        reports.append(
            await preview_spatial_reenrichment(
                store,
                FakeProjector(),
                ReenrichmentJob(
                    lane=lane,
                    target_projection_revision=target,
                ),
            )
        )
    path = tmp_path / "qdrant-coverage.json"

    snapshot = publish_spatial_coverage_snapshot(path, reports)

    assert snapshot == SpatialCoverageSnapshotV1.model_validate_json(path.read_bytes())
    from rag.spatial_coverage import load_spatial_coverage_snapshot

    assert load_spatial_coverage_snapshot(path) == snapshot
    assert snapshot.target_projection_revision == target
    assert [lane.lane for lane in snapshot.lanes] == ["analysis", "documents"]
    assert all(lane.filterable_points == 2 for lane in snapshot.lanes)


@pytest.mark.asyncio
async def test_publish_coverage_snapshot_rejects_projected_dry_run_counts(
    tmp_path,
) -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
        publish_spatial_coverage_snapshot,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    report = await preview_spatial_reenrichment(
        FakeStore([_old_payload()]),
        FakeProjector(),
        ReenrichmentJob(lane="analysis", target_projection_revision=target),
    )

    with pytest.raises(ValueError, match="current index coverage"):
        publish_spatial_coverage_snapshot(
            tmp_path / "qdrant-coverage.json",
            [report],
        )


@pytest.mark.asyncio
async def test_public_apply_interface_requires_an_approved_dry_run() -> None:
    from rag.spatial_reenrich import (
        MemoryCheckpointStore,
        ReenrichmentJob,
        apply_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    with pytest.raises(TypeError, match="approved_report"):
        await apply_spatial_reenrichment(
            FakeStore([_old_payload()]),
            FakeProjector(),
            MemoryCheckpointStore(),
            ReenrichmentJob(
                lane="analysis",
                target_projection_revision=target,
            ),
        )


def test_unguarded_mode_switch_is_not_a_public_interface() -> None:
    import rag.spatial_reenrich as reenrichment

    assert not hasattr(reenrichment, "ReenrichmentMode")
    assert not hasattr(reenrichment, "run_spatial_reenrichment")


@pytest.mark.asyncio
async def test_apply_rejects_approval_drift_before_any_write() -> None:
    from rag.spatial_reenrich import (
        MemoryCheckpointStore,
        ReenrichmentJob,
        apply_spatial_reenrichment,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore([_old_payload()])
    projector = FakeProjector()
    job = ReenrichmentJob(lane="analysis", target_projection_revision=target)
    approved = await preview_spatial_reenrichment(store, projector, job)
    store.points[0].payload.clear()
    store.points[0].payload.update(_projection(target))

    with pytest.raises(ValueError, match="drifted"):
        await apply_spatial_reenrichment(
            store,
            projector,
            MemoryCheckpointStore(),
            job,
            approved_report=approved,
        )

    assert store.replace_calls == []


@pytest.mark.asyncio
async def test_dry_run_always_scans_full_lane_and_ignores_apply_checkpoint() -> None:
    from rag.spatial_reenrich import (
        Checkpoint,
        MemoryCheckpointStore,
        ReenrichmentJob,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    job = ReenrichmentJob(lane="analysis", target_projection_revision=target)
    checkpoints = MemoryCheckpointStore()
    checkpoint = Checkpoint(
        cursor=None,
        complete=True,
        approved_report_fingerprint="a" * 64,
    )
    checkpoints.save(job, checkpoint)
    store = FakeStore([_old_payload()])

    report = await preview_spatial_reenrichment(
        store,
        FakeProjector(),
        job,
    )

    assert report["start_cursor"] is None
    assert report["total_points"] == 1
    assert store.fetch_cursors == [None]
    assert checkpoints.load(job) == checkpoint


@pytest.mark.asyncio
async def test_apply_replaces_every_spatial_field_in_one_full_point_update() -> None:
    from rag.spatial_reenrich import (
        MemoryCheckpointStore,
        ReenrichmentJob,
        apply_spatial_reenrichment,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore([_old_payload()])
    projector = FakeProjector()
    job = ReenrichmentJob(lane="analysis", target_projection_revision=target)
    approved = await preview_spatial_reenrichment(store, projector, job)
    report = await apply_spatial_reenrichment(
        store,
        projector,
        MemoryCheckpointStore(),
        job,
        approved_report=approved,
    )

    assert report["writes_applied"] == 1
    assert len(store.replace_calls) == 1
    replacement = store.replace_calls[0][0]
    assert replacement.vector == [1.0, 0.0]
    assert replacement.payload["source"] == "rss"
    assert replacement.payload["content"] == "preserve me"
    assert replacement.payload["spatial_projection_revision"] == target
    assert replacement.payload["source_country_code"] == ["UKR"]
    assert replacement.payload["source_country_code_system"] == ["iso3"]
    assert replacement.payload["country_iso3"] == ["UKR"]
    assert replacement.payload["admin1_code"] == []
    assert replacement.payload["admin2_code"] == []
    assert "spatial_derivation_revision" not in replacement.payload
    assert "spatial_legacy_field" not in replacement.payload
    assert replacement.payload["geo"] == {"lon": 1.0, "lat": 2.0}


@pytest.mark.asyncio
async def test_apply_honors_explicit_geo_clear() -> None:
    from rag.spatial_reenrich import (
        MemoryCheckpointStore,
        ReenrichmentJob,
        apply_spatial_reenrichment,
        preview_spatial_reenrichment,
    )

    class ClearingProjector(FakeProjector):
        def project(self, point, job):
            projection = _projection(job.target_projection_revision)
            projection["geo"] = None
            return projection

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore([_old_payload()])
    projector = ClearingProjector()
    job = ReenrichmentJob(lane="analysis", target_projection_revision=target)
    approved = await preview_spatial_reenrichment(store, projector, job)

    await apply_spatial_reenrichment(
        store,
        projector,
        MemoryCheckpointStore(),
        job,
        approved_report=approved,
    )

    assert store.points[0].payload["geo"] is None


@pytest.mark.asyncio
async def test_apply_is_idempotent_with_a_fresh_checkpoint() -> None:
    from rag.spatial_reenrich import (
        MemoryCheckpointStore,
        ReenrichmentJob,
        apply_spatial_reenrichment,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore([_old_payload()])
    job = ReenrichmentJob(lane="analysis", target_projection_revision=target)
    projector = FakeProjector()
    first_approval = await preview_spatial_reenrichment(store, projector, job)
    first = await apply_spatial_reenrichment(
        store,
        projector,
        MemoryCheckpointStore(),
        job,
        approved_report=first_approval,
    )
    second_approval = await preview_spatial_reenrichment(store, projector, job)
    second = await apply_spatial_reenrichment(
        store,
        projector,
        MemoryCheckpointStore(),
        job,
        approved_report=second_approval,
    )

    assert first["writes_applied"] == 1
    assert second["already_current"] == 1
    assert second["writes_planned"] == 0
    assert len(store.replace_calls) == 1


@pytest.mark.asyncio
async def test_interrupted_batch_resumes_from_last_completed_cursor() -> None:
    from rag.spatial_reenrich import (
        MemoryCheckpointStore,
        ReenrichmentJob,
        apply_spatial_reenrichment,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore(
        [_old_payload(), _old_payload(), _old_payload()],
        fail_replace_call=2,
    )
    checkpoints = MemoryCheckpointStore()
    job = ReenrichmentJob(
        lane="analysis",
        target_projection_revision=target,
        batch_size=2,
    )
    projector = FakeProjector()
    approved = await preview_spatial_reenrichment(store, projector, job)

    with pytest.raises(RuntimeError, match="interrupted replace"):
        await apply_spatial_reenrichment(
            store,
            projector,
            checkpoints,
            job,
            approved_report=approved,
        )

    assert checkpoints.load(job).cursor == "2"
    assert checkpoints.load(job).complete is False
    assert checkpoints.load(job).approved_report_fingerprint == (
        approved["report_fingerprint"]
    )

    store.fail_replace_call = None
    resumed = await apply_spatial_reenrichment(
        store,
        projector,
        checkpoints,
        job,
        approved_report=approved,
    )

    assert resumed["start_cursor"] == "2"
    assert resumed["writes_applied"] == 1
    assert store.fetch_cursors[-1] == "2"
    assert checkpoints.load(job).complete is True


@pytest.mark.asyncio
async def test_resume_rejects_a_different_approval_before_read_or_write() -> None:
    from rag.spatial_reenrich import (
        MemoryCheckpointStore,
        ReenrichmentJob,
        apply_spatial_reenrichment,
        preview_spatial_reenrichment,
        report_fingerprint,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore(
        [_old_payload(), _old_payload(), _old_payload()],
        fail_replace_call=2,
    )
    checkpoints = MemoryCheckpointStore()
    job = ReenrichmentJob(
        lane="analysis",
        target_projection_revision=target,
        batch_size=2,
    )
    projector = FakeProjector()
    approved = await preview_spatial_reenrichment(store, projector, job)
    with pytest.raises(RuntimeError, match="interrupted replace"):
        await apply_spatial_reenrichment(
            store,
            projector,
            checkpoints,
            job,
            approved_report=approved,
        )

    different = deepcopy(approved)
    different["writes_planned"] = int(different["writes_planned"]) + 1
    different["report_fingerprint"] = report_fingerprint(different)
    fetch_count = len(store.fetch_cursors)
    write_count = len(store.replace_calls)

    with pytest.raises(ValueError, match="durable checkpoint"):
        await apply_spatial_reenrichment(
            store,
            projector,
            checkpoints,
            job,
            approved_report=different,
        )

    assert len(store.fetch_cursors) == fetch_count
    assert len(store.replace_calls) == write_count


def test_checkpoint_key_is_lane_plus_target_projection_revision() -> None:
    from rag.spatial_reenrich import (
        Checkpoint,
        MemoryCheckpointStore,
        ReenrichmentJob,
    )

    store = MemoryCheckpointStore()
    first = ReenrichmentJob(
        lane="analysis",
        target_projection_revision="spatial-projection-v1-111111111111",
    )
    second = ReenrichmentJob(
        lane="realtime",
        target_projection_revision="spatial-projection-v1-111111111111",
    )
    third = ReenrichmentJob(
        lane="analysis",
        target_projection_revision="spatial-projection-v1-222222222222",
    )
    for index, job in enumerate((first, second, third)):
        store.save(
            job,
            Checkpoint(
                cursor=str(index),
                complete=False,
                approved_report_fingerprint="a" * 64,
            ),
        )

    assert first.checkpoint_key == (
        "analysis|spatial-projection-v1-111111111111"
    )
    assert [store.load(job).cursor for job in (first, second, third)] == ["0", "1", "2"]


@pytest.mark.asyncio
async def test_report_separates_current_stale_conflict_and_unsupported_coverage() -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    current_filterable = _projection(target)
    current_conflict = _projection(target, status="conflict")
    current_unsupported = _projection(target, status="unavailable")
    current_unsupported.pop("spatial_projection_revision")
    stale = _projection("spatial-projection-v1-111111111111")
    store = FakeStore(
        [current_filterable, current_conflict, current_unsupported, stale]
    )
    projector = FakeProjector(
        {
            "point-2": "conflict",
            "point-3": "unavailable",
        }
    )

    report = await preview_spatial_reenrichment(
        store,
        projector,
        ReenrichmentJob(lane="analysis", target_projection_revision=target),
    )

    before = report["coverage_before"]["lanes"][0]
    projected = report["coverage_projected"]["lanes"][0]
    assert before == {
        "lane": "analysis",
        "total_points": 4,
        "filterable_points": 1,
        "conflict_points": 1,
        "stale_points": 1,
        "unsupported_points": 1,
        "unprojected_points": 0,
        "audit_only_points": 0,
        "inconsistent_points": 0,
    }
    assert projected == {
        "lane": "analysis",
        "total_points": 4,
        "filterable_points": 2,
        "conflict_points": 1,
        "stale_points": 0,
        "unsupported_points": 1,
        "unprojected_points": 0,
        "audit_only_points": 0,
        "inconsistent_points": 0,
    }
    assert report["stale_points"] == 1
    assert report["stale_rate"] == 0.25
    assert report["unprojected_rate"] == 0.0
    assert report["filterable_rate"] == 0.25
    assert report["projected_filterable_rate"] == 0.5
    assert report["stale_gate_passed"] is False


@pytest.mark.asyncio
async def test_unprojected_points_fail_promotion_stale_gate_instead_of_hiding_in_total() -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    audit_only = _projection(target, status="audit_only")
    report = await preview_spatial_reenrichment(
        FakeStore([_old_payload(), audit_only]),
        FakeProjector({"point-2": "audit_only"}),
        ReenrichmentJob(lane="analysis", target_projection_revision=target),
    )

    before = report["coverage_before"]["lanes"][0]
    assert before["unprojected_points"] == 1
    assert before["audit_only_points"] == 1
    assert sum(
        before[field]
        for field in (
            "filterable_points",
            "conflict_points",
            "stale_points",
            "unsupported_points",
            "unprojected_points",
            "audit_only_points",
            "inconsistent_points",
        )
    ) == before["total_points"]
    assert report["stale_rate"] == 0.5
    assert report["stale_gate_passed"] is False


@pytest.mark.asyncio
async def test_current_but_internally_inconsistent_payload_blocks_promotion() -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    inconsistent = _projection(target, status="audit_only")
    inconsistent["spatial_derivation_status"] = "filterable"
    report = await preview_spatial_reenrichment(
        FakeStore([inconsistent]),
        FakeProjector(),
        ReenrichmentJob(lane="analysis", target_projection_revision=target),
    )

    before = report["coverage_before"]["lanes"][0]
    assert before["inconsistent_points"] == 1
    assert before["unprojected_points"] == 0
    assert report["stale_rate"] == 1.0
    assert report["stale_gate_passed"] is False


@pytest.mark.asyncio
async def test_mixed_conflict_with_admitted_tokens_counts_as_filterable() -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
    )

    class MixedProjector(FakeProjector):
        def project(self, point, job):
            return _projection(
                job.target_projection_revision,
                status="filterable",
                conflict=True,
            )

    target = "spatial-projection-v1-47fec701a2a2"
    mixed = _projection(target, status="filterable", conflict=True)
    report = await preview_spatial_reenrichment(
        FakeStore([mixed]),
        MixedProjector(),
        ReenrichmentJob(lane="analysis", target_projection_revision=target),
    )

    before = report["coverage_before"]["lanes"][0]
    projected = report["coverage_projected"]["lanes"][0]
    assert before["filterable_points"] == 1
    assert before["conflict_points"] == 0
    assert projected["filterable_points"] == 1


def test_projection_revision_and_scheduling_follow_derivation_changes_only() -> None:
    from rag.spatial_reenrich import plan_spatial_reenrichment_jobs
    from spatial import derive_spatial_projection_revision

    before = {
        "world": "spatial-derive-v1-28eba7a35d89",
        "country:UKR": "spatial-derive-v1-111111111111",
    }
    after = {
        **before,
        "country:UKR": "spatial-derive-v1-d30efa07e141",
    }
    target = derive_spatial_projection_revision(after)

    jobs = plan_spatial_reenrichment_jobs(
        before,
        after,
        lanes=("analysis", "realtime"),
    )

    assert {(job.lane, job.target_projection_revision) for job in jobs} == {
        ("analysis", target),
        ("realtime", target),
    }
    assert plan_spatial_reenrichment_jobs(
        after,
        dict(after),
        lanes=("analysis", "realtime"),
    ) == ()


def test_active_projection_revision_matches_shared_contract_vector() -> None:
    from spatial import derive_spatial_projection_revision

    manifest = json.loads(CATALOG_MANIFEST_PATH.read_text(encoding="utf-8"))
    revisions = {
        item["scope"]["key"]: item["derivation_revision"]
        for item in manifest["scopes"]
    }
    contract = json.loads(PAYLOAD_CONTRACT_PATH.read_text(encoding="utf-8"))

    assert derive_spatial_projection_revision(revisions) == (
        contract["vectors"][0]["payload"]["spatial_projection_revision"]
    )


def test_json_checkpoint_store_uses_atomic_service_independent_v1_format(
    tmp_path: Path,
) -> None:
    from rag.spatial_reenrich import (
        Checkpoint,
        JsonCheckpointStore,
        ReenrichmentJob,
    )

    path = tmp_path / "state/checkpoints.json"
    store = JsonCheckpointStore(path)
    job = ReenrichmentJob(
        lane="analysis",
        target_projection_revision="spatial-projection-v1-111111111111",
    )

    fingerprint = "a" * 64
    store.save(
        job,
        Checkpoint(
            cursor="page-2",
            complete=False,
            approved_report_fingerprint=fingerprint,
        ),
    )

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "checkpoints": [
            {
                "job_key": (
                    "analysis|spatial-projection-v1-111111111111"
                ),
                "cursor": "page-2",
                "complete": False,
                "approved_report_fingerprint": fingerprint,
            }
        ],
    }
    assert JsonCheckpointStore(path).load(job) == Checkpoint(
        cursor="page-2",
        complete=False,
        approved_report_fingerprint=fingerprint,
    )


def test_json_checkpoint_store_roundtrips_a_pristine_checkpoint(
    tmp_path: Path,
) -> None:
    from rag.spatial_reenrich import (
        Checkpoint,
        JsonCheckpointStore,
        ReenrichmentJob,
    )

    path = tmp_path / "checkpoints.json"
    store = JsonCheckpointStore(path)
    job = ReenrichmentJob(
        lane="analysis",
        target_projection_revision="spatial-projection-v1-111111111111",
    )

    store.save(job, Checkpoint())

    assert JsonCheckpointStore(path).load(job) == Checkpoint()
    assert json.loads(path.read_text(encoding="utf-8"))["checkpoints"][0][
        "approved_report_fingerprint"
    ] is None


def test_json_checkpoint_store_upgrades_only_a_pristine_legacy_entry(
    tmp_path: Path,
) -> None:
    from rag.spatial_reenrich import JsonCheckpointStore, ReenrichmentJob

    path = tmp_path / "checkpoints.json"
    job = ReenrichmentJob(
        lane="analysis",
        target_projection_revision="spatial-projection-v1-111111111111",
    )
    legacy = {
        "schema_version": 1,
        "checkpoints": [
            {
                "job_key": job.checkpoint_key,
                "cursor": None,
                "complete": False,
            }
        ],
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    store = JsonCheckpointStore(path)
    pristine = store.load(job)
    assert pristine.approved_report_fingerprint is None
    store.save(job, pristine)
    assert "approved_report_fingerprint" in json.loads(
        path.read_text(encoding="utf-8")
    )["checkpoints"][0]

    legacy["checkpoints"][0]["cursor"] = "page-2"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(ValueError, match="approval fingerprint"):
        JsonCheckpointStore(path).load(job)


def test_shared_batch_contract_pins_plan06a_and_qdrant_semantics() -> None:
    contract = json.loads(BATCH_CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract["contract_version"] == 1
    assert contract["semantics"] == {
        "dry_run_writes": 0,
        "apply_requires": "approved-complete-full-lane-dry-run",
        "checkpoint_after": "complete-confirmed-batch",
        "report_fingerprint": "sha256-canonical-json-excluding-self",
    }
    assert contract["neo4j_plan06a"]["checkpoint_entry_fields"] == [
        "job_key",
        "last_record_id",
    ]
    assert contract["qdrant_plan07a"]["checkpoint_entry_fields"] == [
        "job_key",
        "cursor",
        "complete",
        "approved_report_fingerprint",
    ]
    assert contract["qdrant_plan07a"]["legacy_checkpoint_policy"] == (
        "accept-pristine-reject-durable-without-approval"
    )
    assert contract["qdrant_plan07a"]["checkpoint_approval_field"] == (
        "null-only-pristine-64hex-for-durable"
    )
    assert contract["qdrant_plan07a"]["coverage_snapshot_fields"] == [
        "total_points",
        "filterable_points",
        "conflict_points",
        "stale_points",
        "unsupported_points",
        "unprojected_points",
        "audit_only_points",
        "inconsistent_points",
    ]
    assert contract["qdrant_plan07a"]["point_write"] == (
        "full-point-upsert-preserving-vector-and-nonspatial-payload"
    )
    assert contract["qdrant_plan07a"]["projection_owned_payload"] == {
        "prefixes": ["spatial_"],
        "exact_fields": [
            "geo",
            "source_country_code",
            "source_country_code_system",
            "country_iso3",
            "admin1_code",
            "admin2_code",
        ],
    }
    assert contract["qdrant_plan07a"]["report_rate_fields"] == [
        "stale_rate",
        "unprojected_rate",
        "filterable_rate",
        "projected_filterable_rate",
    ]


@pytest.mark.asyncio
async def test_qdrant_adapter_scrolls_with_lane_filter_and_full_upserts() -> None:
    from qdrant_client import models

    from rag.spatial_reenrich import (
        QdrantReenrichmentStore,
        ReenrichmentPoint,
    )

    class FakeQdrantClient:
        def __init__(self) -> None:
            self.scroll_calls: list[dict[str, object]] = []
            self.upsert_calls: list[dict[str, object]] = []

        async def scroll(self, **kwargs):
            self.scroll_calls.append(kwargs)
            return (
                [
                    models.Record(
                        id=7,
                        vector=[0.25, 0.75],
                        payload={"source": "rss"},
                    )
                ],
                8,
            )

        async def upsert(self, **kwargs):
            self.upsert_calls.append(kwargs)

    client = FakeQdrantClient()
    lane_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="source",
                match=models.MatchValue(value="rss"),
            )
        ]
    )
    store = QdrantReenrichmentStore(
        client,
        "worldview",
        {"analysis": lane_filter},
    )

    page = await store.fetch_page("analysis", None, 50)
    written = await store.replace_points(
        "analysis",
        (
            ReenrichmentPoint(
                point_id=7,
                vector=[0.25, 0.75],
                payload={"source": "rss", "spatial_conflict": False},
            ),
        ),
    )

    assert page.points[0].payload == {"source": "rss"}
    assert page.next_cursor == 8
    assert client.scroll_calls == [
        {
            "collection_name": "worldview",
            "scroll_filter": lane_filter,
            "limit": 50,
            "offset": None,
            "with_payload": True,
            "with_vectors": True,
        }
    ]
    assert written == 1
    assert len(client.upsert_calls) == 1
    upsert = client.upsert_calls[0]
    assert upsert["collection_name"] == "worldview"
    assert upsert["wait"] is True
    point = upsert["points"][0]
    assert point.id == 7
    assert point.vector == [0.25, 0.75]
    assert point.payload == {"source": "rss", "spatial_conflict": False}


@pytest.mark.asyncio
async def test_projector_cannot_reintroduce_obsolete_scalar_revision() -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
    )

    class PoisonProjector(FakeProjector):
        def project(self, point, job):
            projection = super().project(point, job)
            projection["spatial_derivation_revision"] = (
                "spatial-derive-v1-111111111111"
            )
            return projection

    target = "spatial-projection-v1-47fec701a2a2"
    store = FakeStore([_old_payload()])
    with pytest.raises(ValueError, match="scalar derivation revision"):
        await preview_spatial_reenrichment(
            store,
            PoisonProjector(),
            ReenrichmentJob(
                lane="analysis",
                target_projection_revision=target,
            ),
        )

    assert store.replace_calls == []


@pytest.mark.asyncio
async def test_reviewed_dry_run_validation_detects_report_drift() -> None:
    from rag.spatial_reenrich import (
        ReenrichmentJob,
        preview_spatial_reenrichment,
        validate_dry_run_approval,
    )

    target = "spatial-projection-v1-47fec701a2a2"
    report = await preview_spatial_reenrichment(
        FakeStore([_old_payload()]),
        FakeProjector(),
        ReenrichmentJob(lane="analysis", target_projection_revision=target),
    )
    validate_dry_run_approval(report, deepcopy(report))

    drifted = deepcopy(report)
    drifted["writes_planned"] = 2
    with pytest.raises(ValueError, match="drifted"):
        validate_dry_run_approval(report, drifted)
