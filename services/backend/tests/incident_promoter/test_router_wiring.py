"""Verify /promote and /silence call ClusterStore on app.state.

Auth pattern matches the existing tests in test_incidents_router.py:
``monkeypatch.setattr(incidents_router.settings, "incidents_admin_token", ...)``
plus the ``X-Admin-Token`` request header. The mock cluster_store is
installed *inside* the TestClient context so the lifespan startup (which
sets a real ClusterStore on app.state) doesn't overwrite it.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.incident import Incident, IncidentStatus


def _fake_incident(id_: str) -> Incident:
    return Incident(
        id=id_, kind="manual", title="t", severity="high",
        coords=(0.0, 0.0), status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
    )


def test_promote_calls_cluster_store_mark_promoted(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    cs = AsyncMock()
    with patch(
        "app.routers.incidents.incident_store.create_incident",
        new=AsyncMock(return_value=_fake_incident("inc-promote-1")),
    ), patch(
        "app.routers.incidents.incident_store.close_incident",
        new=AsyncMock(return_value=_fake_incident("inc-promote-1").model_copy(
            update={"status": IncidentStatus.PROMOTED}
        )),
    ):
        with TestClient(app) as client:
            # Lifespan has run; now install the mock — it sticks for this test.
            app.state.cluster_store = cs

            resp = client.post(
                "/api/incidents/_admin/trigger",
                headers={"X-Admin-Token": "secret-xyz"},
                json={"title": "x", "kind": "manual", "severity": "high",
                      "coords": [0.0, 0.0]},
            )
            assert resp.status_code == 201, resp.text
            incident_id = resp.json()["id"]

            resp = client.post(
                f"/api/incidents/{incident_id}/promote",
                headers={"X-Admin-Token": "secret-xyz"},
            )
            assert resp.status_code == 200, resp.text

    cs.mark_promoted.assert_awaited_once_with(incident_id)


def test_silence_calls_cluster_store_mark_silenced(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    # PromoterConfig is read from app.state by the silence handler. Stub it.
    class _StubCfg:
        silence_cooldown_sec = 3600

    cs = AsyncMock()
    with patch(
        "app.routers.incidents.incident_store.create_incident",
        new=AsyncMock(return_value=_fake_incident("inc-silence-1")),
    ), patch(
        "app.routers.incidents.incident_store.close_incident",
        new=AsyncMock(return_value=_fake_incident("inc-silence-1").model_copy(
            update={"status": IncidentStatus.SILENCED}
        )),
    ):
        with TestClient(app) as client:
            app.state.cluster_store = cs
            app.state.promoter_config = _StubCfg()

            resp = client.post(
                "/api/incidents/_admin/trigger",
                headers={"X-Admin-Token": "secret-xyz"},
                json={"title": "x", "kind": "manual", "severity": "high",
                      "coords": [0.0, 0.0]},
            )
            assert resp.status_code == 201
            incident_id = resp.json()["id"]

            resp = client.post(
                f"/api/incidents/{incident_id}/silence",
                headers={"X-Admin-Token": "secret-xyz"},
            )
            assert resp.status_code == 200

    cs.mark_silenced.assert_awaited_once()
    kwargs = cs.mark_silenced.await_args.kwargs
    assert kwargs.get("until") is not None
