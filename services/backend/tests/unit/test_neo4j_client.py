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
async def test_read_queries_share_one_managed_read_transaction() -> None:
    transaction = MagicMock()
    transaction.run = AsyncMock(side_effect=[
        _async_iter([{"id": "event-1"}]),
        _async_iter([{"candidate_count": 1}]),
    ])
    mock_session = MagicMock()

    async def execute_read(callback):
        return await callback(transaction)

    mock_session.execute_read = AsyncMock(side_effect=execute_read)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)

    queries = (
        ("MATCH (ev:Event) RETURN ev.id AS id", {"scope_key": "country:UKR"}),
        ("MATCH (ev:Event) RETURN count(ev) AS candidate_count", {}),
    )
    with patch.object(nc, "get_graph_client", AsyncMock(return_value=mock_driver)):
        result_sets = await nc.read_queries(queries)

    assert result_sets == [[{"id": "event-1"}], [{"candidate_count": 1}]]
    mock_session.execute_read.assert_awaited_once()
    assert transaction.run.await_args_list[0].args == queries[0]
    assert transaction.run.await_args_list[1].args == queries[1]
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


@pytest.mark.asyncio
async def test_close_driver_releases_and_resets_singleton() -> None:
    driver = MagicMock(close=AsyncMock())
    nc._driver = driver

    await nc.close_driver()

    driver.close.assert_awaited_once()
    assert nc._driver is None
