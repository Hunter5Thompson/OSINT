"""Mandatory research stage and serialization of the run-scoped result."""

from langgraph.runtime import Runtime

from graph.state import AgentState
from rag.current import ResearchContext, ResearchResult
from rag.evidence import pack_with_lineage


def research_update(result: ResearchResult) -> dict:
    pack, artifact = pack_with_lineage(result.evidence, budget=13000, preserve_order=True)
    consumed = {item.get("evidence_id") for item in artifact}
    coverage = result.coverage.model_copy(deep=True)
    coverage.current_evidence_ids = [i for i in coverage.current_evidence_ids if i in consumed]
    if not coverage.current_evidence_ids and coverage.situation == "evidence_available":
        coverage.situation = "insufficient_evidence"
        coverage.gaps.append("prompt_budget")
        coverage.status = "partial"
    return {
        "current_evidence_pack": pack,
        "current_evidence_artifact": artifact,
        "research_coverage": coverage.model_dump(mode="json"),
    }


async def current_research_node(state: AgentState, runtime: Runtime[ResearchContext]) -> dict:
    context = runtime.context
    if context is None or context.research is None:
        return {}
    result = await context.research.search(context.public_question)
    return {
        **research_update(result),
        "agent_chain": state.get("agent_chain", []) + ["current_research"],
    }
