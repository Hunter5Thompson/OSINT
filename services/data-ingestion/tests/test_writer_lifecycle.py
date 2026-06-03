"""Lifecycle and event-loop safety tests for Qdrant-backed ingestion jobs."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.base import BaseCollector
from feeds.correlation_job import CorrelationJob
from feeds.hotspot_updater import HotspotUpdater


class _ConcreteCollector(BaseCollector):
    async def collect(self) -> None:
        pass


def _base_settings() -> MagicMock:
    settings = MagicMock()
    settings.qdrant_url = "http://localhost:6333"
    settings.qdrant_collection = "odin_intel"
    settings.tei_embed_url = "http://localhost:8001"
    settings.http_timeout = 30.0
    return settings


@pytest.mark.asyncio
async def test_base_collector_close_releases_http_and_qdrant() -> None:
    with patch("feeds.base.QdrantClient"):
        collector = _ConcreteCollector(settings=_base_settings())

    collector.http = MagicMock(aclose=AsyncMock())
    collector.qdrant = MagicMock()

    await collector.close()

    collector.http.aclose.assert_awaited_once()
    collector.qdrant.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_hotspot_scroll_runs_outside_event_loop() -> None:
    def scroll(**_: object) -> tuple[list[MagicMock], None]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return ([MagicMock()], None)
        raise AssertionError("sync Qdrant scroll ran on the event-loop thread")

    with patch("feeds.hotspot_updater.QdrantClient") as qdrant_cls:
        qdrant_cls.return_value.scroll = scroll
        updater = HotspotUpdater()

    assert await updater._count_recent_mentions("Taiwan Strait") == 1


@pytest.mark.asyncio
async def test_hotspot_close_releases_redis_and_qdrant() -> None:
    with patch("feeds.hotspot_updater.QdrantClient"):
        updater = HotspotUpdater()

    updater._redis = MagicMock(close=AsyncMock())
    updater.qdrant = MagicMock()

    await updater.close()

    assert updater._redis is None
    updater.qdrant.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_correlation_close_releases_qdrant() -> None:
    with patch("feeds.correlation_job.QdrantClient"):
        job = CorrelationJob(settings=_base_settings())

    job.qdrant = MagicMock()

    await job.close()

    job.qdrant.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_scheduler_closes_correlation_job_after_failure() -> None:
    import scheduler

    job = MagicMock(run=AsyncMock(side_effect=RuntimeError("boom")), close=AsyncMock())
    with patch("scheduler.CorrelationJob", return_value=job):
        await scheduler.run_correlation_job()

    job.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_closes_rss_collector_after_failure() -> None:
    import scheduler

    collector = MagicMock(
        collect=AsyncMock(side_effect=RuntimeError("boom")),
        close=AsyncMock(),
    )
    with patch("scheduler.RSSCollector", return_value=collector):
        await scheduler.run_rss_collector()

    collector.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_closes_telegram_collector_after_failure() -> None:
    import scheduler

    collector = MagicMock(
        collect=AsyncMock(side_effect=RuntimeError("boom")),
        close=AsyncMock(),
    )
    with patch("scheduler.TelegramCollector", return_value=collector):
        await scheduler.run_telegram_collector()

    collector.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("runner_name", "factory_name", "operation"),
    [
        ("run_rss_collector", "RSSCollector", "collect"),
        ("run_hotspot_updater", "HotspotUpdater", "update"),
        ("run_telegram_collector", "TelegramCollector", "collect"),
        ("run_ucdp_collector", "UCDPCollector", "collect"),
        ("run_firms_collector", "FIRMSCollector", "collect"),
        ("run_usgs_collector", "USGSCollector", "collect"),
        ("run_military_collector", "MilitaryAircraftCollector", "collect"),
        ("run_ofac_collector", "OFACCollector", "collect"),
        ("run_correlation_job", "CorrelationJob", "run"),
        ("run_eonet_collector", "EONETCollector", "collect"),
        ("run_gdacs_collector", "GDACSCollector", "collect"),
        ("run_hapi_collector", "HAPICollector", "collect"),
        ("run_noaa_nhc_collector", "NOAANHCCollector", "collect"),
        ("run_portwatch_collector", "PortWatchCollector", "collect"),
        ("run_fulltext_collector", "FulltextCollector", "collect"),
    ],
)
@pytest.mark.asyncio
async def test_scheduler_constructs_qdrant_owners_outside_event_loop(
    runner_name: str,
    factory_name: str,
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scheduler

    # fulltext_collector is gated — enable it so the wrapper reaches _construct_off_loop.
    # Harmless for all other parametrized cases (they don't read this flag).
    monkeypatch.setattr(scheduler.settings, "fulltext_enabled", True, raising=False)

    owner = MagicMock(close=AsyncMock())
    setattr(owner, operation, AsyncMock())

    def build(**_: object) -> MagicMock:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return owner

    with (
        patch.object(scheduler, factory_name, side_effect=build),
        patch("scheduler._get_redis_client", return_value=MagicMock()),
    ):
        await getattr(scheduler, runner_name)()

    owner.close.assert_awaited_once()
