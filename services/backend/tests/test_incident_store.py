"""Store-level tests using a fake Neo4j driver — no live DB required."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.incident import (
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.services import incident_store


def _row(**overrides):
    base = {
        "id": "inc-001",
        "kind": "firms.cluster",
        "title": "Sinjar ridge thermal cluster",
        "severity": "high",
        "lat": 36.34,
        "lon": 41.87,
        "location": "Sinjar ridge",
        "status": "open",
        "trigger_ts": "2026-04-25T10:00:00Z",
        "closed_ts": None,
        "sources": ["firms·1"],
        "layer_hints": ["firmsHotspots"],
        "timeline_json": json.dumps([{"t_offset_s": 0.0, "kind": "trigger", "text": "t0"}]),
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_incident_assigns_id_and_persists() -> None:
    with patch.object(
        incident_store,
        "write_query",
        new=AsyncMock(return_value=[_row(id="inc-007")]),
    ):
        req = IncidentCreateRequest(
            title="Sinjar ridge thermal cluster",
            kind="firms.cluster",
            severity="high",
            coords=(36.34, 41.87),
            location="Sinjar ridge",
            sources=["firms·1"],
            layer_hints=["firmsHotspots"],
        )
        record = await incident_store.create_incident(req)
        assert record.id == "inc-007"
        assert record.severity == "high"
        assert record.coords == (36.34, 41.87)
        assert record.timeline[0].kind == "trigger"


@pytest.mark.asyncio
async def test_create_incident_uses_uuid_shape_id() -> None:
    captured: dict = {}

    async def fake_write(query, params):
        captured.update(params)
        # echo back what we asked to write
        return [_row(id=params["incident_id"])]

    with patch.object(incident_store, "write_query", new=AsyncMock(side_effect=fake_write)):
        req = IncidentCreateRequest(
            title="x",
            kind="firms.cluster",
            severity="low",
            coords=(0.0, 0.0),
        )
        record = await incident_store.create_incident(req)
        assert record.id.startswith("inc-")
        suffix = record.id.split("-", 1)[1]
        assert len(suffix) == 8
        assert all(ch in "0123456789abcdef" for ch in suffix)


@pytest.mark.asyncio
async def test_get_incident_decodes_timeline() -> None:
    with patch.object(
        incident_store,
        "read_query",
        new=AsyncMock(return_value=[_row()]),
    ):
        record = await incident_store.get_incident("inc-001")
        assert record is not None
        assert record.location == "Sinjar ridge"
        assert record.timeline == [IncidentTimelineEvent(t_offset_s=0.0, kind="trigger", text="t0")]


@pytest.mark.asyncio
async def test_close_incident_writes_status_and_closed_ts() -> None:
    captured: dict = {}

    async def fake_write(query, params):
        captured.update(params)
        return [_row(status="closed", closed_ts="2026-04-25T11:00:00Z")]

    with (
        patch.object(incident_store, "read_query", new=AsyncMock(return_value=[_row()])),
        patch.object(incident_store, "write_query", new=AsyncMock(side_effect=fake_write)),
    ):
        record = await incident_store.close_incident(
            "inc-001", IncidentStatus.SILENCED, datetime(2026, 4, 25, 11, tzinfo=UTC)
        )
        assert record is not None
        assert captured["status"] == "silenced"
        assert captured["closed_ts"] == "2026-04-25T11:00:00+00:00"


@pytest.mark.asyncio
async def test_append_timeline_event_grows_timeline() -> None:
    seed = _row()
    with (
        patch.object(incident_store, "read_query", new=AsyncMock(return_value=[seed])),
        patch.object(
            incident_store,
            "write_query",
            new=AsyncMock(side_effect=lambda q, p: [_row(timeline_json=p["timeline_json"])]),
        ),
    ):
        record = await incident_store.append_timeline_event(
            "inc-001",
            IncidentTimelineEvent(
                t_offset_s=92.0, kind="signal", text="GDELT 4 articles", severity="elevated"
            ),
        )
        assert record is not None
        assert len(record.timeline) == 2
        assert record.timeline[-1].text == "GDELT 4 articles"
