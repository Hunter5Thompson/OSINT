"""Tests for the gated fulltext scheduler job (FULLTEXT_ENABLED opt-in)."""

from unittest.mock import AsyncMock, patch

import pytest


class TestFulltextJob:
    @pytest.mark.asyncio
    async def test_disabled_is_noop(self, monkeypatch):
        monkeypatch.setattr("config.settings.fulltext_enabled", False, raising=False)
        from scheduler import run_fulltext_collector
        with patch("scheduler.FulltextCollector") as mock_coll:
            await run_fulltext_collector()
        mock_coll.assert_not_called()              # opt-in OFF → never constructs/crawls

    @pytest.mark.asyncio
    async def test_enabled_runs_collect_off_loop(self, monkeypatch):
        monkeypatch.setattr("config.settings.fulltext_enabled", True, raising=False)
        from scheduler import run_fulltext_collector
        inst = AsyncMock()
        with patch("scheduler.unavailable_dependencies", AsyncMock(return_value=[])), \
             patch("scheduler._construct_off_loop", AsyncMock(return_value=inst)) as col, \
             patch("scheduler.FulltextCollector") as mock_fc:
            await run_fulltext_collector()
        # constructed OFF-LOOP (matches other collectors)
        col.assert_awaited_once_with(mock_fc)
        inst.collect.assert_awaited_once()
        inst.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enabled_skips_run_while_dependency_down(self, monkeypatch):
        """No select/mark while crawl4ai/docling/TEI is down — otherwise every
        teaser in the batch burns a retry attempt towards failed_permanent."""
        monkeypatch.setattr("config.settings.fulltext_enabled", True, raising=False)
        from scheduler import run_fulltext_collector
        with patch("scheduler.unavailable_dependencies",
                   AsyncMock(return_value=["crawl4ai"])), \
             patch("scheduler._construct_off_loop", AsyncMock()) as col:
            await run_fulltext_collector()
        col.assert_not_awaited()
