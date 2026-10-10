"""Reviewed scheduler format selection; no live jobs or provider calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import scheduler


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["tle", "omm"])
async def test_job_uses_selected_generation_and_closes_it(format_name, monkeypatch):
    legacy = SimpleNamespace(update=AsyncMock(), close=AsyncMock())
    gp = SimpleNamespace(update=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(scheduler, "TLEUpdater", Mock(return_value=legacy))
    monkeypatch.setattr(scheduler, "GPUpdater", Mock(return_value=gp), raising=False)
    monkeypatch.setattr(scheduler, "settings", SimpleNamespace(satellite_orbit_format=format_name))
    await scheduler.run_tle_updater()
    selected, other = (gp, legacy) if format_name == "omm" else (legacy, gp)
    selected.update.assert_awaited_once()
    selected.close.assert_awaited_once()
    other.update.assert_not_awaited()
