"""Every report gets notebook context without relying on model tool selection."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

import graph.workflow as workflow
import main
from config import settings
from rag.evidence import EvidenceItem, NotebookPassage, SourceRef, pack_with_lineage
from rag.notebooks import build_catalog
from tests.test_notebook_research import digest, embed, package, query_embed


@pytest.mark.parametrize("valid_citations", [True, False])
async def test_started_report_receives_original_passages_automatically(
    tmp_path, monkeypatch, valid_citations
):
    root = package(tmp_path)
    target = tmp_path / "catalog.sqlite"
    await build_catalog({"intel": root}, target, embed=embed, embedding_model="test")
    monkeypatch.setattr(settings, "notebook_catalog_path", target, raising=False)
    monkeypatch.setattr(
        settings, "notebook_catalog_sha256", digest(target.read_bytes()), raising=False
    )
    monkeypatch.setattr(settings, "notebook_embedding_model", "test", raising=False)
    monkeypatch.setattr("rag.notebooks.embed_notebook_query", query_embed, raising=False)
    research, synthesis = AsyncMock(), AsyncMock()
    research.ainvoke.return_value = AIMessage(content="Research complete.")
    fixture = json.loads(
        (Path(__file__).parents[3] / "tests/fixtures/notebook-passage.json").read_text()
    )
    synthesis.ainvoke.return_value = AIMessage(
        content=(
            f"Report with context [{fixture['evidence_id']}].\nThreat Assessment: NOT_ASSESSED\n"
            "Confidence Level: not assessed"
            if valid_citations
            else "Unattributed report"
        )
    )
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: research)

    def grounded_model(*, original_passages):
        assert original_passages is True
        return synthesis

    monkeypatch.setattr(workflow, "create_synthesis_llm", grounded_model)
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/query",
            json={
                "query": "Assess export restrictions affecting magnets",
                "spatial_relation": "either",
            },
        )
    if not valid_citations:
        assert response.status_code == 502
        assert response.json()["code"] == "INTEL_PIPELINE_FAILED"
        return
    assert response.status_code == 200
    assert synthesis.ainvoke.await_count == 2
    prompt = "\n".join(message.content for message in synthesis.ainvoke.call_args.args[0])
    assert "permanent magnets" in prompt
    assert "unreviewed_source_excerpt" in prompt
    assert response.json()["evidence_summary"][0]["knowledge_role"] == "background"


async def test_methods_alone_cannot_become_an_event_assessment(monkeypatch):
    fixture = json.loads(
        (Path(__file__).parents[3] / "tests/fixtures/notebook-passage.json").read_text()
    )
    item = EvidenceItem(
        evidence_id=fixture["evidence_id"],
        title=fixture["title"],
        excerpt=fixture["excerpt"],
        relevance_score=1,
        knowledge_role="method",
        passage=NotebookPassage(**fixture["passage"]),
        source=SourceRef(
            source_ref_id=fixture["source_ref_id"],
            source_type="notebooklm",
            provider=fixture["provider"],
        ),
    )
    pack, artifact = pack_with_lineage([item], budget=9000)
    synthesis = AsyncMock()
    synthesis.ainvoke.return_value = AIMessage(
        content="Threat Assessment: CRITICAL\nConfidence Level: high confidence"
    )
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: synthesis)
    result = await workflow.react_synthesis_node(
        {
            "query": "Welche Angriffe ereigneten sich heute?",
            "messages": [ToolMessage(content=pack, artifact=artifact, tool_call_id="test")],
        }
    )
    assert result["threat_assessment"] is None
    assert result["answerability"] == "insufficient_evidence"
    assert result["evidence_summary"][0]["knowledge_role"] == "method"
    synthesis.ainvoke.assert_not_awaited()


async def test_missing_configured_archive_is_http_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "notebook_catalog_path", tmp_path / "missing.sqlite")
    monkeypatch.setattr(settings, "notebook_catalog_sha256", "a" * 64)
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.post("/query", json={"query": "test", "spatial_relation": "either"})
    assert response.status_code == 502
    assert response.json()["code"] == "INTEL_PIPELINE_FAILED"


async def test_health_reports_missing_required_catalog(monkeypatch, tmp_path):
    from model_readiness import ModelReadiness, ReadinessReason

    monkeypatch.setattr(settings, "notebook_catalog_path", tmp_path / "missing.sqlite")
    monkeypatch.setattr(settings, "notebook_catalog_sha256", "b" * 64)
    monkeypatch.setattr(
        main,
        "check_model_readiness",
        AsyncMock(
            return_value=ModelReadiness(
                ready=True,
                reason=ReadinessReason.READY,
                required_models=("qwen3.5",),
                missing_models=(),
            )
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["reason"] == "notebook_catalog_unavailable"


async def test_followup_search_uses_same_original_passages(tmp_path, monkeypatch):
    from agents.tools.notebook_search import notebook_search

    root = package(tmp_path)
    target = tmp_path / "catalog.sqlite"
    await build_catalog({"intel": root}, target, embed=embed, embedding_model="test")
    monkeypatch.setattr(settings, "notebook_catalog_path", target)
    monkeypatch.setattr(settings, "notebook_catalog_sha256", digest(target.read_bytes()))
    monkeypatch.setattr(settings, "notebook_embedding_model", "test")
    monkeypatch.setattr("rag.notebooks.embed_notebook_query", query_embed)
    result = await notebook_search.ainvoke(
        {
            "type": "tool_call",
            "id": "followup",
            "name": "notebook_search",
            "args": {"query": "magnets"},
        }
    )
    assert "permanent magnets" in result.content
    assert result.artifact[0]["passage"]["content_review"] == "unreviewed_source_excerpt"


def test_default_report_does_not_depend_on_legacy_gdelt_doc_api():
    from agents.react_agent import system_prompt_for_state
    from agents.tools import tools_for_state
    from tests.tool_runtime import agent_state

    state = agent_state()
    assert "gdelt_query" not in {tool.name for tool in tools_for_state(state)}
    assert "gdelt_query" not in system_prompt_for_state(state)
