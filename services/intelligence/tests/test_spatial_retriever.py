from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from qdrant_client import models


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"result": []}


class _HttpClient:
    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, _url: str, *, json: dict[str, object]):
        self.bodies.append(json)
        return _Response()


async def test_search_serializes_nested_qdrant_models_and_never_retries_unfiltered() -> None:
    from rag.retriever import search
    from spatial import combine_filters

    base = models.Filter(
        should=[
            models.FieldCondition(
                key="source",
                match=models.MatchAny(any=["rss", "rss_fulltext"]),
            )
        ],
        must_not=[
            models.FieldCondition(
                key="superseded_by_fulltext",
                match=models.MatchValue(value=True),
            )
        ],
    )
    spatial = models.Filter(
        must=[
            models.FieldCondition(
                key="spatial_occurrence_scope_revision_tokens",
                match=models.MatchAny(
                    any=[
                        "sr1|country:UKR|spatial-derive-v1-d30efa07e141"
                    ]
                ),
            ),
            models.FieldCondition(
                key="spatial_conflict",
                match=models.MatchValue(value=False),
            ),
        ]
    )
    combined = combine_filters(base, spatial)
    before = combined.model_dump(mode="json", exclude_none=True)
    client = _HttpClient()

    with (
        patch("rag.retriever._ensure_schema_validated", new=AsyncMock()),
        patch("rag.retriever.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
        patch("rag.retriever.httpx.AsyncClient", return_value=client),
    ):
        results = await search("query", query_filter=combined)

    assert results == []
    assert len(client.bodies) == 1
    assert client.bodies[0]["filter"] == before
    assert combined.model_dump(mode="json", exclude_none=True) == before


async def test_enhanced_search_propagates_coverage_snapshot_without_fallback() -> None:
    from rag.retriever import enhanced_search
    from spatial import SpatialCoverageSnapshotV1, SpatialLaneCoverageV1

    snapshot = SpatialCoverageSnapshotV1(
        target_projection_revision="spatial-projection-v1-47fec701a2a2",
        lanes=(
            SpatialLaneCoverageV1(
                lane="analysis",
                total_points=100,
                filterable_points=80,
                conflict_points=2,
                stale_points=1,
                unsupported_points=10,
                unprojected_points=5,
                audit_only_points=2,
                inconsistent_points=0,
            ),
        ),
    )
    captured: dict[str, object] = {}

    async def fake_search(_query: str, **kwargs):
        captured.update(kwargs)
        return []

    with patch("rag.retriever.search", new=AsyncMock(side_effect=fake_search)):
        results = await enhanced_search(
            "query",
            query_filter=models.Filter(),
            coverage_snapshot=snapshot,
            enable_rerank=False,
            enable_graph_context=False,
        )

    assert results == []
    assert captured["coverage_snapshot"] is snapshot


async def test_strict_search_surfaces_transport_failure_for_truthful_accounting() -> None:
    from rag.retriever import search

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, _url: str, *, json: dict[str, object]):
            raise RuntimeError("qdrant transport down")

    with (
        patch("rag.retriever._ensure_schema_validated", new=AsyncMock()),
        patch("rag.retriever.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
        patch("rag.retriever.httpx.AsyncClient", return_value=FailingClient()),
        pytest.raises(RuntimeError, match="qdrant transport down"),
    ):
        await search("query", raise_on_failure=True)
