from types import SimpleNamespace
from unittest.mock import AsyncMock


class TestEnsureIndexes:
    def _client(self, existing):
        c = SimpleNamespace()
        c.get_collection = AsyncMock(
            return_value=SimpleNamespace(payload_schema={k: object() for k in existing})
        )
        c.create_payload_index = AsyncMock()
        return c

    async def test_creates_only_missing_with_wait(self):
        from scripts.ensure_payload_indexes import ensure_indexes

        client = self._client(existing={"source"})
        created = await ensure_indexes(client=client, collection="odin_intel")

        assert set(created) == {"telegram_channel", "notebook_id"}
        for call in client.create_payload_index.await_args_list:
            assert call.kwargs["wait"] is True
            assert call.kwargs["field_schema"] == "keyword"

    async def test_idempotent_second_run_noop(self):
        from scripts.ensure_payload_indexes import ensure_indexes

        client = self._client(existing={"source", "telegram_channel", "notebook_id"})
        created = await ensure_indexes(client=client, collection="odin_intel")

        assert created == []
        client.create_payload_index.assert_not_awaited()

    async def test_none_payload_schema_creates_all(self):
        from rag.qdrant_schema import REQUIRED_PAYLOAD_INDEXES
        from scripts.ensure_payload_indexes import ensure_indexes

        client = SimpleNamespace(
            get_collection=AsyncMock(return_value=SimpleNamespace(payload_schema=None)),
            create_payload_index=AsyncMock(),
        )
        created = await ensure_indexes(client=client, collection="odin_intel")
        assert set(created) == set(REQUIRED_PAYLOAD_INDEXES)   # fresh collection -> all created
        assert client.create_payload_index.await_count == len(REQUIRED_PAYLOAD_INDEXES)
