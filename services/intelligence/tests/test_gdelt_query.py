"""Tests for gdelt_query tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.tools.gdelt_query import gdelt_query


class _DummyAsyncClient:
    def __init__(self, response: MagicMock):
        self._response = response

    async def __aenter__(self) -> "_DummyAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self._response


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
            result = await gdelt_query.ainvoke({"query": "strait of hormuz", "max_records": 5})

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
            result = await gdelt_query.ainvoke({"query": "strait of hormuz", "max_records": 5})

        assert "[GDELT Results for: strait of hormuz]" in result
        assert "Shipping disruption reported" in result
