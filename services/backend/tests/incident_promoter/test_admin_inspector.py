"""Tests for GET /api/incidents/_admin/promoter."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services.incident_promoter.cluster_store import ClusterState, ClusterStore
from app.services.incident_promoter.config import PromoterConfig


def test_admin_inspector_returns_snapshot(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    def clock():
        return datetime(2026, 5, 19, 12, 0, tzinfo=UTC)

    store = ClusterStore(clock=clock)
    store._by_key["firms:geo:1.0:1.0"] = ClusterState(  # noqa: SLF001
        cluster_key="firms:geo:1.0:1.0", incident_id="inc-a",
        detector_id="firms", severity="high", coords=(1.0, 1.0),
        hit_count=4, last_signal_ts=clock(), created_ts=clock(),
        incident_status="open",
    )
    store._by_incident_id["inc-a"] = "firms:geo:1.0:1.0"  # noqa: SLF001
    store._cooldowns["telegram:topic:abc"] = clock() + timedelta(hours=1)  # noqa: SLF001

    with TestClient(app) as client:
        # Install the seeded store after lifespan has set its own.
        app.state.cluster_store = store
        app.state.promoter_config = PromoterConfig.from_env()

        resp = client.get(
            "/api/incidents/_admin/promoter",
            headers={"X-Admin-Token": "secret-xyz"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "enabled_detectors" in body
    assert any(c["cluster_key"] == "firms:geo:1.0:1.0" for c in body["active_clusters"])
    assert body["cooldowns"][0]["cluster_key"] == "telegram:topic:abc"
    assert "cooldown_until" in body["cooldowns"][0]


def test_admin_inspector_returns_empty_when_no_promoter(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    with TestClient(app) as client:
        app.state.cluster_store = None
        app.state.promoter_config = None
        resp = client.get(
            "/api/incidents/_admin/promoter",
            headers={"X-Admin-Token": "secret-xyz"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled_detectors"] == []
    assert body["active_clusters"] == []
    assert body["cooldowns"] == []
