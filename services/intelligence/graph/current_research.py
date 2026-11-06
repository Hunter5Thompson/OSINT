"""Mandatory research stage and serialization of the run-scoped result."""

from datetime import datetime

from langgraph.runtime import Runtime

from graph.state import AgentState
from rag.current import ResearchContext, ResearchResult
from rag.evidence import EvidenceItem, eligible_current_evidence, pack_with_lineage


def research_update(result: ResearchResult) -> dict:
    current_ids = set(result.coverage.current_evidence_ids)
    ordered = sorted(result.evidence, key=lambda item: item.evidence_id not in current_ids)
    pack, artifact = pack_with_lineage(ordered, budget=13000, preserve_order=True)
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


def reconcile_coverage(coverage: dict, items: list[EvidenceItem]) -> dict:
    """Apply the same gate to actual consumed backend, baseline and tool evidence."""
    result = dict(coverage)
    since = datetime.fromisoformat(coverage["published_since"].replace("Z", "+00:00"))
    as_of = datetime.fromisoformat(coverage["as_of"].replace("Z", "+00:00"))
    result["current_evidence_ids"] = [
        item.evidence_id
        for item in items
        if item.evidence_id and eligible_current_evidence(item, since, as_of)
    ]
    if result["current_evidence_ids"] and "spatial_occurrence_unproven" not in coverage["gaps"]:
        result["situation"] = "evidence_available"
        if result["status"] == "unavailable":
            result["status"] = "partial"
    return result
