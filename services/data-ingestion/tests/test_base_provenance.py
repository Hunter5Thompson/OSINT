from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.base import BaseCollector


class _Concrete(BaseCollector):
    async def collect(self) -> None:  # pragma: no cover
        ...


@pytest.fixture
def collector():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    with patch("feeds.base.QdrantClient", return_value=MagicMock()):
        c = _Concrete(settings=s)
    c._embed = AsyncMock(return_value=[0.0] * 1024)
    return c


@pytest.mark.asyncio
async def test_build_point_stamps_dataset_provenance(collector):
    point = await collector._build_point("text", {"source": "usgs"}, "abc123")
    assert point.payload["source_type"] == "dataset"
    assert point.payload["provider"] == "usgs.gov"
    assert "ingested_at" in point.payload
    # credibility is NOT written on the write path
    assert "credibility_score" not in point.payload


@pytest.mark.asyncio
async def test_build_point_unknown_source_raises(collector):
    with pytest.raises(KeyError):
        await collector._build_point("text", {"source": "mystery"}, "abc123")
