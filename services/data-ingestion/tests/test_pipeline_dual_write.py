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
    process_item,
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


async def _captured_statements(events):
    """Run _write_to_neo4j with a mock client and return the posted statements list."""
    captured = {}
    client = AsyncMock()

    async def _post(url, json, auth):  # noqa: A002
        captured["statements"] = json["statements"]
        return _resp({"results": [], "errors": []})

    client.post = _post
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch("pipeline.httpx.AsyncClient", return_value=cm):
        await _write_to_neo4j(events, [], "http://u", "doc title", "rss", settings)
    return captured["statements"]


@pytest.mark.asyncio
async def test_event_written_with_merge_not_create():
    stmts = await _captured_statements(
        [{"title": "Strike on Kyiv", "codebook_type": "conflict.armed_clash"}]
    )
    ev_stmts = [s for s in stmts if "Event" in s["statement"]]
    assert ev_stmts, "expected an Event statement"
    assert all("MERGE (ev:Event {event_key:" in s["statement"] for s in ev_stmts)
    assert all("CREATE (ev:Event" not in s["statement"] for s in ev_stmts)
    assert all("event_key" in s["parameters"] for s in ev_stmts)


@pytest.mark.asyncio
async def test_same_event_yields_same_event_key():
    e = {"title": "Strike on Kyiv", "codebook_type": "conflict.armed_clash"}
    s1 = await _captured_statements([e])
    s2 = await _captured_statements([dict(e, title="  strike on  KYIV ")])
    k1 = next(s["parameters"]["event_key"] for s in s1 if "Event" in s["statement"])
    k2 = next(s["parameters"]["event_key"] for s in s2 if "Event" in s["statement"])
    assert k1 == k2


@pytest.mark.asyncio
async def test_write_raises_on_non_json_200_body():
    """A 200 with a non-JSON body must surface as Neo4jWriteError, not a raw decode error."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(side_effect=ValueError("Expecting value"))
    with _patched_client(resp), pytest.raises(Neo4jWriteError):
        await _write_to_neo4j(
            [{"title": "x", "codebook_type": "other.unclassified"}], [],
            "http://u", "t", "rss", settings,
        )


def _vllm_patch(events):
    return patch("pipeline._call_vllm", AsyncMock(return_value={
        "events": events, "entities": [], "locations": [],
    }))


def _failing_neo4j_patch():
    # tx/commit returns errors[] -> _write_to_neo4j raises Neo4jWriteError.
    return _patched_client(_resp({"results": [], "errors": [{"code": "X"}]}))


@pytest.mark.asyncio
async def test_process_item_swallows_by_default():
    ev = [{"title": "t", "codebook_type": "other.unclassified"}]
    with _vllm_patch(ev), _failing_neo4j_patch():
        # default raise_on_write_error=False -> no raise, returns enrichment
        result = await process_item("t", "body", "http://u", "rss", settings=settings)
    assert result is not None


@pytest.mark.asyncio
async def test_process_item_propagates_when_flag_set():
    ev = [{"title": "t", "codebook_type": "other.unclassified"}]
    with _vllm_patch(ev), _failing_neo4j_patch(), pytest.raises(Neo4jWriteError):
        await process_item(
            "t", "body", "http://u", "rss",
            settings=settings, raise_on_write_error=True,
        )


@pytest.mark.asyncio
async def test_process_item_no_redis_publish_on_write_failure():
    ev = [{"title": "t", "codebook_type": "other.unclassified"}]
    redis = AsyncMock()
    with _vllm_patch(ev), _failing_neo4j_patch(), pytest.raises(Neo4jWriteError):
        await process_item(
            "t", "body", "http://u", "rss",
            settings=settings, redis_client=redis, raise_on_write_error=True,
        )
    redis.xadd.assert_not_called()
