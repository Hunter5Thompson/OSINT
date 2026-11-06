"""Focused public follow-ups; archive text cannot become an outbound search query."""

from typing import Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from graph.current_research import research_update
from rag.current import ResearchContext


@tool
async def current_search(
    focus: Literal["latest", "official", "counterevidence"],
    runtime: ToolRuntime[ResearchContext],
) -> Command:
    """Read more current public sources about the user's original question.

    Choose latest developments, official statements, or counterevidence. Time,
    scope and budgets stay fixed. Results are unverified topic context and do not
    establish spatial occurrence. Historical-only runs cannot use this tool.
    """
    context = runtime.context
    if context is None or context.research is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="CURRENT_RESEARCH_NOT_REQUESTED",
                        tool_call_id=runtime.tool_call_id,
                        name="current_search",
                    )
                ]
            }
        )
    suffix = {
        "latest": " latest developments",
        "official": " official statements evidence",
        "counterevidence": " denials contrary evidence de-escalation",
    }[focus]
    result = await context.research.search(context.public_question + suffix)
    update = research_update(result)
    update["messages"] = [
        ToolMessage(
            content=update["current_evidence_pack"] or result.coverage.model_dump_json(),
            artifact=update["current_evidence_artifact"],
            tool_call_id=runtime.tool_call_id,
            name="current_search",
        )
    ]
    return Command(update=update)
