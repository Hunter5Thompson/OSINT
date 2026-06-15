from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config import settings
from pipeline import (
    Neo4jWriteError,
    _event_key,
    _normalize_event_title,
    _write_to_neo4j,
    content_hash,
)


def _resp(json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(return_value=json_body)
    return resp


def _patched_client(resp_or_exc):
    """Return a patch() context for pipeline.httpx.AsyncClient whose .post
    returns resp_or_exc (or raises it if it's an Exception)."""
    client = AsyncMock()
    if isinstance(resp_or_exc, Exception):
        client.post = AsyncMock(side_effect=resp_or_exc)
    else:
        client.post = AsyncMock(return_value=resp_or_exc)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return patch("pipeline.httpx.AsyncClient", return_value=cm)


@pytest.mark.asyncio
async def test_write_raises_on_tx_errors_array():
    """tx/commit returns HTTP 200 with a populated errors[] — must raise, not warn."""
    body = {"results": [], "errors": [{"code": "Neo.ClientError.Statement.SyntaxError"}]}
    with _patched_client(_resp(body)), pytest.raises(Neo4jWriteError):
        await _write_to_neo4j(
            [{"title": "x", "codebook_type": "other.unclassified"}], [],
            "http://u", "t", "rss", settings,
        )


@pytest.mark.asyncio
async def test_write_raises_on_http_error():
    with _patched_client(httpx.ConnectError("refused")), pytest.raises(Neo4jWriteError):
        await _write_to_neo4j(
            [{"title": "x", "codebook_type": "other.unclassified"}], [],
            "http://u", "t", "rss", settings,
        )


@pytest.mark.asyncio
async def test_write_ok_when_no_errors():
    with _patched_client(_resp({"results": [], "errors": []})):
        await _write_to_neo4j(
            [{"title": "x", "codebook_type": "other.unclassified"}], [],
            "http://u", "t", "rss", settings,
        )  # no raise


def test_content_hash_matches_collector_formula():
    # Must equal the collectors' historical _content_hash(title, url).
    import hashlib
    raw = f"{'  Title '.strip().lower()}|{'HTTP://U '.strip().lower()}"
    assert content_hash("  Title ", "HTTP://U ") == hashlib.sha256(raw.encode()).hexdigest()


def test_normalize_event_title_collapses_and_caps():
    assert _normalize_event_title("  Foo   Bar ") == "foo bar"
    assert _normalize_event_title("FOO bar") == "foo bar"
    assert len(_normalize_event_title("x" * 500)) == 200


def test_event_key_stable_across_title_whitespace_and_case():
    h = content_hash("doc", "http://u")
    k1 = _event_key(h, "conflict.armed_clash", "  Strike  on  Kyiv ")
    k2 = _event_key(h, "conflict.armed_clash", "strike on kyiv")
    assert k1 == k2
    assert len(k1) == 24


def test_event_key_differs_by_codebook_type_and_title():
    h = content_hash("doc", "http://u")
    assert _event_key(h, "a.b", "t") != _event_key(h, "c.d", "t")
    assert _event_key(h, "a.b", "t1") != _event_key(h, "a.b", "t2")
