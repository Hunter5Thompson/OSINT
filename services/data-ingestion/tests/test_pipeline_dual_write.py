from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config import settings
from pipeline import Neo4jWriteError, _write_to_neo4j


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
