from unittest.mock import AsyncMock, patch

import pytest

from feeds._fulltext_fetch import clean_body, fetch_fulltext, is_quality, route_kind


class TestRoutingAndGate:
    def test_route_pdf_vs_html(self):
        assert route_kind("https://x.org/report.pdf") == "pdf"
        assert route_kind("https://x.org/commentary/abc") == "html"

    def test_clean_body_strips_nav_link_lines(self):
        md = (
            "[Home](/) [About](/about)\n"
            "This is a substantial analytical paragraph that comfortably clears"
            " the eighty character minimum for real prose.\n"
            "Here is a second equally substantial paragraph, also well beyond"
            " the eighty character threshold for counting.\n"
        )
        cleaned, paras = clean_body(md)
        assert "Home" not in cleaned and "About" not in cleaned
        assert paras == 2

    def test_quality_gate_rejects_short_or_few_paragraphs(self):
        assert is_quality("x" * 5000, paragraphs=5, min_chars=1500, min_paras=3) is True
        assert is_quality("x" * 500, paragraphs=5, min_chars=1500, min_paras=3) is False
        assert is_quality("x" * 5000, paragraphs=1, min_chars=1500, min_paras=3) is False

    def test_real_crawl4ai_fixture_passes_default_gate(self):
        import json
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "fulltext" / "crawl4ai_md.json"
        md = json.loads(fixture.read_text())["markdown"]
        cleaned, paras = clean_body(md)
        assert paras >= 3                       # real article, single-\n separated
        assert is_quality(cleaned, paragraphs=paras, min_chars=1500, min_paras=3) is True

    def test_real_docling_fixture_passes_default_gate(self):
        import json
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "fulltext" / "docling_convert.json"
        doc = json.loads(fixture.read_text())["document"]["md_content"]
        cleaned, paras = clean_body(doc)
        assert paras >= 3
        assert is_quality(cleaned, paragraphs=paras, min_chars=1500, min_paras=3) is True


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_html_uses_crawl4ai_fit(self):
        captured = {}

        async def fake_post(url, json=None):
            captured["url"] = url
            captured["json"] = json
            from httpx import Request, Response
            content = "## Title\n\n" + "Real analysis paragraph. " * 200 + "\n\nP2 " * 50
            body = {"markdown": content, "success": True}
            return Response(200, json=body, request=Request("POST", url))

        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=fake_post)):
            md = await fetch_fulltext("https://csis.org/analysis/x",
                                      crawl4ai_url="http://c:11235", docling_url="http://d:5001",
                                      min_chars=100, min_paras=1)
        assert captured["url"].endswith("/md")
        assert captured["json"]["f"] == "fit"           # fit filter requested
        assert md and "Real analysis paragraph" in md

    @pytest.mark.asyncio
    async def test_fetch_returns_none_on_paywall_short(self):
        async def fake_post(url, json=None):
            from httpx import Request, Response
            body = {"markdown": "[Subscribe](/join)\n\nJoin now.", "success": True}
            return Response(200, json=body, request=Request("POST", url))
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=fake_post)):
            md = await fetch_fulltext("https://csis.org/x", crawl4ai_url="http://c", docling_url="http://d",
                                      min_chars=1500, min_paras=3)
        assert md is None

    @pytest.mark.asyncio
    async def test_fetch_pdf_uses_docling_v1_source_shape(self):
        captured = {}

        async def fake_post(url, json=None):
            captured["url"] = url
            captured["json"] = json
            from httpx import Request, Response
            pdf_content = "## Report\n\n" + "Substantive PDF analysis paragraph. " * 200
            body = {"document": {"md_content": pdf_content}, "status": "success", "errors": []}
            return Response(200, json=body, request=Request("POST", url))

        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=fake_post)):
            md = await fetch_fulltext("https://rand.org/pubs/report.pdf",
                                      crawl4ai_url="http://c:11235", docling_url="http://d:5001",
                                      min_chars=100, min_paras=1)
        assert captured["url"].endswith("/v1/convert/source")          # corrected path (SHAPES.md)
        assert captured["json"]["sources"] == [{"kind": "http", "url": "https://rand.org/pubs/report.pdf"}]
        assert captured["json"]["options"]["to_formats"] == ["md"]
        assert md and "Substantive PDF analysis paragraph" in md
