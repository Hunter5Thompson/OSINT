"""Persisted timestamps are decoded independently of the process timezone."""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.services import incident_store, report_store


@contextmanager
def _process_timezone(name: str) -> Iterator[None]:
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.parametrize("parse", [incident_store._parse_dt, report_store._parse_dt])
def test_naive_persisted_datetime_means_utc_under_any_process_timezone(parse) -> None:
    with _process_timezone("UTC"):
        utc_result = parse("2026-05-19T12:00:00")
    with _process_timezone("Europe/Berlin"):
        berlin_result = parse("2026-05-19T12:00:00")

    expected = datetime(2026, 5, 19, 12, tzinfo=UTC)
    assert utc_result == expected
    assert berlin_result == expected


@pytest.mark.parametrize("parse", [incident_store._parse_dt, report_store._parse_dt])
def test_zoned_persisted_datetime_converts_to_utc(parse) -> None:
    assert parse("2026-05-19T12:00:00Z") == datetime(2026, 5, 19, 12, tzinfo=UTC)
    assert parse("2026-05-19T12:00:00+02:00") == datetime(2026, 5, 19, 10, tzinfo=UTC)
    assert parse("2026-05-19T12:00:00-03:00") == datetime(2026, 5, 19, 15, tzinfo=UTC)
    assert parse(datetime(2026, 5, 19, 12)) == datetime(2026, 5, 19, 12, tzinfo=UTC)


@pytest.mark.parametrize("parse", [incident_store._parse_dt, report_store._parse_dt])
def test_invalid_persisted_datetime_is_not_replaced_with_current_time(parse) -> None:
    with pytest.raises(ValueError):
        parse("not-a-time")


def _report_row(**overrides):
    row = {
        "id": "report-1",
        "paragraph_num": 1,
        "stamp": "19·V",
        "title": "Briefing",
        "created_at": "2026-05-19T12:00:00Z",
        "updated_at": None,
    }
    row.update(overrides)
    return row


def test_report_missing_updated_at_uses_created_at_only() -> None:
    for row in (_report_row(), {k: v for k, v in _report_row().items() if k != "updated_at"}):
        report = report_store._row_to_report(row)
        assert report.updated_at == report.created_at


@pytest.mark.parametrize("closed_ts", ["", 0])
def test_incident_non_null_invalid_closed_timestamp_is_not_treated_as_missing(
    closed_ts,
) -> None:
    row = {
        "id": "inc-time",
        "kind": "firms.cluster",
        "title": "x",
        "severity": "high",
        "lat": 1.0,
        "lon": 2.0,
        "status": "closed",
        "trigger_ts": "2026-05-19T12:00:00Z",
        "closed_ts": closed_ts,
        "sources": [],
        "layer_hints": [],
        "timeline_json": "[]",
    }
    with pytest.raises(ValueError):
        incident_store._row_to_incident(row)


@pytest.mark.parametrize(
    "row",
    [
        _report_row(updated_at="broken"),
        _report_row(created_at="broken"),
    ],
)
def test_report_invalid_persisted_times_are_not_masked_by_fallback(row) -> None:
    with pytest.raises(ValueError):
        report_store._row_to_report(row)


def test_report_message_requires_valid_persisted_time() -> None:
    with pytest.raises(ValueError):
        report_store._row_to_message(
            {"id": "message-1", "role": "system", "text": "entry", "ts": "broken"}
        )


@pytest.mark.asyncio
async def test_report_list_isolates_invalid_timestamp_between_valid_rows(monkeypatch) -> None:
    rows = [
        _report_row(id="before"),
        _report_row(id="poison", updated_at="broken"),
        _report_row(id="after"),
    ]
    monkeypatch.setattr(report_store, "read_query", AsyncMock(return_value=rows))

    class RecordingLog:
        events: list[tuple[str, dict[str, object]]] = []

        def warning(self, event: str, **kwargs: object) -> None:
            self.events.append((event, kwargs))

    diagnostics = RecordingLog()
    monkeypatch.setattr(report_store, "log", diagnostics)

    reports = await report_store.list_reports()

    assert [report.id for report in reports] == ["before", "after"]
    assert diagnostics.events == [
        (
            "report_rows_decode_degraded",
            {
                "invalid_count": 1,
                "invalid_rows": [
                    {
                        "record_id": "poison",
                        "field": "updated_at",
                        "error_class": "ValueError",
                    }
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_report_message_list_isolates_invalid_timestamp_between_valid_rows(
    monkeypatch,
) -> None:
    rows = [
        {"id": "before", "role": "system", "text": "a", "ts": "2026-05-19T12:00:00Z"},
        {"id": "poison", "role": "system", "text": "b", "ts": "broken"},
        {"id": "after", "role": "system", "text": "c", "ts": "2026-05-19T12:00:00Z"},
    ]
    monkeypatch.setattr(report_store, "read_query", AsyncMock(return_value=rows))

    class RecordingLog:
        events: list[tuple[str, dict[str, object]]] = []

        def warning(self, event: str, **kwargs: object) -> None:
            self.events.append((event, kwargs))

    diagnostics = RecordingLog()
    monkeypatch.setattr(report_store, "log", diagnostics)

    messages = await report_store.list_report_messages("report-1")

    assert [message.id for message in messages] == ["before", "after"]
    assert diagnostics.events[0][0] == "report_messages_decode_degraded"
    assert diagnostics.events[0][1]["invalid_count"] == 1


@pytest.mark.asyncio
async def test_report_list_database_failure_is_not_a_successful_empty_list(monkeypatch) -> None:
    async def fail_read(_query, _params):
        raise ConnectionError("report database unavailable")

    monkeypatch.setattr(report_store, "read_query", fail_read)
    with pytest.raises(ConnectionError, match="report database unavailable"):
        await report_store.list_reports()
    with pytest.raises(ConnectionError, match="report database unavailable"):
        await report_store.list_report_messages("report-1")


@pytest.mark.asyncio
async def test_corrupt_scope_report_is_not_hidden_as_absent(monkeypatch) -> None:
    monkeypatch.setattr(
        report_store,
        "read_query",
        AsyncMock(return_value=[_report_row(id="corrupt", created_at="broken")]),
    )
    with pytest.raises(ValueError):
        await report_store.get_report_by_scope_keys("scope:one")
