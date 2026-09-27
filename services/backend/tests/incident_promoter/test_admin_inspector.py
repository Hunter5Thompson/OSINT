"""Tests for GET /api/incidents/_admin/promoter."""
import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import Request
from fastapi.testclient import TestClient

from app.main import app
from app.models.incident import Incident, IncidentStatus
from app.routers.incidents import admin_promoter_inspector
from app.services.incident_promoter.cluster_store import ClusterState, ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.promoter import Promoter
from app.services.incident_store import RehydrationResult


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
        assert getattr(app.state, "promoter", None) is not None
        assert set(getattr(app.state, "promoter_tasks", {})) == {"drain", "sweeper"}
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


def test_admin_inspector_distinguishes_drain_failure_from_live_sweeper(monkeypatch):
    from app.routers import incidents as incidents_router

    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    class TaskState:
        def __init__(self, *, done, cancelled=False, error=None):
            self._done = done
            self._cancelled = cancelled
            self._error = error

        def done(self):
            return self._done

        def cancelled(self):
            return self._cancelled

        def exception(self):
            return self._error

    class PromoterHealth:
        def health_snapshot(self):
            return {
                "rehydration_status": "healthy",
                "rehydration_error": None,
                "invalid_rows": 0,
                "drain_status": "cancelled",
            }

    with TestClient(app) as client:
        app.state.cluster_store = ClusterStore(clock=lambda: datetime.now(UTC))
        app.state.promoter_config = PromoterConfig.from_env()
        app.state.promoter = PromoterHealth()
        app.state.promoter_tasks = {
            "drain": TaskState(done=True, cancelled=True),
            "sweeper": TaskState(done=False),
        }
        response = client.get(
            "/api/incidents/_admin/promoter",
            headers={"X-Admin-Token": "secret-xyz"},
        )

    assert response.status_code == 200
    assert response.json()["tasks"] == {"drain": "cancelled", "sweeper": "running"}
    assert response.json()["health"]["drain_status"] == "cancelled"


def _direct_request(state) -> Request:
    app_stub = SimpleNamespace(state=state)
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/incidents/_admin/promoter",
            "raw_path": b"/api/incidents/_admin/promoter",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "root_path": "",
            "app": app_stub,
        }
    )


async def test_real_promoter_rehydrate_poison_blocks_drain_and_inspector_shows_sweeper(
    fake_clock,
):
    class SignalStream:
        def __init__(self):
            self.queue = asyncio.Queue()

        def subscribe(self):
            return self.queue

        def unsubscribe(self, _queue):
            pass

    class Store:
        async def list_owned_for_rehydrate(self):
            good = Incident(
                id="inc-valid-neighbor", kind="firms.cluster", title="valid",
                severity="high", coords=(1.0, 2.0), status=IncidentStatus.OPEN,
                trigger_ts=fake_clock(),
                layer_hints=["auto_promoter:v1", "cluster:firms:geo:1:2"],
            )
            return RehydrationResult([good], degraded=True, invalid_rows=1)

    cfg = PromoterConfig(enabled=True, sweeper_tick_sec=3600)
    store = ClusterStore(clock=fake_clock)
    promoter = Promoter(
        signal_stream=SignalStream(), cluster_store=store, incident_store=Store(),
        incident_event_stream=SimpleNamespace(publish=lambda *_args: None),
        config=cfg, clock=fake_clock, detectors=[],
    )
    drain_task = asyncio.create_task(promoter.run())
    sweeper_task = asyncio.create_task(promoter.sweeper_loop())
    try:
        await asyncio.wait_for(drain_task, timeout=1)
        request = _direct_request(
            SimpleNamespace(
                cluster_store=store,
                promoter_config=cfg,
                promoter=promoter,
                promoter_tasks={"drain": drain_task, "sweeper": sweeper_task},
            )
        )
        body = await admin_promoter_inspector(request)
        assert body["health"]["rehydration_status"] == "degraded"
        assert body["health"]["drain_status"] == "blocked"
        assert body["tasks"] == {"drain": "stopped", "sweeper": "running"}
        assert [cluster.incident_id for cluster in store.active_clusters()] == [
            "inc-valid-neighbor"
        ]
    finally:
        sweeper_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper_task


async def test_real_promoter_database_failure_is_unhealthy_and_never_drains(fake_clock):
    class SignalStream:
        def __init__(self):
            self.queue = asyncio.Queue()

        def subscribe(self):
            return self.queue

        def unsubscribe(self, _queue):
            pass

    class Store:
        async def list_owned_for_rehydrate(self):
            raise ConnectionError("neo4j unavailable")

    stream = SignalStream()
    await stream.queue.put(object())
    cfg = PromoterConfig(enabled=True, sweeper_tick_sec=3600)
    cluster_store = ClusterStore(clock=fake_clock)
    promoter = Promoter(
        signal_stream=stream, cluster_store=cluster_store, incident_store=Store(),
        incident_event_stream=SimpleNamespace(publish=lambda *_args: None),
        config=cfg, clock=fake_clock, detectors=[],
    )
    drain_task = asyncio.create_task(promoter.run())
    sweeper_task = asyncio.create_task(promoter.sweeper_loop())
    try:
        await asyncio.wait_for(drain_task, timeout=1)
        request = _direct_request(
            SimpleNamespace(
                cluster_store=cluster_store,
                promoter_config=cfg,
                promoter=promoter,
                promoter_tasks={"drain": drain_task, "sweeper": sweeper_task},
            )
        )
        body = await admin_promoter_inspector(request)
        assert stream.queue.qsize() == 1
        assert body["health"]["rehydration_status"] == "unhealthy"
        assert body["health"]["rehydration_error"] == "ConnectionError"
        assert body["health"]["drain_status"] == "blocked"
        assert body["tasks"] == {"drain": "stopped", "sweeper": "running"}
    finally:
        sweeper_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper_task


async def test_real_promoter_cancelled_drain_is_visible_while_sweeper_runs(fake_clock):
    draining = asyncio.Event()

    class BlockingQueue(asyncio.Queue):
        async def get(self):
            draining.set()
            return await super().get()

    class SignalStream:
        def __init__(self):
            self.queue = BlockingQueue()

        def subscribe(self):
            return self.queue

        def unsubscribe(self, _queue):
            pass

    class Store:
        async def list_owned_for_rehydrate(self):
            return RehydrationResult([], degraded=False, invalid_rows=0)

    cfg = PromoterConfig(enabled=True, sweeper_tick_sec=3600)
    store = ClusterStore(clock=fake_clock)
    promoter = Promoter(
        signal_stream=SignalStream(), cluster_store=store, incident_store=Store(),
        incident_event_stream=SimpleNamespace(publish=lambda *_args: None),
        config=cfg, clock=fake_clock, detectors=[],
    )
    drain_task = asyncio.create_task(promoter.run())
    sweeper_task = asyncio.create_task(promoter.sweeper_loop())
    try:
        await asyncio.wait_for(draining.wait(), timeout=1)
        assert promoter.health_snapshot()["drain_status"] == "running"
        drain_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drain_task
        request = _direct_request(
            SimpleNamespace(
                cluster_store=store,
                promoter_config=cfg,
                promoter=promoter,
                promoter_tasks={"drain": drain_task, "sweeper": sweeper_task},
            )
        )
        body = await admin_promoter_inspector(request)
        assert body["health"]["drain_status"] == "cancelled"
        assert body["tasks"] == {"drain": "cancelled", "sweeper": "running"}
    finally:
        if not drain_task.done():
            drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain_task
        sweeper_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper_task
