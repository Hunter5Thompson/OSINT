"""Web search tool for OSINT agent."""

from langchain_core.tools import tool


@tool
def web_search(query: str) -> str:
    """Search the web for information related to a query.

    Args:
        query: The search query string.

    Returns:
        Search results as formatted text.
    """
    # Placeholder - replace with actual search API (SearXNG, Brave, etc.)
    return (
        f"[Web Search Results for: {query}]\n"
        "Note: Web search is not yet connected. "
        "Connect a search API (SearXNG, Brave Search, etc.) for live results.\n"
        "Using available RAG knowledge base and GDELT data instead."
    )
