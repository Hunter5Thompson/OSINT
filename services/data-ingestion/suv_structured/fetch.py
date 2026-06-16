"""Render the SUV directory via the crawl4ai HTTP service (JS executed server-side).

crawl4ai is consumed as a service (no Python/browser dependency), mirroring
feeds/_fulltext_fetch._crawl4ai_md. The `/md` fit endpoint runs a headless
browser; the walking-skeleton confirmed it returns the AJAX-rendered company rows
(77 companies, all detail on one page)."""
from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger(__name__)

_FIT_KEYS = ("fit_markdown", "markdown")


async def fetch_directory_markdown(
    url: str, *, crawl4ai_url: str, client: httpx.AsyncClient
) -> str:
    """POST to crawl4ai /md and return the fit markdown. Raises ValueError if empty."""
    resp = await client.post(f"{crawl4ai_url.rstrip('/')}/md", json={"url": url, "f": "fit"})
    resp.raise_for_status()
    data = resp.json()
    for k in _FIT_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            log.info("suv_directory_rendered", url=url, chars=len(v))
            return v
    raise ValueError(f"crawl4ai returned no markdown for {url}")
