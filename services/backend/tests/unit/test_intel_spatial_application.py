"""Munin spatial application must survive the backend seam without relabeling."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.models.intel import RetrievalSpatialRelation
from app.models.spatial import ScopeKind, SpatialScopeTokenV1
from app.services.intel_stream import stream_intel_query


def _token(scope_key: str, revision: str) -> SpatialScopeTokenV1:
    return SpatialScopeTokenV1(
        scope_key=scope_key,
        kind=ScopeKind.COUNTRY,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision=revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(revision,),
    )


def _application(scope_key: str, revision: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "scope": {
            "schema_version": 1,
            "scope_key": scope_key,
            "catalog_revision": "spatial-v1-e76a16bff799",
            "derivation_revision": revision,
            "boundary_policy": "odin-reference-v1",
        },
        "relation": "either",
        "qdrant": {
            "status": "applied",
            "mode": "semantic-key",
            "completeness": "partial",
        },
        "neo4j": {
            "status": "not-called",
            "mode": "semantic-key",
            "completeness": "unknown",
        },
        "blocked_tools": ["gdelt_query", "rss_fetch"],
        "coverage_revision": "spatial-projection-v1-47fec701a2a2",
    }


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "agent_chain": ["react_agent", "synthesis"],
            "sources_used": [],
            "analysis": "Pinned result",
            "confidence": 0.7,
            "threat_assessment": "MODERATE",
            "tool_trace": [],
            "mode": "react",
            "timestamp": datetime.now(UTC).isoformat(),
            "spatial_application": _application(
                "country:UKR",
                "spatial-derive-v1-d30efa07e141",
            ),
        }


class _Client:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    async def post(self, _url: str, *, json: dict[str, object], timeout: float) -> _Response:
        self.payload = json
        assert timeout == 300.0
        return _Response()


@pytest.mark.asyncio
async def test_sse_preserves_run_scope_when_request_scope_has_since_changed() -> None:
    client = _Client()
    current_request = _token(
        "country:POL",
        "spatial-derive-v1-aaaaaaaaaaaa",
    )

    events = [
        event
        async for event in stream_intel_query(
            query="current situation",
            spatial_scope=current_request,
            spatial_relation=RetrievalSpatialRelation.EITHER,
            client=client,  # type: ignore[arg-type]
        )
    ]

    assert client.payload is not None
    assert client.payload["spatial_scope"] == {
        "scope_key": "country:POL",
        "catalog_revision": "spatial-v1-e76a16bff799",
    }
    result_event = next(event for event in events if event["event"] == "result")
    result = json.loads(result_event["data"])
    assert result["spatial_application"]["scope"]["scope_key"] == "country:UKR"
    assert result["spatial_application"]["scope"]["derivation_revision"] == (
        "spatial-derive-v1-d30efa07e141"
    )
