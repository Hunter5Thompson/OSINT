"""Scheduler mode tests for Legacy DOC GDELT vs GDELT Raw ingestion."""

from __future__ import annotations


def _job_ids(scheduler) -> set[str]:
    return {job.id for job in scheduler.get_jobs()}


def _initial_job_names() -> set[str]:
    from scheduler import initial_collection_jobs

    return {job.__name__ for job in initial_collection_jobs()}


def test_legacy_gdelt_doc_job_disabled_by_default(monkeypatch):
    from scheduler import create_scheduler, settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", False, raising=False)

    scheduler = create_scheduler()

    assert "gdelt_collector" not in _job_ids(scheduler)
    assert "gdelt_raw_forward" in _job_ids(scheduler)


def test_legacy_gdelt_doc_job_can_be_enabled(monkeypatch):
    from scheduler import create_scheduler, settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", True, raising=False)

    scheduler = create_scheduler()

    assert "gdelt_collector" in _job_ids(scheduler)
    assert "gdelt_raw_forward" in _job_ids(scheduler)


def test_legacy_gdelt_doc_startup_job_disabled_by_default(monkeypatch):
    from scheduler import settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", False, raising=False)

    names = _initial_job_names()

    assert "run_gdelt_collector" not in names
    assert "run_rss_collector" in names


def test_legacy_gdelt_doc_startup_job_can_be_enabled(monkeypatch):
    from scheduler import settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", True, raising=False)

    names = _initial_job_names()

    assert "run_gdelt_collector" in names
    assert "run_rss_collector" in names


def test_legacy_gdelt_doc_config_defaults_disabled(monkeypatch):
    from config import Settings

    monkeypatch.delenv("ENABLE_LEGACY_GDELT_DOC", raising=False)

    settings = Settings(_env_file=None)

    assert settings.enable_legacy_gdelt_doc is False
