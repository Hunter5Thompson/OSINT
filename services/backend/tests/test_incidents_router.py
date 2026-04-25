from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.incident import (
    Incident,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.services.incident_stream import get_incident_stream


def _make_incident(incident_id: str = "inc-001") -> Incident:
    return Incident(
        id=incident_id,
        kind="firms.cluster",
        title="x",
        severity="elevated",
        coords=(36.34, 41.87),
        location="Sinjar",
        status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
        sources=["firms·1"],
        layer_hints=["firmsHotspots"],
        timeline=[IncidentTimelineEvent(t_offset_s=0.0, kind="trigger", text="t0")],
    )


def test_list_incidents_returns_records() -> None:
    with patch("app.routers.incidents.incident_store.list_open_incidents",
               new=AsyncMock(return_value=[_make_incident()])):
        with TestClient(app) as client:
            resp = client.get("/api/incidents")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["id"] == "inc-001"
            assert data[0]["coords"] == [36.34, 41.87]


def test_get_incident_404_when_missing() -> None:
    with patch("app.routers.incidents.incident_store.get_incident",
               new=AsyncMock(return_value=None)):
        with TestClient(app) as client:
            resp = client.get("/api/incidents/inc-999")
            assert resp.status_code == 404


def test_admin_create_publishes_to_stream() -> None:
    stream = get_incident_stream()
    stream.clear()
    queue = stream.subscribe()
    try:
        with patch("app.routers.incidents.incident_store.create_incident",
                   new=AsyncMock(return_value=_make_incident("inc-007"))):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/incidents/_admin/trigger",
                    json={
                        "title": "x",
                        "kind": "firms.cluster",
                        "severity": "elevated",
                        "coords": [36.34, 41.87],
                        "location": "Sinjar",
                    },
                )
                assert resp.status_code == 201
                assert resp.json()["id"] == "inc-007"
                env = queue.get_nowait()
                assert env.type == "incident.open"
                assert env.payload.id == "inc-007"
    finally:
        stream.unsubscribe(queue)


def test_silence_publishes_close_event() -> None:
    stream = get_incident_stream()
    stream.clear()
    queue = stream.subscribe()
    try:
        closed = _make_incident().model_copy(
            update={"status": IncidentStatus.SILENCED, "closed_ts": datetime.now(UTC)}
        )
        with patch("app.routers.incidents.incident_store.close_incident",
                   new=AsyncMock(return_value=closed)):
            with TestClient(app) as client:
                resp = client.post("/api/incidents/inc-001/silence")
                assert resp.status_code == 200
                env = queue.get_nowait()
                assert env.type == "incident.silence"
    finally:
        stream.unsubscribe(queue)


def test_admin_trigger_rejects_when_token_required(monkeypatch) -> None:
    from app.routers import incidents as incidents_router

    monkeypatch.setattr(incidents_router.settings, "incidents_admin_token", "secret-xyz")
    with TestClient(app) as client:
        resp = client.post(
            "/api/incidents/_admin/trigger",
            json={
                "title": "x",
                "kind": "firms.cluster",
                "severity": "elevated",
                "coords": [0.0, 0.0],
            },
        )
        assert resp.status_code == 401
        # And accepts when the header matches:
        with patch(
            "app.routers.incidents.incident_store.create_incident",
            new=AsyncMock(return_value=_make_incident("inc-200")),
        ):
            resp = client.post(
                "/api/incidents/_admin/trigger",
                headers={"X-Admin-Token": "secret-xyz"},
                json={
                    "title": "x",
                    "kind": "firms.cluster",
                    "severity": "elevated",
                    "coords": [0.0, 0.0],
                },
            )
            assert resp.status_code == 201


def test_stream_route_is_not_swallowed_by_dynamic_id() -> None:
    """Regression: GET /api/incidents/stream must hit the SSE handler, NOT
    the GET /{incident_id} handler. FastAPI matches routes in declaration
    order, so /stream MUST be declared before /{incident_id}.

    Note: client.stream() blocks until the SSE generator exits (httpx ASGI
    transport limitation). We patch _sse_generator with a one-shot stub so
    the test completes immediately while still exercising the real FastAPI
    route dispatch (the important invariant being tested).
    """
    from collections.abc import AsyncGenerator

    async def _stub_gen(*_args, **_kwargs) -> AsyncGenerator[dict[str, str], None]:
        yield {"comment": "ready"}

    with patch("app.routers.incidents._sse_generator", new=_stub_gen):
        with TestClient(app) as client:
            with client.stream("GET", "/api/incidents/stream") as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
