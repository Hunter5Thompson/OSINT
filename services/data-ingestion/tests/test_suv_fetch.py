import httpx
import pytest

from suv_structured.fetch import fetch_directory_markdown


@pytest.mark.asyncio
async def test_fetch_returns_markdown_from_md_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/md"
        body = {"markdown": "### Rheinmetall AG\n**Mitarbeiterzahl:** 34000"}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        md = await fetch_directory_markdown(
            "https://suv.report/x/", crawl4ai_url="http://c", client=client)
    assert "Rheinmetall" in md


@pytest.mark.asyncio
async def test_fetch_prefers_fit_markdown_key():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"fit_markdown": "### A", "markdown": "### B"}))
    async with httpx.AsyncClient(transport=transport) as client:
        md = await fetch_directory_markdown("u", crawl4ai_url="http://c", client=client)
    assert md == "### A"


@pytest.mark.asyncio
async def test_fetch_raises_on_empty_render():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"markdown": "   "}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await fetch_directory_markdown("u", crawl4ai_url="http://c", client=client)
