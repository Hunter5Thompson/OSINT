"""Bounded fetch telemetry, independent of ingestion counts and source freshness."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import structlog

KEY = "health:collector-fetch:v1"
log = structlog.get_logger(__name__)


def catalog() -> list[dict[str, object]]:
    from feeds.hapi_collector import FOCUS_COUNTRIES
    from feeds.ofac_collector import OFAC_FEEDS
    from feeds.rss_collector import RSS_FEEDS

    return [
        {"id": f"{kind}:{name}", "collector": kind, "name": name, "max_age_s": age}
        for kind, names, age in (
            ("rss", [feed["name"] for feed in RSS_FEEDS], 7200),
            ("ofac", list(OFAC_FEEDS), 172800),
            ("hapi", FOCUS_COUNTRIES, 172800),
        )
        for name in names
    ]


async def _store(redis: Any, mapping: dict[str, str]) -> None:
    if redis is None:
        return
    try:
        async with asyncio.timeout(2):
            await redis.hset(KEY, mapping=mapping)
    except Exception:
        log.warning("collector_telemetry_unavailable")


async def register_catalog(redis: Any) -> None:
    await _store(redis, {"_registry": json.dumps(catalog())})


def fetch_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return "transport_error"


async def record_fetch(
    redis: Any, collector: str, name: str, *, item_count: int | None = None,
    error_code: str | None = None, now: float | None = None,
) -> None:
    """One atomic hash write; failures retain the preceding successful fetch time.

    Available only means the publisher returned a parseable response. It does
    not assert successful extraction, graph writes, new evidence or factual truth.
    No response bodies, credential-bearing URLs or raw exception strings persist.
    """
    timestamp = int(time.time() if now is None else now)
    key = f"{collector}:{name}"
    status = ("not_configured" if error_code == "missing_identifier"
              else "unavailable" if error_code else "available")
    mapping = {key: json.dumps({
        "status": status, "attempt_at": timestamp,
        "error_code": error_code, "item_count": item_count,
    })}
    if error_code is None:
        mapping[f"{key}:last_success"] = str(timestamp)
    await _store(redis, mapping)
