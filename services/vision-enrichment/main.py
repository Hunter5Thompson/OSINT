"""Vision Enrichment Service — main entry point."""

from __future__ import annotations

import asyncio
import signal

import redis.asyncio as aioredis
import structlog

from config import settings
from consumer import VisionConsumer

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("vision-enrichment")


async def main() -> None:
    """Start the vision enrichment consumer."""
    log.info("vision_service_starting")

    redis_client = aioredis.from_url(settings.redis_url)
    consumer = VisionConsumer(redis_client=redis_client)

    shutdown_event = asyncio.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        log.info("signal_received", signal=signal.Signals(signum).name)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    consumer_task = asyncio.create_task(consumer.run())

    # Wait for shutdown signal
    await shutdown_event.wait()

    log.info("vision_service_shutting_down")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
    log.info("vision_service_stopped")


if __name__ == "__main__":
    asyncio.run(main())
