"""RSS feed fetching tool for OSINT agent."""

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
import structlog
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from agents.tools.capabilities import tool_allowed_for_state
from graph.state import AgentState
from rag.evidence import neutralize_evidence_markers, pack_with_lineage, to_evidence_item

logger = structlog.get_logger()


@tool(response_format="content_and_artifact")
async def rss_fetch(
    feed_url: str,
    runtime: ToolRuntime[dict[str, object], AgentState],
) -> tuple[str, list[dict]]:
    """Fetch and parse an RSS feed to get recent articles.

    Args:
        feed_url: URL of the RSS feed to fetch.

    Returns:
        A budgeted evidence pack: one `[EVIDENCE] {json}` metadata line per
        article (provider = article domain, source_type = rss, published_at from
        pubDate, url, ...) followed by Title/Excerpt lines. Newest-first.
    """
    if not tool_allowed_for_state("rss_fetch", runtime.state):
        return "SPATIAL_SCOPE_UNSUPPORTED: rss_fetch", []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(feed_url)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)

        items = []
        for idx, item in enumerate(root.findall(".//item")[:10]):
            title = item.findtext("title", "No title")
            link = item.findtext("link", "") or ""
            pub_date = item.findtext("pubDate", "") or ""
            description = (item.findtext("description", "") or "")[:700]
            try:
                published_iso = parsedate_to_datetime(pub_date).isoformat() if pub_date else None
            except (TypeError, ValueError):
                published_iso = None
            domain = (
                urlparse(link).netloc or urlparse(feed_url).netloc or "rss"
            ).removeprefix("www.")
            items.append(to_evidence_item({
                "score": 1.0 - idx * 0.001,
                "source_type": "rss",
                "provider": domain,
                "title": title,
                "content": description,
                "url": link,
                "published_at": published_iso,
            }))

        if not items:
            return f"No articles found in feed: {neutralize_evidence_markers(feed_url)}", []

        pack, lineage = pack_with_lineage(items, budget=6500)
        return f"[RSS Evidence: {neutralize_evidence_markers(feed_url)}]\n{pack}", lineage
    except Exception as e:
        logger.warning("rss_fetch_failed", url=feed_url, error=str(e))
        return (f"Failed to fetch RSS feed: {neutralize_evidence_markers(feed_url)} - "
                f"{neutralize_evidence_markers(str(e))}"), []
