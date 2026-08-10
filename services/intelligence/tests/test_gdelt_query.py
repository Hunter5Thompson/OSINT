"""Tests for gdelt_query tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.tools.gdelt_query import gdelt_query
from spatial import ScopeKind, SpatialScopeTokenV1
from tests.tool_runtime import agent_state, invoke_runtime_tool


class _DummyAsyncClient:
    def __init__(self, response: MagicMock):
        self._response = response

    async def __aenter__(self) -> _DummyAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self._response


def _scope_token() -> SpatialScopeTokenV1:
    revision = "spatial-derive-v1-d30efa07e141"
    return SpatialScopeTokenV1(
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision=revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(revision,),
    )


class TestGdeltQueryTool:
    @pytest.mark.asyncio
    async def test_returns_friendly_message_on_non_json_response(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        response.headers = {"content-type": "text/html"}
        response.text = "<html>temporarily unavailable</html>"

        with patch(
            "agents.tools.gdelt_query.httpx.AsyncClient",
            return_value=_DummyAsyncClient(response),
        ):
            result = await invoke_runtime_tool(
                gdelt_query,
                {"query": "strait of hormuz", "max_records": 5},
            )

        assert "temporarily unavailable" in result.lower()
        assert "expecting value" not in result.lower()

    @pytest.mark.asyncio
    async def test_formats_article_list_when_json_is_valid(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "articles": [
                {
                    "title": "Shipping disruption reported",
                    "url": "https://example.test/a",
                    "domain": "example.test",
                    "seendate": "20260423",
                    "language": "English",
                }
            ]
        }
        response.headers = {"content-type": "application/json"}
        response.text = ""

        with patch(
            "agents.tools.gdelt_query.httpx.AsyncClient",
            return_value=_DummyAsyncClient(response),
        ):
            result = await invoke_runtime_tool(
                gdelt_query,
                {"query": "strait of hormuz", "max_records": 5},
            )

        assert "[GDELT Evidence for: strait of hormuz]" in result
        from rag.evidence import parse_evidence_refs
        refs = parse_evidence_refs(result)
        assert len(refs) == 1
        assert refs[0].provider == "example.test"

    @pytest.mark.asyncio
    async def test_emits_evidence_blocks_seendate_not_published(self):
        from rag.evidence import parse_evidence_refs
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"articles": [{
            "title": "Shipping disruption",
            "url": "https://reuters.com/a",
            "domain": "reuters.com",
            "seendate": "20260423T120000Z",
            "language": "English",
        }]}
        response.headers = {"content-type": "application/json"}
        response.text = ""
        with patch(
            "agents.tools.gdelt_query.httpx.AsyncClient",
            return_value=_DummyAsyncClient(response),
        ):
            out = await invoke_runtime_tool(
                gdelt_query,
                {"query": "hormuz", "max_records": 5},
            )
        refs = parse_evidence_refs(out)
        assert len(refs) == 1
        assert refs[0].source_type == "gdelt"
        assert refs[0].provider == "reuters.com"
        assert refs[0].published_at is None  # seendate is an observation, not publication

    @pytest.mark.asyncio
    async def test_scoped_direct_call_is_blocked_before_http(self):
        with patch(
            "agents.tools.gdelt_query.httpx.AsyncClient",
            side_effect=AssertionError("HTTP must not be constructed"),
        ):
            out = await invoke_runtime_tool(
                gdelt_query,
                {"query": "hormuz", "max_records": 5},
                state=agent_state(spatial_scope=_scope_token()),
            )

        assert out.startswith("SPATIAL_SCOPE_UNSUPPORTED")

    @pytest.mark.asyncio
    async def test_external_endpoint_comes_from_settings(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"articles": []}
        response.headers = {"content-type": "application/json"}
        response.text = ""
        client = _DummyAsyncClient(response)
        client.get = MagicMock(side_effect=client.get)

        with (
            patch(
                "agents.tools.gdelt_query.httpx.AsyncClient",
                return_value=client,
            ),
            patch(
                "agents.tools.gdelt_query.settings.gdelt_api_url",
                "https://gdelt.example.test/doc",
            ),
        ):
            await invoke_runtime_tool(
                gdelt_query,
                {"query": "hormuz", "max_records": 5},
            )

        assert client.get.call_args.args[0] == "https://gdelt.example.test/doc"
