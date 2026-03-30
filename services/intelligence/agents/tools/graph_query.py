"""graph_query tool — NL→Cypher via templates with free Cypher fallback.

Template-first: route_to_template picks a predefined query.
Fallback: LLM-generated Cypher, guarded by validate_cypher_readonly + LIMIT injection.
"""

from __future__ import annotations

import re
import time
from typing import Any

import structlog
from langchain_core.tools import tool

from agents.tools.graph_templates import (
    TEMPLATES,
    build_cypher_from_template,
    inject_limit,
    select_template,
)
from graph.read_queries import validate_cypher_readonly

log = structlog.get_logger(__name__)

# Lazy singleton — set by the workflow before agent invocation
_graph_client = None


def set_graph_client(client: Any) -> None:
    """Set the module-level GraphClient for the tool to use."""
    global _graph_client
    _graph_client = client


def route_to_template(
    template_id: str, params: dict
) -> dict | None:
    """Try to select a template. Returns routing metadata or None."""
    result = select_template(template_id, params)
    if result is None:
        return None
    cypher, merged_params = result
    return {
        "mode": "template",
        "template_id": template_id,
        "cypher": cypher,
        "params": merged_params,
    }


async def execute_graph_query(
    template_id: str | None = None,
    cypher: str | None = None,
    params: dict | None = None,
    graph_client: Any = None,
) -> str:
    """Execute a graph query via template or free Cypher.

    Args:
        template_id: If set, use this template with params.
        cypher: If set (and no template_id), use as free Cypher (validated).
        params: Query parameters.
        graph_client: Neo4j GraphClient instance. Falls back to module-level.

    Returns:
        Formatted text result for the agent.
    """
    client = graph_client or _graph_client
    if client is None:
        return "Graph database not available. Cannot query knowledge graph."

    params = params or {}
    start = time.monotonic()
    mode = "template"
    tid = template_id

    try:
        if template_id:
            query_cypher, merged_params = build_cypher_from_template(template_id, params)
        elif cypher:
            mode = "fallback"
            tid = None
            # Guard 1: readonly validation
            if not validate_cypher_readonly(cypher):
                log.warning("graph_query_rejected", cypher=cypher[:200], reason="readonly_check")
                return "Query rejected: contains write operations or unsafe patterns."
            # Guard 2: inject LIMIT if missing
            query_cypher = inject_limit(cypher)
            merged_params = params
        else:
            return "No query specified. Provide a template_id or cypher string."

        rows = await client.run_query(query_cypher, merged_params, read_only=True)
        duration_ms = int((time.monotonic() - start) * 1000)

        log.info(
            "graph_query_executed",
            mode=mode,
            template_id=tid,
            duration_ms=duration_ms,
            result_count=len(rows),
        )

        return _format_results(rows)

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.warning("graph_query_failed", mode=mode, template_id=tid, error=str(e), duration_ms=duration_ms)
        return f"Graph query failed: {e}"


def _format_results(rows: list[dict], max_rows: int = 15) -> str:
    """Format Neo4j result rows as readable text for the agent."""
    if not rows:
        return "No results found in the knowledge graph."

    truncated = rows[:max_rows]
    lines = []
    for row in truncated:
        parts = [f"{k}: {v}" for k, v in row.items() if v is not None]
        lines.append("  " + " | ".join(parts))

    result = "[Knowledge Graph Results]\n" + "\n".join(lines)
    if len(rows) > max_rows:
        result += f"\n  ... ({len(rows) - max_rows} more rows)"
    return result


@tool
async def query_knowledge_graph(question: str) -> str:
    """Query the Neo4j knowledge graph. Use for entity relationships,
    event timelines, connection networks, and co-occurrence analysis.

    Args:
        question: Natural language question about entities or events.
    """
    template_id, params = _match_intent(question)

    if template_id:
        return await execute_graph_query(template_id=template_id, params=params)
    else:
        # No template matched — fallback to LLM-generated Cypher
        return await _free_cypher_fallback(question)


def _match_intent(question: str) -> tuple[str | None, dict]:
    """Simple keyword-based intent matching. Returns (template_id, params) or (None, {})."""
    q = question.lower().strip()

    # Extract quoted entity names
    quoted = re.findall(r'"([^"]+)"', question)
    entity = quoted[0] if quoted else ""

    # If no quoted entity, try to find proper nouns (capitalized words not at start)
    if not entity:
        words = question.split()
        proper_nouns = [w for w in words[1:] if w and w[0].isupper()] if len(words) > 1 else []
        entity = " ".join(proper_nouns) if proper_nouns else ""

    if any(kw in q for kw in ("most connected", "top entities", "most important", "highest degree")):
        return "top_connected", {}

    if any(kw in q for kw in ("timeline", "events in", "events at")):
        location = entity or question.split("in ")[-1].split("at ")[-1].strip(" ?.")
        return "event_timeline", {"location": location}

    if any(kw in q for kw in ("co-occur", "appear together", "related entities", "co-occurring")):
        if entity:
            return "co_occurring", {"name": entity}

    if any(kw in q for kw in ("sources for", "evidence", "reported by", "source")):
        if entity:
            return "source_backed", {"name": entity}

    if any(kw in q for kw in ("events involving", "events about", "events for")):
        if entity:
            return "events_by_entity", {"name": entity}

    if any(kw in q for kw in ("network", "2-hop", "connections around")):
        if entity:
            return "two_hop_network", {"name": entity}

    if any(kw in q for kw in ("connected to", "related to", "neighbors of", "linked to")):
        if entity:
            return "one_hop", {"name": entity}

    if any(kw in q for kw in ("who is", "what is", "find entity", "look up")):
        if entity:
            return "entity_lookup", {"name": entity}

    # Generic entity query — if we have an entity name, try entity_lookup
    if entity:
        return "entity_lookup", {"name": entity}

    return None, {}


async def _free_cypher_fallback(question: str) -> str:
    """Generate Cypher via LLM when no template matches.

    Uses schema whitelist in prompt, validates output through all safety layers.
    """
    from graph.schema_whitelist import schema_prompt_block

    try:
        from openai import AsyncOpenAI
        from config import settings

        client = AsyncOpenAI(base_url=settings.llm_base_url, api_key="not-needed")
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": (
                    "You are a Cypher query generator for Neo4j. "
                    "Generate a single READ-ONLY Cypher query to answer the user's question.\n\n"
                    f"{schema_prompt_block()}\n\n"
                    "Return ONLY the Cypher query, no explanation."
                )},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=300,
        )
        cypher = (response.choices[0].message.content or "").strip()
        if not cypher:
            return f"Could not generate a graph query for: '{question}'."

        return await execute_graph_query(cypher=cypher, params={})

    except Exception as e:
        log.warning("free_cypher_fallback_failed", error=str(e))
        return f"Graph query generation failed: {e}"
