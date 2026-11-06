import json
from unittest.mock import AsyncMock

from agents.tools.graph_query import _match_intent, query_knowledge_graph
from agents.tools.graph_templates import select_template
from tests.test_reviewed_evidence_contract import PAYLOADS
from tests.tool_runtime import agent_state, invoke_runtime_tool_message


def test_reviewed_claim_intent_has_parameter_bound_template():
    template, params = _match_intent('reviewed claims about "RUSI"')
    assert template == "reviewed_claims"
    cypher, bound = select_template(template, params)
    assert "EXTRACTED_FROM" in cypher and "qualification_json" in cypher
    assert "$name" in cypher and "RUSI" not in cypher
    assert bound["name"] == "RUSI"


async def test_claim_read_preserves_review_artifact(monkeypatch):
    import agents.tools.graph_query as module

    p = next(p for p in PAYLOADS if p["review"]["claim_id"] == "C060")
    client = AsyncMock()
    client.run_query.return_value = [
        {
            "statement": p["content"],
            "title": p["title"],
            "notebook_id": p["notebook_id"],
            "source_id": p["source_id"],
            "source_kind": p["source_kind"],
            "claim_hash": p["claim_hash"],
            "qualification_json": json.dumps(p["review"]),
        }
    ]
    monkeypatch.setattr(module, "_graph_client", client)
    msg = await invoke_runtime_tool_message(
        query_knowledge_graph, {"question": 'reviewed claims about "RUSI"'}
    )
    assert msg.artifact[0]["review"]["qualification_note"] == p["review"]["qualification_note"]
    assert msg.artifact[0]["review"]["evidence"][0]["independent_lineage"] == "RUSI_field_research"
    assert client.run_query.call_args.kwargs["read_only"] is True


async def test_claim_template_cannot_escape_non_global_scope(monkeypatch):
    import agents.tools.graph_query as module
    from tests.test_workflow import _token

    client = AsyncMock()
    monkeypatch.setattr(module, "_graph_client", client)
    msg = await invoke_runtime_tool_message(
        query_knowledge_graph,
        {"question": 'reviewed claims about "RUSI"'},
        state=agent_state(spatial_scope=_token("country:UKR", "d30efa07e141")),
    )
    client.run_query.assert_not_awaited()
    assert not msg.artifact
    assert "SPATIAL_SCOPE_UNSUPPORTED" in msg.content
