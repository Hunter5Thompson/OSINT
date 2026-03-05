"""Main entry point — APScheduler-based async scheduler for all feed collectors."""

from __future__ import annotations

import asyncio
import signal
import sys

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from feeds.rss_collector import RSSCollector
from feeds.gdelt_collector import GDELTCollector
from feeds.tle_updater import TLEUpdater
from feeds.hotspot_updater import HotspotUpdater

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("scheduler")


# ---------------------------------------------------------------------------
# Job wrapper functions (APScheduler calls these)
# ---------------------------------------------------------------------------
async def run_rss_collector() -> None:
    """Collect RSS feeds."""
    try:
        collector = RSSCollector()
        await collector.collect()
    except Exception:
        log.exception("rss_job_failed")


async def run_gdelt_collector() -> None:
    """Collect GDELT events."""
    try:
        collector = GDELTCollector()
        await collector.collect()
    except Exception:
        log.exception("gdelt_job_failed")


async def run_tle_updater() -> None:
    """Update TLE satellite data."""
    updater = TLEUpdater()
    try:
        await updater.update()
    except Exception:
        log.exception("tle_job_failed")
    finally:
        await updater.close()


async def run_hotspot_updater() -> None:
    """Update geopolitical hotspot data."""
    updater = HotspotUpdater()
    try:
        await updater.update()
    except Exception:
        log.exception("hotspot_job_failed")
    finally:
        await updater.close()


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------
def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance with all feed jobs."""
    scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,           # collapse missed runs into one
            "max_instances": 1,          # never run the same job concurrently
            "misfire_grace_time": 300,   # 5 min grace for misfired jobs
        }
    )

    # RSS feeds — every 30 minutes
    scheduler.add_job(
        run_rss_collector,
        trigger=IntervalTrigger(minutes=30),
        id="rss_collector",
        name="RSS Feed Collector",
        replace_existing=True,
    )

    # GDELT events — every 15 minutes
    scheduler.add_job(
        run_gdelt_collector,
        trigger=IntervalTrigger(minutes=15),
        id="gdelt_collector",
        name="GDELT Event Collector",
        replace_existing=True,
    )

    # TLE satellite data — daily at 03:00 UTC
    scheduler.add_job(
        run_tle_updater,
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="tle_updater",
        name="TLE Data Updater",
        replace_existing=True,
    )

    # Geopolitical hotspots — every 6 hours
    scheduler.add_job(
        run_hotspot_updater,
        trigger=IntervalTrigger(hours=6),
        id="hotspot_updater",
        name="Hotspot Updater",
        replace_existing=True,
    )

    return scheduler


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    """Start the scheduler and run until interrupted."""
    log.info("scheduler_starting")
    scheduler = create_scheduler()

    # Register graceful shutdown
    shutdown_event = asyncio.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        signame = signal.Signals(signum).name
        log.info("signal_received", signal=signame)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    scheduler.start()
    log.info(
        "scheduler_running",
        jobs=[j.name for j in scheduler.get_jobs()],
    )

    # Run initial collection on startup (don't wait for first interval)
    log.info("initial_collection_starting")
    initial_tasks = [
        run_rss_collector(),
        run_gdelt_collector(),
        run_tle_updater(),
        run_hotspot_updater(),
    ]
    await asyncio.gather(*initial_tasks, return_exceptions=True)
    log.info("initial_collection_complete")

    # Block until shutdown signal
    await shutdown_event.wait()

    log.info("scheduler_shutting_down")
    scheduler.shutdown(wait=True)
    log.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
