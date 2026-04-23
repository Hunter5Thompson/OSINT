"""GDELT event database query tool."""

import httpx
import structlog
from langchain_core.tools import tool

logger = structlog.get_logger()

GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


@tool
async def gdelt_query(query: str, max_records: int = 20) -> str:
    """Query the GDELT Global Knowledge Graph for recent events.

    Args:
        query: Search terms for GDELT events.
        max_records: Maximum number of records to return (default 20).

    Returns:
        Formatted GDELT event results.
    """
    try:
        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(min(max_records, 50)),
            "format": "json",
            "sort": "DateDesc",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(GDELT_API_URL, params=params)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                content_type = (resp.headers.get("content-type") or "").lower()
                body_preview = (resp.text or "").replace("\n", " ")[:160]
                logger.warning(
                    "gdelt_non_json_response",
                    content_type=content_type,
                    preview=body_preview,
                    error=str(exc),
                )
                return f"GDELT query temporarily unavailable for: {query}"

        articles = data.get("articles", [])
        if not articles:
            return f"No GDELT results found for: {query}"

        results: list[str] = []
        for article in articles[:max_records]:
            title = article.get("title", "No title")
            url = article.get("url", "")
            source = article.get("domain", "unknown")
            date = article.get("seendate", "")
            language = article.get("language", "")
            results.append(
                f"- [{date}] {title}\n"
                f"  Source: {source} ({language}) | {url}"
            )

        return f"[GDELT Results for: {query}]\n" + "\n".join(results)
    except Exception as e:
        logger.warning("gdelt_query_failed", error=str(e))
        return f"GDELT query failed: {e}"
