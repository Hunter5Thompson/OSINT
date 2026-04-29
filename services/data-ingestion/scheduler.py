"""Main entry point — APScheduler-based async scheduler for all feed collectors."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
import redis.asyncio as aioredis
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from feeds.correlation_job import CorrelationJob
from feeds.eonet_collector import EONETCollector
from feeds.firms_collector import FIRMSCollector
from feeds.gdacs_collector import GDACSCollector
from feeds.hapi_collector import HAPICollector
from feeds.hotspot_updater import HotspotUpdater
from feeds.military_aircraft_collector import MilitaryAircraftCollector
from feeds.noaa_nhc_collector import NOAANHCCollector
from feeds.ofac_collector import OFACCollector
from feeds.portwatch_collector import PortWatchCollector
from feeds.rss_collector import RSSCollector
from feeds.telegram_collector import TelegramCollector
from feeds.tle_updater import TLEUpdater
from feeds.ucdp_collector import UCDPCollector
from feeds.usgs_collector import USGSCollector

# Shared async Redis client for stream publishing
_redis_client: aioredis.Redis | None = None


def _get_redis_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url)
    return _redis_client

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
        structlog.dev.ConsoleRenderer()
        if sys.stderr.isatty()
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("scheduler")


# ---------------------------------------------------------------------------
# Startup healthcheck — Spark / local ingestion vLLM reachability
# ---------------------------------------------------------------------------
async def check_ingestion_llm() -> None:
    """Probe the ingestion vLLM at startup. Never raises — only logs.

    Three exclusive outcomes:
      - ready:         200 + ingestion_vllm_model in /v1/models data[].id
      - config error:  200 without model OR 401/403/404
      - unreachable:   connect error / timeout / 5xx / unexpected response shape

    The scheduler must keep running regardless of outcome, so this helper
    swallows every exception and only emits structured log events.
    """
    base_url = settings.ingestion_vllm_url
    url = f"{base_url}/v1/models"
    expected_model = settings.ingestion_vllm_model

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else []
            ids = [
                m.get("id")
                for m in data
                if isinstance(m, dict) and m.get("id") is not None
            ]
            if expected_model in ids:
                log.info(
                    "ingestion_llm_ready",
                    url=base_url,
                    model=expected_model,
                )
            else:
                log.error(
                    "ingestion_llm_model_mismatch",
                    url=base_url,
                    expected=expected_model,
                    available=ids,
                )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403, 404):
            log.error(
                "ingestion_llm_config_error",
                url=url,
                status=status,
                error=str(exc),
            )
        else:
            log.warning(
                "ingestion_llm_unreachable",
                url=url,
                error=f"http {status}",
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.warning("ingestion_llm_unreachable", url=url, error=str(exc))
    except Exception as exc:  # noqa: BLE001 — must never propagate
        # Malformed JSON, unexpected response shape, DNS errors, etc.
        log.warning("ingestion_llm_unreachable", url=url, error=str(exc))


# ---------------------------------------------------------------------------
# Job wrapper functions (APScheduler calls these)
# ---------------------------------------------------------------------------
async def run_rss_collector() -> None:
    """Collect RSS feeds."""
    try:
        collector = RSSCollector(redis_client=_get_redis_client())
        await collector.collect()
    except Exception:
        log.exception("rss_job_failed")


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


async def run_telegram_collector() -> None:
    """Collect Telegram channel messages."""
    collector = TelegramCollector(redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("telegram_job_failed")
    finally:
        await collector.disconnect()



async def run_ucdp_collector() -> None:
    """Collect UCDP GED conflict events."""
    collector = UCDPCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("ucdp_job_failed")
    finally:
        await collector.close()


async def run_firms_collector() -> None:
    """Collect NASA FIRMS thermal anomalies."""
    collector = FIRMSCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("firms_job_failed")
    finally:
        await collector.close()


async def run_usgs_collector() -> None:
    """Collect USGS earthquakes with nuclear enrichment."""
    collector = USGSCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("usgs_job_failed")
    finally:
        await collector.close()


async def run_military_collector() -> None:
    """Collect military aircraft positions."""
    collector = MilitaryAircraftCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("military_job_failed")
    finally:
        await collector.close()


async def run_ofac_collector() -> None:
    """Collect OFAC sanctions list."""
    collector = OFACCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("ofac_job_failed")
    finally:
        await collector.close()


async def run_correlation_job() -> None:
    """Correlate FIRMS thermal anomalies with ACLED conflict events."""
    job = CorrelationJob(
        settings=settings, redis_client=_get_redis_client()
    )
    try:
        await job.run()
    except Exception:
        log.exception("correlation_job_failed")


async def run_eonet_collector() -> None:
    """Collect NASA EONET natural events."""
    collector = EONETCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("eonet_job_failed")
    finally:
        await collector.close()


async def run_gdacs_collector() -> None:
    """Collect GDACS global disaster alerts."""
    collector = GDACSCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("gdacs_job_failed")
    finally:
        await collector.close()


async def run_hapi_collector() -> None:
    """Collect HAPI humanitarian data."""
    collector = HAPICollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("hapi_job_failed")
    finally:
        await collector.close()


async def run_noaa_nhc_collector() -> None:
    """Collect NOAA NHC tropical storm advisories."""
    collector = NOAANHCCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("noaa_nhc_job_failed")
    finally:
        await collector.close()


async def run_portwatch_collector() -> None:
    """Collect IMF PortWatch maritime trade data."""
    collector = PortWatchCollector(settings=settings, redis_client=_get_redis_client())
    try:
        await collector.collect()
    except Exception:
        log.exception("portwatch_job_failed")
    finally:
        await collector.close()


async def run_gdelt_raw_collector() -> None:
    """Wrap the GDELT raw-files collector in async context for APScheduler.

    Imports lazily inside the function so scheduler startup doesn't pay the
    cost of pulling in heavy clients (AsyncQdrantClient, Neo4j driver,
    Polars-based writers) until the first scheduled run.
    """
    try:
        from feeds.gdelt_raw_collector import run_once
        await run_once()
    except Exception:
        log.exception("gdelt_raw_job_failed")


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

    # Telegram channels — every 5 minutes (adaptive internally)
    scheduler.add_job(
        run_telegram_collector,
        trigger=IntervalTrigger(minutes=5),
        id="telegram_collector",
        name="Telegram Channel Collector",
        replace_existing=True,
    )

    # --- Hugin P0 Collectors ---


    scheduler.add_job(
        run_ucdp_collector,
        trigger=IntervalTrigger(hours=settings.ucdp_interval_hours),
        id="ucdp_collector",
        name="UCDP GED Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_firms_collector,
        trigger=IntervalTrigger(hours=settings.firms_interval_hours),
        id="firms_collector",
        name="FIRMS Thermal Anomaly Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_usgs_collector,
        trigger=IntervalTrigger(hours=settings.usgs_interval_hours),
        id="usgs_collector",
        name="USGS Nuclear Earthquake Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_military_collector,
        trigger=IntervalTrigger(minutes=settings.military_interval_minutes),
        id="military_aircraft_collector",
        name="Military Aircraft Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_ofac_collector,
        trigger=CronTrigger(hour=3, minute=30, timezone="UTC"),
        id="ofac_collector",
        name="OFAC Sanctions Collector",
        replace_existing=True,
    )

    # FIRMS-ACLED Correlation — 5 min offset from FIRMS
    correlation_start = datetime.now(UTC) + timedelta(minutes=5)
    scheduler.add_job(
        run_correlation_job,
        trigger=IntervalTrigger(
            hours=settings.correlation_interval_hours,
            start_date=correlation_start,
        ),
        id="firms_acled_correlation",
        name="FIRMS-ACLED Correlation",
        replace_existing=True,
    )

    # --- Hugin Sprint 2a Collectors ---

    scheduler.add_job(
        run_eonet_collector,
        trigger=IntervalTrigger(hours=settings.eonet_interval_hours),
        id="eonet_collector",
        name="NASA EONET Natural Events Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_gdacs_collector,
        trigger=IntervalTrigger(hours=settings.gdacs_interval_hours),
        id="gdacs_collector",
        name="GDACS Global Disaster Alert Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_hapi_collector,
        trigger=CronTrigger(hour=4, minute=0, timezone="UTC"),
        id="hapi_collector",
        name="HAPI Humanitarian Data Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_noaa_nhc_collector,
        trigger=IntervalTrigger(hours=settings.noaa_nhc_interval_hours),
        id="noaa_nhc_collector",
        name="NOAA NHC Tropical Storm Collector",
        replace_existing=True,
    )

    scheduler.add_job(
        run_portwatch_collector,
        trigger=IntervalTrigger(hours=settings.portwatch_interval_hours),
        id="portwatch_collector",
        name="IMF PortWatch Maritime Trade Collector",
        replace_existing=True,
    )

    # GDELT raw-files forward sweep — every GDELT_FORWARD_INTERVAL_SECONDS
    # (default 900s = 15 min). 30s offset prevents cold-start thundering herd
    # when the scheduler boots alongside Neo4j/Qdrant/TEI healthchecks.
    scheduler.add_job(
        run_gdelt_raw_collector,
        "interval",
        seconds=int(os.getenv("GDELT_FORWARD_INTERVAL_SECONDS", "900")),
        id="gdelt_raw_forward",
        name="GDELT Raw Files Forward Collector",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC) + timedelta(seconds=30),
        replace_existing=True,
    )

    return scheduler


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def initial_collection_jobs() -> list[Callable[[], Awaitable[None]]]:
    """Jobs to run once on scheduler startup before interval triggers fire."""
    jobs: list[Callable[[], Awaitable[None]]] = [
        run_rss_collector,
        run_tle_updater,
        run_hotspot_updater,
        run_telegram_collector,
        run_ucdp_collector,
        run_firms_collector,
        run_usgs_collector,
        run_military_collector,
        run_eonet_collector,
        run_gdacs_collector,
        # HAPI runs daily via cron, not on initial startup.
        run_noaa_nhc_collector,
        run_portwatch_collector,
        # OFAC runs daily via cron, not on initial startup.
    ]
    return jobs


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

    # Probe the ingestion vLLM (Spark or local) so a misconfigured URL
    # shows up in logs immediately instead of as a flood of pipeline errors
    # later.  Never raises — jobs continue regardless of outcome.
    await check_ingestion_llm()

    # Run initial collection on startup (don't wait for first interval)
    log.info("initial_collection_starting")
    initial_tasks = [job() for job in initial_collection_jobs()]
    await asyncio.gather(*initial_tasks, return_exceptions=True)
    log.info("initial_collection_complete")

    # Block until shutdown signal
    await shutdown_event.wait()

    log.info("scheduler_shutting_down")
    scheduler.shutdown(wait=True)
    if _redis_client is not None:
        await _redis_client.aclose()
    log.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
