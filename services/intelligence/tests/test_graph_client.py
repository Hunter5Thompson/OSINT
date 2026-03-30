"""Tests for the async Neo4j client wrapper. Uses mock driver."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from graph.client import GraphClient


def _async_iter(items):
    """Return an object that supports the async iterator protocol over *items*."""

    class _AsyncIter:
        def __init__(self):
            self._it = iter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

    return _AsyncIter()


@pytest.fixture
def mock_driver():
    driver = AsyncMock()
    session = AsyncMock()
    # driver.session must be a regular MagicMock so calling it returns return_value
    # (not a coroutine), enabling the async context manager protocol.
    driver.session = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return driver, session


class TestGraphClientRunQuery:
    async def test_write_query_uses_default_session(self, mock_driver):
        driver, session = mock_driver
        record = MagicMock()
        record.__iter__ = MagicMock(return_value=iter([("id", "abc123")]))
        record.keys.return_value = ["id"]
        record.__getitem__ = lambda self, key: "abc123"
        result_mock = _async_iter([record])
        session.run.return_value = result_mock

        with patch("graph.client.AsyncGraphDatabase") as mock_agd:
            mock_agd.driver.return_value = driver
            client = GraphClient("bolt://localhost:7687", "neo4j", "pass")
            await client.run_query("CREATE (n) RETURN n")
            session.run.assert_called_once()

    async def test_read_only_sets_access_mode(self, mock_driver):
        driver, session = mock_driver
        result_mock = _async_iter([])
        session.run.return_value = result_mock

        with patch("graph.client.AsyncGraphDatabase") as mock_agd:
            mock_agd.driver.return_value = driver
            client = GraphClient("bolt://localhost:7687", "neo4j", "pass")
            await client.run_query("MATCH (n) RETURN n", read_only=True)

            call_kwargs = driver.session.call_args
            assert call_kwargs is not None
            kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
            assert "default_access_mode" in kwargs


class TestGraphClientClose:
    async def test_close_closes_driver(self):
        with patch("graph.client.AsyncGraphDatabase") as mock_agd:
            driver = AsyncMock()
            mock_agd.driver.return_value = driver
            client = GraphClient("bolt://localhost:7687", "neo4j", "pass")
            await client.close()
            driver.close.assert_called_once()
