"""Scheduler contract for GDELT Raw-only production ingestion."""

from __future__ import annotations


def _job_ids(scheduler) -> set[str]:
    return {job.id for job in scheduler.get_jobs()}


def _initial_job_names() -> set[str]:
    from scheduler import initial_collection_jobs

    return {job.__name__ for job in initial_collection_jobs()}


def test_scheduler_registers_gdelt_raw_forward_only(monkeypatch):
    """Even if the old env flag is set, the legacy DOC collector stays unscheduled."""
    monkeypatch.setenv("ENABLE_LEGACY_GDELT_DOC", "true")

    from scheduler import create_scheduler

    scheduler = create_scheduler()

    assert "gdelt_raw_forward" in _job_ids(scheduler)
    assert "gdelt_collector" not in _job_ids(scheduler)


def test_startup_jobs_exclude_legacy_gdelt_doc(monkeypatch):
    """Startup fanout must not run the legacy DOC collector."""
    monkeypatch.setenv("ENABLE_LEGACY_GDELT_DOC", "true")

    names = _initial_job_names()

    assert "run_gdelt_collector" not in names
    assert "run_rss_collector" in names

