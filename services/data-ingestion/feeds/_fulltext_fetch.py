"""Full-text fetch clients (crawl4ai HTML, docling PDF) + quality gate.

Pure helpers (route_kind/clean_body/is_quality) are I/O-free and unit-tested.
Network response shapes are pinned by tests/fixtures/fulltext (Task 1)."""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

# Response key holding the content-filtered markdown — verified against Task-1 SHAPES.md
# (crawl4ai returns the fit markdown in the flat top-level "markdown" key; no "fit_markdown").
_CRAWL4AI_FIT_KEYS = ("fit_markdown", "markdown")
# JSON path to docling markdown — verified against Task-1 SHAPES.md.
_DOCLING_MD_PATH = ("document", "md_content")

_LINK_LINE = re.compile(r"^\s*(?:\[[^\]]*\]\([^)]*\)\s*)+$")  # line = only md links


def route_kind(url: str) -> str:
    return "pdf" if url.lower().split("?", 1)[0].endswith(".pdf") else "html"


def clean_body(markdown: str) -> tuple[str, int]:
    """Drop nav/link-only lines; return (cleaned_text, prose_paragraph_count)."""
    lines = [ln for ln in markdown.splitlines() if not _LINK_LINE.match(ln)]
    cleaned = "\n".join(lines).strip()
    paras = [p for p in re.split(r"\n\s*\n", cleaned) if len(p.strip()) >= 10]
    return cleaned, len(paras)


def is_quality(cleaned: str, *, paragraphs: int, min_chars: int, min_paras: int) -> bool:
    return len(cleaned) >= min_chars and paragraphs >= min_paras


def _dig(d: dict, path: tuple[str, ...]) -> Any | None:
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return None
    return d


async def _crawl4ai_md(url: str, base: str, client: httpx.AsyncClient) -> str | None:
    resp = await client.post(f"{base.rstrip('/')}/md", json={"url": url, "f": "fit"})
    resp.raise_for_status()
    data = resp.json()
    for k in _CRAWL4AI_FIT_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, dict):  # tolerate nested {fit_markdown,...} on other builds
            for kk in _CRAWL4AI_FIT_KEYS:
                if isinstance(v.get(kk), str) and v[kk].strip():
                    return v[kk]
    return None


async def _docling_md(url: str, base: str, client: httpx.AsyncClient) -> str | None:
    # Corrected per SHAPES.md: /v1/convert/source + sources:[{kind:http,url}]
    # (NOT /v1alpha, NOT http_sources)
    resp = await client.post(
        f"{base.rstrip('/')}/v1/convert/source",
        json={"sources": [{"kind": "http", "url": url}], "options": {"to_formats": ["md"]}},
    )
    resp.raise_for_status()
    md = _dig(resp.json(), _DOCLING_MD_PATH)
    return md if isinstance(md, str) and md.strip() else None


async def fetch_fulltext(
    url: str, *, crawl4ai_url: str, docling_url: str,
    min_chars: int, min_paras: int, timeout: float = 60.0,
) -> str | None:
    """Fetch + clean + quality-gate. Returns cleaned markdown or None (skip)."""
    kind = route_kind(url)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            raw = (await _docling_md(url, docling_url, client)) if kind == "pdf" \
                else (await _crawl4ai_md(url, crawl4ai_url, client))
    except httpx.HTTPError as exc:
        log.warning("fulltext_fetch_failed", url=url, kind=kind, error=str(exc))
        raise  # transient — caller records status="retry"
    if not raw:
        return None
    cleaned, paras = clean_body(raw)
    if not is_quality(cleaned, paragraphs=paras, min_chars=min_chars, min_paras=min_paras):
        log.info("fulltext_quality_gate_skip", url=url, chars=len(cleaned), paras=paras)
        return None
    return cleaned
