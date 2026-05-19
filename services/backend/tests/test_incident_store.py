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


@pytest.mark.asyncio
async def test_close_incident_is_idempotent_on_terminal_status() -> None:
    """Calling close_incident on an already-CLOSED incident must be a no-op."""
    mock_write = AsyncMock()
    with (
        patch.object(
            incident_store,
            "get_incident",
            new=AsyncMock(return_value=incident_store._row_to_incident(_row(status="closed"))),
        ),
        patch.object(incident_store, "write_query", new=mock_write),
    ):
        record = await incident_store.close_incident("inc-001", IncidentStatus.CLOSED)
        assert record is not None
        assert record.status == IncidentStatus.CLOSED
        mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_close_incident_does_not_overwrite_promoted_status() -> None:
    """Calling close_incident on a PROMOTED incident must leave status unchanged."""
    mock_write = AsyncMock()
    with (
        patch.object(
            incident_store,
            "get_incident",
            new=AsyncMock(return_value=incident_store._row_to_incident(_row(status="promoted"))),
        ),
        patch.object(incident_store, "write_query", new=mock_write),
    ):
        record = await incident_store.close_incident("inc-001", IncidentStatus.CLOSED)
        assert record is not None
        assert record.status == IncidentStatus.PROMOTED
        mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_apply_signal_update_appends_timeline_and_merges_severity_and_sources() -> None:
    """apply_signal_update merges sources/hints (dedupe), escalates severity, appends timeline."""
    existing_timeline = json.dumps([
        {"t_offset_s": 0.0, "kind": "trigger", "text": "initial trigger", "severity": "elevated"}
    ])
    existing_incident = incident_store._row_to_incident(
        _row(
            id="inc-042",
            severity="elevated",
            status="open",
            lat=48.0,
            lon=37.8,
            sources=["FIRMS · VIIRS_SNPP_NRT"],
            layer_hints=["firms", "events", "auto_promoter:v1", "cluster:firms:geo:48.0:37.8"],
            timeline_json=existing_timeline,
        )
    )

    new_timeline_event = IncidentTimelineEvent(
        t_offset_s=120.0,
        kind="signal",
        text="Telegram corroboration",
        severity="high",
    )

    updated_timeline = json.dumps([
        {"t_offset_s": 0.0, "kind": "trigger", "text": "initial trigger", "severity": "elevated"},
        {"t_offset_s": 120.0, "kind": "signal", "text": "Telegram corroboration", "severity": "high"},
    ])
    mock_write = AsyncMock(
        return_value=[
            _row(
                id="inc-042",
                severity="high",
                lat=48.0,
                lon=37.8,
                sources=["FIRMS · VIIRS_SNPP_NRT", "Telegram · OSINTdefender"],
                layer_hints=["firms", "events", "auto_promoter:v1", "cluster:firms:geo:48.0:37.8", "telegram"],
                timeline_json=updated_timeline,
            )
        ]
    )

    with (
        patch.object(incident_store, "get_incident", new=AsyncMock(return_value=existing_incident)),
        patch.object(incident_store, "write_query", new=mock_write),
    ):
        result = await incident_store.apply_signal_update(
            "inc-042",
            timeline_event=new_timeline_event,
            severity="high",
            sources_to_merge=["FIRMS · VIIRS_SNPP_NRT", "Telegram · OSINTdefender"],
            layer_hints_to_merge=["firms", "telegram"],
        )

    assert result is not None
    assert result.severity == "high"
    assert len(result.timeline) == 2
    assert result.timeline[-1].text == "Telegram corroboration"
    # Dedupe: "FIRMS · VIIRS_SNPP_NRT" must appear exactly once
    assert result.sources.count("FIRMS · VIIRS_SNPP_NRT") == 1
    assert "Telegram · OSINTdefender" in result.sources
    assert "telegram" in result.layer_hints
    mock_write.assert_called_once()


@pytest.mark.asyncio
async def test_apply_signal_update_missing_incident_returns_none() -> None:
    """apply_signal_update is a no-op when the incident does not exist."""
    mock_write = AsyncMock()

    with (
        patch.object(incident_store, "get_incident", new=AsyncMock(return_value=None)),
        patch.object(incident_store, "write_query", new=mock_write),
    ):
        result = await incident_store.apply_signal_update(
            "inc-does-not-exist",
            timeline_event=IncidentTimelineEvent(
                t_offset_s=0.0, kind="signal", text="phantom signal"
            ),
            severity="high",
            sources_to_merge=["some-source"],
            layer_hints_to_merge=["some-hint"],
        )

    assert result is None
    mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_list_owned_for_rehydrate_filters_by_auto_promoter_marker() -> None:
    """Only incidents with 'auto_promoter:v1' in layer_hints are returned; manual ones are excluded."""
    row1 = _row(
        id="inc-owned-open",
        status="open",
        layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:1.0:1.0"],
    )
    row2 = _row(
        id="inc-owned-promoted",
        status="promoted",
        layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:2.0:2.0"],
    )
    row3 = _row(
        id="inc-manual",
        status="open",
        layer_hints=["manual"],
    )

    with patch.object(
        incident_store,
        "read_query",
        new=AsyncMock(return_value=[row1, row2, row3]),
    ):
        result = await incident_store.list_owned_for_rehydrate()

    assert len(result) == 2
    result_ids = {inc.id for inc in result}
    assert "inc-owned-open" in result_ids
    assert "inc-owned-promoted" in result_ids
    assert "inc-manual" not in result_ids
