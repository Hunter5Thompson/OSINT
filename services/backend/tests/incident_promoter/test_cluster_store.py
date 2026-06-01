"""Structural tests for ClusterStore (data + listener registration only)."""
from datetime import UTC, datetime

import pytest

from app.services.incident_promoter.cluster_store import (
    ClusterState,
    ClusterStore,
)


def test_cluster_store_starts_empty(fake_clock):
    store = ClusterStore(clock=fake_clock)
    assert store.active_clusters() == []
    assert store.cooldowns() == {}
    assert store.is_empty() is True


def test_add_termination_listener_collects_callbacks(fake_clock):
    store = ClusterStore(clock=fake_clock)
    received: list[tuple[str, object]] = []

    def listener(key: str, suppress_until=None):
        received.append((key, suppress_until))

    store.add_termination_listener(listener)
    # listener is registered but not invoked yet
    assert received == []
    assert len(store._termination_listeners) == 1  # noqa: SLF001 — internal check


def test_cluster_state_is_dataclass_with_required_fields():
    s = ClusterState(
        cluster_key="firms:geo:48.0:37.8",
        incident_id="inc-1",
        detector_id="firms",
        severity="high",
        coords=(48.0, 37.8),
        hit_count=3,
        last_signal_ts=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
        created_ts=datetime(2026, 5, 19, 11, 50, tzinfo=UTC),
        contributing_signal_ids=["a", "b", "c"],
        incident_status="open",
    )
    assert s.hit_count == 3
    # cooldown is tracked in ClusterStore._cooldowns, NOT here
    assert not hasattr(s, "silenced_until")


@pytest.mark.asyncio
async def test_handle_create_path(fake_clock, fake_incident_store, fake_incident_event_stream):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    hit = ClusterHit(
        cluster_key="firms:geo:48.0:37.8",
        detector_id="firms",
        incident_kind="firms.cluster",
        title="FIRMS cluster ignited · 3 detections in firms:geo:48.0:37.8",
        severity="high",
        coords=(48.0, 37.8),
        location="",
        sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
        layer_hints_to_merge=["firms", "auto_promoter:v1", "cluster:firms:geo:48.0:37.8"],
        timeline_event=IncidentTimelineEvent(
            t_offset_s=0.0, kind="trigger", text="seed", severity="high"
        ),
        contributing_signal_ids=["a", "b", "c"],
    )
    await store.handle(
        hit,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
    )
    assert fake_incident_event_stream.types() == ["incident.open"]
    state = store.get_by_cluster_key("firms:geo:48.0:37.8")
    assert state is not None
    assert state.incident_status == "open"
    # hit_count == len(contributing_signal_ids) at ignition (spec §5.1)
    assert state.hit_count == 3
    assert "firms:geo:48.0:37.8" not in store._reserving  # noqa: SLF001


@pytest.mark.asyncio
async def test_handle_update_path_appends_timeline_and_publishes_update(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)

    def _make_hit(eid: str, sev: str = "high") -> ClusterHit:
        return ClusterHit(
            cluster_key="firms:geo:1.0:1.0",
            detector_id="firms",
            incident_kind="firms.cluster",
            title=f"FIRMS hit {eid}",
            severity=sev,
            coords=(1.0, 1.0),
            location="",
            sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
            layer_hints_to_merge=["firms", "auto_promoter:v1", "cluster:firms:geo:1.0:1.0"],
            timeline_event=IncidentTimelineEvent(
                t_offset_s=0.0, kind="observation", text=eid, severity=sev
            ),
            contributing_signal_ids=[eid],
        )

    # first hit: create
    await store.handle(
        _make_hit("a"),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
    )
    # second hit: update
    fake_clock.advance(60)
    await store.handle(
        _make_hit("b"),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
    )

    assert fake_incident_event_stream.types() == ["incident.open", "incident.update"]
    state = store.get_by_cluster_key("firms:geo:1.0:1.0")
    assert state.hit_count == 2
    incident = fake_incident_event_stream.published[-1][1]
    assert len(incident.timeline) == 2  # 1 trigger + 1 observation


@pytest.mark.asyncio
async def test_handle_escalation_curves_per_detector(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    """Spec §4.3 escalation: telegram elevated→high@5, high→critical@10."""
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "telegram:topic:escalate"

    def _hit(eid: str) -> ClusterHit:
        return ClusterHit(
            cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
            title=f"Telegram hit {eid}", severity="elevated",
            coords=None, location="",
            sources_to_merge=["Telegram · test"],
            layer_hints_to_merge=["telegram", "auto_promoter:v1", f"cluster:{key}"],
            timeline_event=IncidentTimelineEvent(
                t_offset_s=0.0, kind="observation", text=eid, severity="elevated"
            ),
            contributing_signal_ids=[eid],
        )

    # Ignition packing 3 signals → hit_count=3, severity floor "elevated"
    igniter = ClusterHit(
        cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
        title="Telegram cluster · 3 matching posts", severity="elevated",
        coords=None, location="",
        sources_to_merge=["Telegram · test"],
        layer_hints_to_merge=["telegram", "auto_promoter:v1", f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["a", "b", "c"],
    )
    await store.handle(igniter, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key(key)
    assert state.hit_count == 3 and state.severity == "elevated"

    # Drive hit_count to 5 → escalate to high
    for i, eid in enumerate(["d", "e"]):
        fake_clock.advance(60)
        await store.handle(_hit(eid), incident_store=fake_incident_store,
                           incident_event_stream=fake_incident_event_stream)
    assert state.hit_count == 5
    assert state.severity == "high"

    # Drive hit_count to 10 → escalate to critical
    for eid in ["f", "g", "h", "i", "j"]:
        fake_clock.advance(60)
        await store.handle(_hit(eid), incident_store=fake_incident_store,
                           incident_event_stream=fake_incident_event_stream)
    assert state.hit_count == 10
    assert state.severity == "critical"


@pytest.mark.asyncio
async def test_handle_promoted_state_silently_absorbs(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "firms:geo:2.0:2.0"
    hit = ClusterHit(
        cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
        title="seed", severity="high", coords=(2.0, 2.0), location="",
        sources_to_merge=[], layer_hints_to_merge=["auto_promoter:v1", f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key(key)
    # simulate promote
    state.incident_status = "promoted"
    pre = fake_clock()
    fake_clock.advance(30)

    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    # No new SSE frame
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert state.hit_count == 1            # unchanged
    assert state.last_signal_ts > pre      # internal only


@pytest.mark.asyncio
async def test_handle_cooldown_drops_hit(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "telegram:topic:abc123"
    store._cooldowns[key] = fake_clock() + timedelta(hours=1)  # noqa: SLF001

    hit = ClusterHit(
        cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
        title="seed", severity="elevated", coords=None, location="",
        sources_to_merge=[], layer_hints_to_merge=[f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=[],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == []
    assert store.get_by_cluster_key(key) is None
    assert key in store.cooldowns()


@pytest.mark.asyncio
async def test_handle_cooldown_expired_creates_normally(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "telegram:topic:abc123"
    store._cooldowns[key] = fake_clock() + timedelta(seconds=10)  # noqa: SLF001
    fake_clock.advance(20)  # cooldown expired

    hit = ClusterHit(
        cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
        title="fresh", severity="elevated", coords=None, location="",
        sources_to_merge=[], layer_hints_to_merge=[f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=[],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert key not in store.cooldowns()


@pytest.mark.asyncio
async def test_mark_promoted_sets_status_and_is_noop_for_unknown(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    hit = ClusterHit(
        cluster_key="firms:geo:3.0:3.0", detector_id="firms",
        incident_kind="firms.cluster", title="seed", severity="high",
        coords=(3.0, 3.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:3.0:3.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key("firms:geo:3.0:3.0")
    incident_id = state.incident_id

    await store.mark_promoted(incident_id)
    assert store.get_by_cluster_key("firms:geo:3.0:3.0").incident_status == "promoted"

    await store.mark_promoted("inc-not-here")  # no exception


@pytest.mark.asyncio
async def test_mark_silenced_drops_state_records_cooldown_fires_listeners(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    received: list[tuple[str, object]] = []
    store = ClusterStore(clock=fake_clock)
    store.add_termination_listener(
        lambda k, suppress_until=None: received.append((k, suppress_until))
    )

    hit = ClusterHit(
        cluster_key="telegram:topic:abc", detector_id="telegram",
        incident_kind="telegram.burst", title="seed", severity="elevated",
        coords=None, location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:telegram:topic:abc"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key("telegram:topic:abc")
    until = fake_clock() + timedelta(hours=1)

    await store.mark_silenced(state.incident_id, until=until)

    assert store.get_by_cluster_key("telegram:topic:abc") is None
    assert store.cooldowns()["telegram:topic:abc"] == until
    assert received == [("telegram:topic:abc", until)]


def test_snapshot_for_sweep_classifies_stale_open_promoted_and_expired_cooldowns(
    fake_clock,
):
    from datetime import timedelta

    from app.services.incident_promoter.cluster_store import ClusterState, ClusterStore

    store = ClusterStore(clock=fake_clock)
    now = fake_clock()
    quiet = 900  # 15 min

    # stale open
    store._by_key["k_open"] = ClusterState(  # noqa: SLF001
        cluster_key="k_open", incident_id="inc-a", detector_id="firms",
        severity="high", coords=(0.0, 0.0), hit_count=3,
        last_signal_ts=now - timedelta(seconds=quiet + 60),
        created_ts=now - timedelta(seconds=quiet + 200),
        incident_status="open",
    )
    store._by_incident_id["inc-a"] = "k_open"  # noqa: SLF001

    # stale promoted
    store._by_key["k_prom"] = ClusterState(  # noqa: SLF001
        cluster_key="k_prom", incident_id="inc-b", detector_id="firms",
        severity="high", coords=(0.0, 0.0), hit_count=3,
        last_signal_ts=now - timedelta(seconds=quiet + 30),
        created_ts=now - timedelta(seconds=quiet + 200),
        incident_status="promoted",
    )
    store._by_incident_id["inc-b"] = "k_prom"  # noqa: SLF001

    # fresh
    store._by_key["k_fresh"] = ClusterState(  # noqa: SLF001
        cluster_key="k_fresh", incident_id="inc-c", detector_id="firms",
        severity="high", coords=(0.0, 0.0), hit_count=1,
        last_signal_ts=now - timedelta(seconds=10),
        created_ts=now - timedelta(seconds=10),
        incident_status="open",
    )
    store._by_incident_id["inc-c"] = "k_fresh"  # noqa: SLF001

    # expired + live cooldowns
    store._cooldowns["cool_expired"] = now - timedelta(seconds=1)  # noqa: SLF001
    store._cooldowns["cool_live"] = now + timedelta(seconds=60)  # noqa: SLF001

    snap = store.snapshot_for_sweep(quiet_window_sec=quiet, now=now)
    assert {s.cluster_key for s in snap.stale_open} == {"k_open"}
    assert {s.cluster_key for s in snap.stale_promoted} == {"k_prom"}
    assert set(snap.expired_cooldown_keys) == {"cool_expired"}
