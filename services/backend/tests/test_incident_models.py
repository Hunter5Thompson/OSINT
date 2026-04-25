from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.incident import (
    SEVERITY_TO_CONF,
    Incident,
    IncidentCreateRequest,
    IncidentEnvelope,
    IncidentStatus,
    IncidentTimelineEvent,
)


def test_severity_table_covers_all_levels() -> None:
    assert set(SEVERITY_TO_CONF) == {"low", "elevated", "high", "critical"}
    assert 0.0 < SEVERITY_TO_CONF["low"] < SEVERITY_TO_CONF["critical"] <= 1.0


def test_incident_create_request_minimum_fields() -> None:
    req = IncidentCreateRequest(
        title="Sinjar ridge thermal cluster",
        kind="firms.cluster",
        severity="high",
        coords=[36.34, 41.87],
        location="Sinjar ridge",
        sources=["firms·1", "ucdp·#44821"],
    )
    assert req.severity == "high"
    assert req.coords == (36.34, 41.87)


def test_incident_create_request_rejects_bad_coords() -> None:
    with pytest.raises(ValidationError):
        IncidentCreateRequest(
            title="bad",
            kind="firms.cluster",
            severity="low",
            coords=[200.0, 0.0],
            location="-",
        )


def test_incident_record_status_default_open() -> None:
    inc = Incident(
        id="inc-001",
        kind="firms.cluster",
        title="x",
        severity="low",
        coords=(0.0, 0.0),
        location="-",
        status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
        sources=[],
        timeline=[],
    )
    assert inc.status is IncidentStatus.OPEN
    assert inc.confidence == pytest.approx(SEVERITY_TO_CONF["low"], rel=1e-6)


def test_envelope_has_event_id_and_type() -> None:
    env = IncidentEnvelope(
        event_id="0001712841723482-000001",
        ts="2026-04-14T16:42:03.482Z",
        type="incident.open",
        payload=Incident(
            id="inc-002",
            kind="firms.cluster",
            title="x",
            severity="elevated",
            coords=(10.0, 20.0),
            location="-",
            status=IncidentStatus.OPEN,
            trigger_ts=datetime.now(UTC),
            sources=[],
            timeline=[IncidentTimelineEvent(t_offset_s=0.0, kind="trigger", text="t0")],
        ),
    )
    assert env.type == "incident.open"
    assert env.payload.timeline[0].kind == "trigger"
