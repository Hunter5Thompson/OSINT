"""Legacy pipeline must not advertise llm_knowledge as a source."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from graph.nodes import osint_node


@pytest.mark.asyncio
async def test_osint_node_sources_used_is_empty():
    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(return_value=type("R", (), {"content": "analysis"})())
    with patch("graph.nodes.create_osint_llm", return_value=fake_llm):
        out = await osint_node({
            "query": "q", "agent_chain": [], "iteration": 0,
        })
    assert out["sources_used"] == []


@pytest.mark.asyncio
async def test_legacy_osint_node_seeds_grounding(monkeypatch):
    from langchain_core.messages import AIMessage

    import graph.nodes as nodes
    captured = {}

    class FakeLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="ok")

    monkeypatch.setattr(nodes, "create_osint_llm", lambda: FakeLLM())
    state = {
        "query": "Lage Iran",
        "grounding_context": "<<<GROUNDING_DATA\nfakten\n>>>END_GROUNDING_DATA",
        "agent_chain": [],
        "iteration": 0,
        "messages": [],
    }
    await nodes.osint_node(state)
    human = [m for m in captured["messages"] if getattr(m, "type", "") == "human"][0]
    assert "GROUNDING_DATA" in human.content  # grounding reaches the legacy osint prompt


@pytest.mark.asyncio
async def test_legacy_osint_node_no_grounding_is_noop(monkeypatch):
    from langchain_core.messages import AIMessage

    import graph.nodes as nodes
    captured = {}

    class FakeLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="ok")

    monkeypatch.setattr(nodes, "create_osint_llm", lambda: FakeLLM())
    state = {"query": "Lage Iran", "agent_chain": [], "iteration": 0, "messages": []}
    await nodes.osint_node(state)
    human = [m for m in captured["messages"] if getattr(m, "type", "") == "human"][0]
    assert "GROUNDING_DATA" not in human.content  # empty grounding → no block appended
