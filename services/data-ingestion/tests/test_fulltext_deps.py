"""Dependency gate for the in-container fulltext job (TASK-113).

A down crawl4ai/docling/TEI turns every selected teaser into a _mark_retry;
after fulltext_max_attempts runs the backlog is failed_permanent. The job
must therefore skip the whole run while any fetch/embed dependency is down,
like the host bridge's health gate did."""

import httpx
import pytest

from feeds.fulltext_collector import unavailable_dependencies


def _transport(down: set[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in down:
            raise httpx.ConnectError("refused", request=request)
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _urls(monkeypatch):
    monkeypatch.setattr("config.settings.crawl4ai_url", "http://crawl4ai:11235")
    monkeypatch.setattr("config.settings.docling_url", "http://docling:5001")
    monkeypatch.setattr("config.settings.tei_embed_url", "http://tei-embed:80")


@pytest.mark.asyncio
async def test_all_dependencies_up():
    assert await unavailable_dependencies(transport=_transport(set())) == []


@pytest.mark.asyncio
async def test_reports_each_down_dependency():
    down = await unavailable_dependencies(transport=_transport({"crawl4ai", "tei-embed"}))
    assert down == ["crawl4ai", "tei"]


@pytest.mark.asyncio
async def test_unhealthy_status_counts_as_down():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503 if request.url.host == "docling" else 200)
    down = await unavailable_dependencies(transport=httpx.MockTransport(handler))
    assert down == ["docling"]
