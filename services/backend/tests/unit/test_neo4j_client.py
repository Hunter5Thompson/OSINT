"""Tests for the extracted Neo4j read helper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import neo4j_client as nc


@pytest.mark.asyncio
async def test_read_query_uses_read_access_session() -> None:
    mock_session = MagicMock()
    mock_session.run = AsyncMock(return_value=_async_iter([{"name": "alpha"}]))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)

    with patch.object(nc, "get_graph_client", AsyncMock(return_value=mock_driver)):
        rows = await nc.read_query("MATCH (n) RETURN n", {})
        assert rows == [{"name": "alpha"}]
        mock_driver.session.assert_called_once()
        assert mock_driver.session.call_args.kwargs["default_access_mode"] == nc.neo4j.READ_ACCESS


@pytest.mark.asyncio
async def test_write_query_uses_write_access_session() -> None:
    mock_session = MagicMock()
    mock_session.run = AsyncMock(return_value=_async_iter([{"ok": 1}]))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)

    with patch.object(nc, "get_graph_client", AsyncMock(return_value=mock_driver)):
        rows = await nc.write_query("CREATE (n:Tmp) RETURN 1 AS ok", {})
        assert rows == [{"ok": 1}]
        mock_driver.session.assert_called_once()
        assert mock_driver.session.call_args.kwargs["default_access_mode"] == nc.neo4j.WRITE_ACCESS


def _async_iter(items):
    class _Result:
        def __aiter__(self):
            self._items = iter(items)
            return self

        async def __anext__(self):
            try:
                return _Record(next(self._items))
            except StopIteration:
                raise StopAsyncIteration

    return _Result()


class _Record(dict):
    pass
