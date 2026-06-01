"""GDELT event database query tool."""

import httpx
import structlog
from langchain_core.tools import tool

from rag.evidence import format_evidence_pack, to_evidence_item

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
        A budgeted evidence pack: one `[EVIDENCE] {json}` metadata line per
        article (provider = source domain, source_type = gdelt, url, ...) followed
        by Title/Excerpt lines. Ordered newest-first. Note: GDELT seendate is an
        observation timestamp, so published_at is intentionally null.
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

        items = [
            to_evidence_item({
                "score": 1.0 - idx * 0.001,  # preserve newest-first ordering
                "source_type": "gdelt",
                "provider": article.get("domain", "gdelt"),
                "title": article.get("title", "No title"),
                "content": article.get("title", ""),
                "url": article.get("url", ""),
                # seendate is GDELT observation metadata — deliberately NOT published_at
            })
            for idx, article in enumerate(articles[:max_records])
        ]
        pack = format_evidence_pack(items, budget=6500)
        return f"[GDELT Evidence for: {query}]\n{pack}"
    except Exception as e:
        logger.warning("gdelt_query_failed", error=str(e))
        return f"GDELT query failed: {e}"
