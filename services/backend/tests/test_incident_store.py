"""Store-level tests using a fake Neo4j driver — no live DB required."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.cypher.incident_write import INCIDENT_CREATE_IDEMPOTENT
from app.models.incident import (
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.services import incident_store


class _SingleResult:
    def __init__(self, row):
        self.row = row

    async def single(self):
        return self.row


class _MutationTransaction:
    def __init__(self, row):
        self.row = row
        self.writes = []

    async def run(self, query, params=None, **kwargs):
        params = {**(params or {}), **kwargs}
        self.writes.append((query, params))
        if "__mutation_lock" in query:
            return _SingleResult({"id": params["incident_id"]} if self.row else None)
        if "applied_mutation_ids AS" in query:
            return _SingleResult(self.row)
        if "SET i.status = $status" in query:
            self.row = {
                **self.row,
                "status": params["status"],
                "closed_ts": params["closed_ts"],
                "applied_mutation_ids": params["applied_mutation_ids"],
            }
        elif "SET i.severity = $severity" in query:
            self.row = {
                **self.row,
                "severity": params["severity"],
                "sources": params["sources"],
                "layer_hints": params["layer_hints"],
                "timeline_json": params["timeline_json"],
                "applied_mutation_ids": params["applied_mutation_ids"],
            }
        return _SingleResult(self.row)


def _patch_mutation_transaction(monkeypatch, row):
    transaction = _MutationTransaction(row)

    async def execute(callback, *, metadata=None):
        return await callback(transaction)

    monkeypatch.setattr(incident_store, "write_transaction", execute)
    return transaction


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
async def test_create_incident_ordinal_is_epoch_ms_without_wrap() -> None:
    frozen = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return frozen

    captured: dict[str, object] = {}

    async def fake_write(_query: str, params: dict[str, object]) -> list[dict[str, object]]:
        captured.update(params)
        return [_row(id=str(params["incident_id"]))]

    with (
        patch.object(incident_store, "write_query", new=AsyncMock(side_effect=fake_write)),
        patch.object(incident_store, "datetime", _FrozenDateTime),
    ):
        await incident_store.create_incident(
            IncidentCreateRequest(
                title="wrap",
                kind="firms.cluster",
                severity="low",
                coords=(36.0, 41.0),
            )
        )

    expected = int(frozen.timestamp() * 1000)
    assert captured["ordinal"] == expected
    assert expected > 2_000_000_000


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
async def test_create_incident_retry_uses_create_only_query_and_current_record() -> None:
    captured: dict[str, object] = {}
    current = _row(
        id="inc-stable01", status="closed", title="Persisted title",
        timeline_json=json.dumps([
            {"t_offset_s": 0.0, "kind": "trigger", "text": "original"},
            {"t_offset_s": 4.0, "kind": "observation", "text": "later"},
        ]),
    )

    async def fake_write(query, params):
        captured["query"] = query
        captured["params"] = params
        return [current]

    with patch.object(incident_store, "write_query", new=AsyncMock(side_effect=fake_write)):
        record = await incident_store.create_incident(
            IncidentCreateRequest(
                title="Retry title", kind="firms.cluster", severity="high",
                coords=(36.0, 41.0), sources=["FIRMS"], layer_hints=["cluster:key"],
            ),
            incident_id="inc-stable01",
        )

    params = captured["params"]
    assert captured["query"] == INCIDENT_CREATE_IDEMPOTENT
    assert "ON CREATE SET" in INCIDENT_CREATE_IDEMPOTENT
    assert "REMOVE i._promoter_create_nonce" in INCIDENT_CREATE_IDEMPOTENT
    assert params["incident_id"] == "inc-stable01"
    assert isinstance(params["create_nonce"], str)
    assert record.status == IncidentStatus.CLOSED
    assert record.title == "Persisted title"
    assert [event.text for event in record.timeline] == ["original", "later"]


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


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "unknown"},
        {"status": None},
        {"severity": "medium"},
        {"lat": None},
        {"lat": float("nan")},
        {"lon": 181.0},
        {"trigger_ts": "broken"},
    ],
)
def test_incident_row_decode_rejects_poison_fields(overrides) -> None:
    with pytest.raises(ValueError):
        incident_store._row_to_incident(_row(**overrides))


def test_incident_row_decode_accepts_real_zero_coordinates() -> None:
    record = incident_store._row_to_incident(_row(lat=0.0, lon=0.0))
    assert record.coords == (0.0, 0.0)


def test_incident_row_decode_rejects_missing_status() -> None:
    row = _row()
    row.pop("status")
    with pytest.raises(ValueError):
        incident_store._row_to_incident(row)


@pytest.mark.asyncio
async def test_list_open_incidents_isolates_poison_row_and_keeps_valid_neighbor(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        incident_store,
        "read_query",
        AsyncMock(
            return_value=[
                _row(id="good-before"),
                _row(id="bad", severity="medium"),
                _row(id="good-after"),
            ]
        ),
    )
    diagnostic = Mock()
    monkeypatch.setattr(incident_store, "logger", Mock(warning=diagnostic), raising=False)

    records = await incident_store.list_open_incidents()

    assert [record.id for record in records] == ["good-before", "good-after"]
    diagnostic.assert_called_once()
    assert diagnostic.call_args.args[0] == "incident_rows_decode_degraded"
    assert diagnostic.call_args.kwargs["invalid_count"] == 1
    assert diagnostic.call_args.kwargs["invalid_rows"] == [
        {"incident_id": "bad", "error_class": "ValidationError"}
    ]


@pytest.mark.asyncio
async def test_all_poison_rows_return_no_records_with_degraded_diagnostic(monkeypatch) -> None:
    monkeypatch.setattr(
        incident_store,
        "read_query",
        AsyncMock(return_value=[_row(id="bad-1", severity="medium"), _row(id="bad-2", lon=181)]),
    )
    diagnostic = Mock()
    monkeypatch.setattr(incident_store, "logger", Mock(warning=diagnostic), raising=False)

    records = await incident_store.list_open_incidents()

    assert records == []
    diagnostic.assert_called_once()
    assert diagnostic.call_args.kwargs["invalid_count"] == 2


@pytest.mark.asyncio
async def test_rehydrate_keeps_valid_rows_and_reports_degraded_for_poison_neighbor(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        incident_store,
        "read_query",
        AsyncMock(
            return_value=[
                _row(id="good", layer_hints=["auto_promoter:v1", "cluster:firms:good"]),
                _row(
                    id="bad", severity="medium",
                    layer_hints=["auto_promoter:v1", "cluster:firms:bad"],
                ),
            ]
        ),
    )

    result = await incident_store.list_owned_for_rehydrate()

    assert [incident.id for incident in result.incidents] == ["good"]
    assert result.degraded is True


@pytest.mark.asyncio
async def test_rehydrate_query_includes_owned_rows_with_unknown_status(monkeypatch) -> None:
    read = AsyncMock(return_value=[])
    monkeypatch.setattr(incident_store, "read_query", read)

    await incident_store.list_owned_for_rehydrate()

    query = read.await_args.args[0]
    assert "auto_promoter:v1" in query
    assert "i.status IS NULL" in query
    assert "closed" in query and "silenced" in query


@pytest.mark.asyncio
async def test_rehydrate_does_not_hide_database_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        incident_store,
        "read_query",
        AsyncMock(side_effect=ConnectionError("neo4j unavailable")),
    )

    with pytest.raises(ConnectionError, match="neo4j unavailable"):
        await incident_store.list_owned_for_rehydrate()


@pytest.mark.asyncio
async def test_close_incident_writes_status_and_closed_ts(monkeypatch) -> None:
    transaction = _patch_mutation_transaction(monkeypatch, _row())
    result = await incident_store.close_incident(
        "inc-001", IncidentStatus.SILENCED, datetime(2026, 4, 25, 11, tzinfo=UTC)
    )
    assert result.status == "applied"
    assert result.incident is not None
    assert result.incident.status == IncidentStatus.SILENCED
    close_query, params = transaction.writes[-1]
    assert "SET i.status = $status" in close_query
    assert params["status"] == "silenced"
    assert params["closed_ts"] == "2026-04-25T11:00:00+00:00"


@pytest.mark.asyncio
async def test_append_timeline_event_grows_timeline(monkeypatch) -> None:
    _patch_mutation_transaction(monkeypatch, _row())
    result = await incident_store.append_timeline_event(
        "inc-001",
        IncidentTimelineEvent(
            t_offset_s=92.0, kind="signal", text="GDELT 4 articles", severity="elevated"
        ),
    )
    assert result.status == "applied"
    assert result.incident is not None
    assert len(result.incident.timeline) == 2
    assert result.incident.timeline[-1].text == "GDELT 4 articles"


@pytest.mark.asyncio
async def test_close_incident_is_idempotent_on_terminal_status(monkeypatch) -> None:
    """Calling close_incident on an already-CLOSED incident must be a no-op."""
    transaction = _patch_mutation_transaction(monkeypatch, _row(status="closed"))
    result = await incident_store.close_incident("inc-001", IncidentStatus.CLOSED)
    assert result.status == "unchanged"
    assert result.incident is not None
    assert result.incident.status == IncidentStatus.CLOSED
    assert len(transaction.writes) == 2


@pytest.mark.asyncio
async def test_close_incident_does_not_overwrite_promoted_status(monkeypatch) -> None:
    """Calling close_incident on a PROMOTED incident must leave status unchanged."""
    transaction = _patch_mutation_transaction(monkeypatch, _row(status="promoted"))
    result = await incident_store.close_incident("inc-001", IncidentStatus.CLOSED)
    assert result.status == "unchanged"
    assert result.incident is not None
    assert result.incident.status == IncidentStatus.PROMOTED
    assert len(transaction.writes) == 2


@pytest.mark.asyncio
async def test_apply_signal_update_appends_timeline_and_merges_severity_and_sources(
    monkeypatch,
) -> None:
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

    transaction = _patch_mutation_transaction(
        monkeypatch,
        _row(
            id=existing_incident.id,
            severity=existing_incident.severity,
            sources=existing_incident.sources,
            layer_hints=existing_incident.layer_hints,
            timeline_json=existing_timeline,
        ),
    )
    result = await incident_store.apply_signal_update(
        "inc-042",
        timeline_event=new_timeline_event,
        severity="high",
        sources_to_merge=["FIRMS · VIIRS_SNPP_NRT", "Telegram · OSINTdefender"],
        layer_hints_to_merge=["firms", "telegram"],
    )

    assert result.status == "applied"
    assert result.incident is not None
    assert result.incident.severity == "high"
    assert len(result.incident.timeline) == 2
    assert result.incident.timeline[-1].text == "Telegram corroboration"
    # Dedupe: "FIRMS · VIIRS_SNPP_NRT" must appear exactly once
    assert result.incident.sources.count("FIRMS · VIIRS_SNPP_NRT") == 1
    assert "Telegram · OSINTdefender" in result.incident.sources
    assert "telegram" in result.incident.layer_hints
    update_query, params = transaction.writes[-1]
    assert "MERGE" not in update_query
    assert params["sources"][-1] == "Telegram · OSINTdefender"


@pytest.mark.asyncio
async def test_apply_signal_update_missing_incident_returns_not_found(monkeypatch) -> None:
    """apply_signal_update is a no-op when the incident does not exist."""
    transaction = _patch_mutation_transaction(monkeypatch, None)
    result = await incident_store.apply_signal_update(
        "inc-does-not-exist",
        timeline_event=IncidentTimelineEvent(
            t_offset_s=0.0, kind="signal", text="phantom signal"
        ),
        severity="high",
        sources_to_merge=["some-source"],
        layer_hints_to_merge=["some-hint"],
    )

    assert result.status == "not_found"
    assert result.incident is None
    assert len(transaction.writes) == 1


@pytest.mark.asyncio
async def test_apply_signal_update_does_not_lower_locked_severity(monkeypatch) -> None:
    transaction = _patch_mutation_transaction(monkeypatch, _row(severity="critical"))
    result = await incident_store.apply_signal_update(
        "inc-001",
        timeline_event=IncidentTimelineEvent(t_offset_s=1, kind="signal", text="late"),
        severity="low",
        sources_to_merge=[],
        layer_hints_to_merge=[],
    )
    assert result.status == "applied"
    assert result.incident is not None
    assert result.incident.severity == "critical"
    assert "lat =" not in transaction.writes[-1][0]
    assert "lon =" not in transaction.writes[-1][0]
    assert "MERGE" not in transaction.writes[-1][0]


@pytest.mark.asyncio
async def test_apply_signal_update_does_not_mutate_terminal_incident(monkeypatch) -> None:
    transaction = _patch_mutation_transaction(monkeypatch, _row(status="silenced"))
    result = await incident_store.apply_signal_update(
        "inc-001",
        timeline_event=IncidentTimelineEvent(t_offset_s=1, kind="signal", text="late"),
        severity="critical",
        sources_to_merge=["late-source"],
        layer_hints_to_merge=["late-hint"],
    )
    assert result.status == "unchanged"
    assert result.incident is not None
    assert result.incident.status == IncidentStatus.SILENCED
    assert len(transaction.writes) == 2


@pytest.mark.asyncio
async def test_managed_callback_replay_uses_receipt_without_duplicate_append(monkeypatch) -> None:
    transaction = _patch_mutation_transaction(monkeypatch, _row())

    async def retry_callback(callback, *, metadata=None):
        first = await callback(transaction)
        replay = await callback(transaction)
        assert first.status == "applied"
        return replay

    monkeypatch.setattr(incident_store, "write_transaction", retry_callback)
    result = await incident_store.apply_signal_update(
        "inc-001",
        timeline_event=IncidentTimelineEvent(t_offset_s=1, kind="signal", text="once"),
        severity="high",
        sources_to_merge=["s"],
        layer_hints_to_merge=["h"],
    )
    assert result.status == "applied"
    assert result.incident is not None
    assert [event.text for event in result.incident.timeline].count("once") == 1
    assert len(transaction.writes) == 5  # lock/read/update, then replay lock/read


@pytest.mark.asyncio
async def test_close_incident_rejects_open_target() -> None:
    with pytest.raises(ValueError, match="must be terminal"):
        await incident_store.close_incident("inc-001", IncidentStatus.OPEN)


@pytest.mark.asyncio
async def test_list_owned_for_rehydrate_filters_by_auto_promoter_marker() -> None:
    """Only incidents with 'auto_promoter:v1' in layer_hints are returned;
    manual ones are excluded."""
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
        autospec=True,
        return_value=[row1, row2, row3],
    ) as mock_read:
        result = await incident_store.list_owned_for_rehydrate()

    assert result.degraded is False
    assert result.invalid_rows == 0
    assert len(result.incidents) == 2
    result_ids = {inc.id for inc in result.incidents}
    assert "inc-owned-open" in result_ids
    assert "inc-owned-promoted" in result_ids
    assert "inc-manual" not in result_ids
    mock_read.assert_awaited_once()
    query, params = mock_read.await_args.args
    assert params == {"limit": 500}
    assert "ORDER BY i.ordinal DESC" in query
