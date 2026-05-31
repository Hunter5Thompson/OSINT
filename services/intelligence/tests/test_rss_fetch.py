from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.tools.rss_fetch import rss_fetch
from rag.evidence import parse_evidence_refs

_FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Strike reported</title><link>https://bbc.com/news/1</link>
<pubDate>Sat, 30 May 2026 10:00:00 GMT</pubDate>
<description>Body text here</description></item>
</channel></rss>"""


class _DummyAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return self._response


@pytest.mark.asyncio
async def test_rss_fetch_emits_evidence_with_domain_provider():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.text = _FEED
    with patch(
        "agents.tools.rss_fetch.httpx.AsyncClient",
        return_value=_DummyAsyncClient(resp),
    ):
        out = await rss_fetch.ainvoke({"feed_url": "https://bbc.com/rss.xml"})
    refs = parse_evidence_refs(out)
    assert len(refs) == 1
    assert refs[0].source_type == "rss"
    assert refs[0].provider == "bbc.com"        # article link domain
    assert refs[0].published_at is not None       # pubDate IS publication time
