"""Live test — touches the real GDELT CDN. Run with `pytest -m live`."""

from __future__ import annotations

import pytest

from gdelt_raw.downloader import fetch_lastupdate

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_gdelt_lastupdate_endpoint():
    entries = await fetch_lastupdate()
    assert len(entries) == 3
    streams = {e.stream for e in entries}
    assert streams == {"events", "mentions", "gkg"}
    # Slice_id is YYYYMMDDHHMMSS
    for e in entries:
        assert len(e.slice_id) == 14
        assert e.md5  # MD5 present
