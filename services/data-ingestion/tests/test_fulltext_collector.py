from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from feeds.fulltext_collector import FulltextCollector

TERMINAL = {"done", "failed_permanent", "skipped_paywall"}


def _teaser(rid, url="https://csis.org/a", feed="CSIS"):
    return SimpleNamespace(id=rid, payload={
        "source": "rss", "feed_name": feed, "url": url, "title": "T",
        "published_at": "2026-01-01", "published": "2026-01-01",
        "entities": [{"name": "X"}],
    })


def _collector(scroll_points):
    qc = MagicMock()
    qc.scroll.return_value = (scroll_points, None)
    qc.upsert = MagicMock()
    qc.set_payload = MagicMock()
    c = FulltextCollector(qdrant=qc)
    c._embed = AsyncMock(return_value=[0.0] * 1024)        # type: ignore[method-assign]
    c._ensure_collection_ready = MagicMock()               # bypass schema preflight
    return c, qc


class TestCollect:
    @pytest.mark.asyncio
    async def test_success_writes_chunks_then_supersedes_by_record_id(self):
        c, qc = _collector([_teaser(rid=111)])
        with patch("feeds.fulltext_collector.fetch_fulltext",
                   AsyncMock(return_value="## H\n\n" + "Real analysis. " * 300)):
            await c.collect()
        # (1) chunks upserted, (2) THEN supersede on the scrolled record.id
        assert qc.upsert.called
        sp = qc.set_payload.call_args
        assert sp.kwargs["points"] == [111]                # record.id, NOT url
        assert sp.kwargs["payload"]["superseded_by_fulltext"] is True
        assert sp.kwargs["payload"]["fulltext_status"] == "done"

    @pytest.mark.asyncio
    async def test_quality_skip_marks_skipped_paywall_no_chunks(self):
        c, qc = _collector([_teaser(rid=222)])
        with patch("feeds.fulltext_collector.fetch_fulltext", AsyncMock(return_value=None)):
            await c.collect()
        qc.upsert.assert_not_called()
        sp = qc.set_payload.call_args
        assert sp.kwargs["points"] == [222]
        assert sp.kwargs["payload"]["fulltext_status"] == "skipped_paywall"
        assert "superseded_by_fulltext" not in sp.kwargs["payload"]

    @pytest.mark.asyncio
    async def test_transient_error_marks_retry_with_backoff(self):
        c, qc = _collector([_teaser(rid=333)])
        import httpx
        with patch("feeds.fulltext_collector.fetch_fulltext",
                   AsyncMock(side_effect=httpx.ConnectError("down"))):
            await c.collect()
        qc.upsert.assert_not_called()
        pl = qc.set_payload.call_args.kwargs["payload"]
        assert pl["fulltext_status"] == "retry"
        assert pl["fulltext_attempts"] == 1
        assert pl["fulltext_retry_epoch"] > 0

    @pytest.mark.asyncio
    async def test_throttles_same_domain(self):
        c, qc = _collector([_teaser(rid=1, url="https://csis.org/a"),
                            _teaser(rid=2, url="https://csis.org/b")])
        sleeps: list[float] = []
        with patch("feeds.fulltext_collector.fetch_fulltext", AsyncMock(return_value=None)), \
             patch("feeds.fulltext_collector.asyncio.sleep",
                   AsyncMock(side_effect=lambda s: sleeps.append(s))):
            await c.collect()
        assert any(s > 0 for s in sleeps)            # 2nd csis.org URL was throttled

    @pytest.mark.asyncio
    async def test_embed_failure_routes_retry_and_continues_batch(self):
        c, qc = _collector([_teaser(rid=1, url="https://csis.org/a"),
                            _teaser(rid=2, url="https://csis.org/b")])
        c._embed = AsyncMock(side_effect=httpx.ConnectError("tei down"))  # type: ignore[method-assign]
        with patch("feeds.fulltext_collector.fetch_fulltext",
                   AsyncMock(return_value="## H\n\n" + "Real analysis. " * 300)), \
             patch("feeds.fulltext_collector.asyncio.sleep", AsyncMock()):
            await c.collect()
        qc.upsert.assert_not_called()                       # embed failed before any upsert
        marked = [call.kwargs["points"][0] for call in qc.set_payload.call_args_list]
        assert marked == [1, 2]                             # both attempted; batch NOT aborted
        assert all(call.kwargs["payload"]["fulltext_status"] == "retry"
                   for call in qc.set_payload.call_args_list)

    @pytest.mark.asyncio
    async def test_retry_becomes_failed_permanent_at_max_attempts(self):
        t = _teaser(rid=5)
        t.payload["fulltext_attempts"] = 3                  # default fulltext_max_attempts == 4
        c, qc = _collector([t])
        with patch("feeds.fulltext_collector.fetch_fulltext",
                   AsyncMock(side_effect=httpx.ConnectError("down"))):
            await c.collect()
        pl = qc.set_payload.call_args.kwargs["payload"]
        assert pl["fulltext_attempts"] == 4
        assert pl["fulltext_status"] == "failed_permanent"


class TestServerSideBackoff:
    @pytest.mark.asyncio
    async def test_select_excludes_future_backoff_server_side(self):
        """Backoff predicate must be in the Qdrant scroll filter (must_not Range gt),
        not applied as a Python post-filter.  A page of future-backoff records must
        never consume batch slots and starve due/new records."""
        c, qc = _collector([])   # scroll returns []; we only care about the filter shape
        with patch("feeds.fulltext_collector.fetch_fulltext", AsyncMock(return_value=None)):
            await c.collect()
        flt = qc.scroll.call_args.kwargs["scroll_filter"]
        # must_not must contain a FieldCondition on fulltext_retry_epoch with a Range(gt=...)
        ranges = [
            cond.range
            for cond in flt.must_not
            if getattr(cond, "key", None) == "fulltext_retry_epoch"
        ]
        assert ranges, "No must_not condition on fulltext_retry_epoch found in scroll filter"
        assert ranges[0] is not None, "fulltext_retry_epoch must_not condition has no range"
        assert ranges[0].gt is not None, "Range.gt must be set (future-backoff predicate)"


class TestPreflight:
    @pytest.mark.asyncio
    async def test_invalid_schema_prevents_upsert(self):
        from qdrant_doctor.schema import QdrantSchemaMismatch
        qc = MagicMock()
        qc.scroll.return_value = ([_teaser(rid=9)], None)
        qc.get_collections.return_value = SimpleNamespace(
            collections=[SimpleNamespace(name="odin_intel")])
        c = FulltextCollector(qdrant=qc)
        c._embed = AsyncMock(return_value=[0.0] * 1024)   # type: ignore[method-assign]
        with patch("feeds.fulltext_collector.validate_collection_schema",
                   side_effect=QdrantSchemaMismatch("bad")), \
             patch("feeds.fulltext_collector.fetch_fulltext", AsyncMock(return_value="x" * 9000)), \
             pytest.raises(QdrantSchemaMismatch):
            await c.collect()
        qc.upsert.assert_not_called()                 # preflight aborts before any write
