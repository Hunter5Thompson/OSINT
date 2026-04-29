"""GDELT event database query tool."""

import httpx
import structlog
from langchain_core.tools import tool

logger = structlog.get_logger()

GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


@tool
async def gdelt_query(query: str, max_records: int = 20) -> str:
    """Query GDELT DOC-API for breaking news (last 24-72h coverage window).

    GDELT covers global news in 65+ languages updated every 15 minutes —
    use this when you need ACTUAL CURRENT events that may not yet have
    been ingested into the local Qdrant knowledge base.

    Query construction tips (GDELT is keyword-based, not semantic):
    - Use 3-6 specific keywords, not full sentences
    - English usually returns more articles than other languages
    - Combine entity + action: "Russia tanker seized" beats "russian shadow fleet"
    - Avoid stop-words and very short queries (≤2 keywords often rate-limited)
    - Quote phrases for exact match: '"shadow fleet" sanctions'

    Examples that work:
    - 'Russia oil tanker sanctions Baltic'
    - 'Houthi missile Red Sea strait'
    - 'Taiwan strait military exercise'
    - 'NATO Article 5 incursion'

    Args:
        query: 3-6 specific keywords describing recent events. Quoted phrases
            allowed. Avoid generic 1-2 word queries.
        max_records: Articles to return (default 20, max 50).

    Returns:
        List of recent articles with title, source domain, publish date,
        URL — sorted newest first.
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
        logger.info(
            "gdelt_query_executed",
            query=query,
            max_records=max_records,
            result_count=len(articles),
        )
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
