"""RSS feed fetching tool for OSINT agent."""

import xml.etree.ElementTree as ET

import httpx
import structlog
from langchain_core.tools import tool

logger = structlog.get_logger()


@tool
async def rss_fetch(feed_url: str) -> str:
    """Fetch and parse an RSS feed to get recent articles.

    Args:
        feed_url: URL of the RSS feed to fetch.

    Returns:
        Formatted text with recent articles from the feed.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(feed_url)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        items = root.findall(".//item")[:10]

        results: list[str] = []
        for item in items:
            title = item.findtext("title", "No title")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")[:200]
            results.append(f"- {title} ({pub_date})\n  {description}\n  {link}")

        if not results:
            return f"No articles found in feed: {feed_url}"

        return f"[RSS Feed: {feed_url}]\n" + "\n".join(results)
    except Exception as e:
        logger.warning("rss_fetch_failed", url=feed_url, error=str(e))
        return f"Failed to fetch RSS feed: {feed_url} - {e}"
