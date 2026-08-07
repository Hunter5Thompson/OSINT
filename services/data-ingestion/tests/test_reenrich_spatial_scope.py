import pytest

from graph_integrity.reenrich_spatial_scope import plan_reenrichment_jobs, run_jobs
from graph_integrity.spatial_batch import MemoryCheckpointStore, report_fingerprint


def test_new_derivation_revision_schedules_each_affected_lane() -> None:
    previous = {
        "country:UKR": "derive-country-a",
        "admin1:iso3166-2:UA-30": "derive-admin-a",
    }
    current = {
        "country:UKR": "derive-country-a",
        "admin1:iso3166-2:UA-30": "derive-admin-b",
    }

    jobs = plan_reenrichment_jobs(previous, current, batch_size=17)

    assert {(job.lane, job.target_derivation_revision) for job in jobs} == {
        ("gdelt_raw", "derive-admin-b"),
        ("military_aircraft", "derive-admin-b"),
        ("backend_incident", "derive-admin-b"),
    }
    assert all(job.job_kind == "reenrichment" for job in jobs)
    assert all(job.batch_size == 17 for job in jobs)
    assert all(job.target_scope_keys == ("admin1:iso3166-2:UA-30",) for job in jobs)


def test_catalog_carry_forward_of_derivation_revision_schedules_no_rewrite() -> None:
    revisions = {
        "country:UKR": "derive-country-a",
        "admin1:iso3166-2:UA-30": "derive-admin-a",
    }

    assert plan_reenrichment_jobs(revisions, dict(revisions)) == ()


def test_country_revision_schedules_country_only_rss_lane_too() -> None:
    jobs = plan_reenrichment_jobs(
        {"country:UKR": "derive-country-a"},
        {"country:UKR": "derive-country-b"},
    )

    assert {job.lane for job in jobs} == {
        "gdelt_raw",
        "rss_pipeline",
        "military_aircraft",
        "backend_incident",
    }


@pytest.mark.asyncio
async def test_carry_forward_run_emits_complete_zero_job_report() -> None:
    class EmptyIndex:
        catalog_revision = "spatial-v1-111111111111"

    report = await run_jobs(
        client=None,  # type: ignore[arg-type]
        spatial_index=EmptyIndex(),  # type: ignore[arg-type]
        checkpoints=MemoryCheckpointStore(),
        jobs=(),
        dry_run=True,
    )

    assert report["complete"] is True
    assert report["job_count"] == 0
    assert report["totals"]["writes_planned"] == 0
    assert report["report_fingerprint"] == report_fingerprint(report)
