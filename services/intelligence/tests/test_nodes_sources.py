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
