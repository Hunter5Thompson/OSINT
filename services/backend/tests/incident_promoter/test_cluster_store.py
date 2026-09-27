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
async def test_invalid_create_releases_reservation_and_next_valid_hit_creates(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "firms:geo:91.0:20.0"

    def hit(coords: tuple[float, float]) -> ClusterHit:
        return ClusterHit(
            cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
            title="FIRMS ignition", severity="high", coords=coords, location="",
            sources_to_merge=["FIRMS"], layer_hints_to_merge=["auto_promoter:v1"],
            timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
            contributing_signal_ids=["a", "b", "c"],
        )

    with pytest.raises(ValueError, match="coords out of range"):
        await store.handle(hit((91.0, 20.0)), incident_store=fake_incident_store,
                           incident_event_stream=fake_incident_event_stream)
    assert key not in store._reserving  # noqa: SLF001
    assert fake_incident_event_stream.types() == []

    await store.handle(hit((89.0, 20.0)), incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == ["incident.open"]


@pytest.mark.asyncio
async def test_failed_create_retries_same_id_and_keeps_ignition_metadata(
    fake_clock, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    class PersistThenFailStore:
        def __init__(self):
            self.ids = []
            self.requests = []
            self.records = {}

        async def create_incident(self, req, *, incident_id=None):
            if incident_id is None:
                from uuid import uuid4
                incident_id = f"inc-{uuid4().hex[:8]}"
            self.ids.append(incident_id)
            self.requests.append(req)
            if incident_id not in self.records:
                from app.models.incident import Incident, IncidentStatus
                self.records[incident_id] = Incident(
                    id=incident_id, kind=req.kind, title=req.title, severity=req.severity,
                    coords=req.coords, location=req.location, status=IncidentStatus.OPEN,
                    trigger_ts=fake_clock(), sources=list(req.sources),
                    layer_hints=list(req.layer_hints),
                    timeline=[IncidentTimelineEvent(t_offset_s=0, kind="trigger",
                                                    text=req.initial_text or "")],
                    )
                if len(self.ids) == 1:
                    raise RuntimeError("commit acknowledgement lost")
            return self.records[incident_id]

        async def apply_signal_update(
            self, incident_id, *, timeline_event, severity, sources_to_merge,
            layer_hints_to_merge,
        ):
            from app.models.incident import Incident
            current = self.records[incident_id]
            updated = current.model_copy(update={
                "timeline": [*current.timeline, timeline_event],
                "sources": list(dict.fromkeys([*current.sources, *sources_to_merge])),
                "layer_hints": list(dict.fromkeys([*current.layer_hints, *layer_hints_to_merge])),
                "severity": severity,
            })
            assert isinstance(updated, Incident)
            self.records[incident_id] = updated
            return updated

    store = ClusterStore(clock=fake_clock)
    incident_store = PersistThenFailStore()
    hit = ClusterHit(
        cluster_key="firms:geo:48.0:37.8", detector_id="firms",
        incident_kind="firms.cluster", title="FIRMS cluster ignited · 3 detections",
        severity="high", coords=(48.0, 37.8), location="",
        sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
        layer_hints_to_merge=["firms", "auto_promoter:v1", "cluster:firms:geo:48.0:37.8"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
        contributing_signal_ids=["a", "b", "c"],
    )
    from dataclasses import replace

    retry_hit = replace(
        hit,
        title="FIRMS follow-up",
        timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="observation", text="d"),
        contributing_signal_ids=["b", "c", "d"],
    )
    await store.handle(hit, incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == []
    assert "firms:geo:48.0:37.8" not in store._reserving  # noqa: SLF001

    await store.handle(retry_hit, incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert len(incident_store.records) == 1
    assert incident_store.ids[0] == incident_store.ids[1]
    request = incident_store.requests[1]
    assert request.title == "FIRMS cluster ignited · 3 detections"
    assert request.sources == ["FIRMS · VIIRS_SNPP_NRT"]
    assert request.layer_hints == ["firms", "auto_promoter:v1", "cluster:firms:geo:48.0:37.8"]
    state = store.get_by_cluster_key(hit.cluster_key)
    assert state is not None and state.hit_count == 4
    assert state.contributing_signal_ids == ["a", "b", "c", "d"]
    assert incident_store.records[state.incident_id].timeline[-1].text == "d"
    assert fake_incident_event_stream.types() == ["incident.open", "incident.update"]


@pytest.mark.asyncio
async def test_retry_accumulates_distinct_hits_across_multiple_create_failures(
    fake_clock, fake_incident_event_stream
):
    from uuid import uuid4

    from app.models.incident import Incident, IncidentStatus, IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    class FailTwiceAfterPersist:
        def __init__(self):
            self.calls = []
            self.records = {}

        async def create_incident(self, request, *, incident_id=None):
            incident_id = incident_id or f"inc-{uuid4().hex[:8]}"
            self.calls.append((request, incident_id))
            if incident_id not in self.records:
                self.records[incident_id] = Incident(
                    id=incident_id, kind=request.kind, title=request.title,
                    severity=request.severity, coords=request.coords, location=request.location,
                    status=IncidentStatus.OPEN, trigger_ts=fake_clock(),
                    sources=list(request.sources), layer_hints=list(request.layer_hints),
                    timeline=[IncidentTimelineEvent(
                        t_offset_s=0, kind="trigger", text=request.initial_text or ""
                    )],
                )
            if len(self.calls) <= 3:
                raise RuntimeError("commit acknowledgement lost")
            return self.records[incident_id]

        async def apply_signal_update(
            self, incident_id, *, timeline_event, severity, sources_to_merge,
            layer_hints_to_merge,
        ):
            current = self.records[incident_id]
            updated = current.model_copy(update={
                "timeline": [*current.timeline, timeline_event],
                "severity": severity,
                "sources": list(dict.fromkeys([*current.sources, *sources_to_merge])),
                "layer_hints": list(dict.fromkeys([*current.layer_hints, *layer_hints_to_merge])),
            })
            self.records[incident_id] = updated
            return updated

    key = "firms:geo:48.0:37.8"
    def make_hit(title: str, ids: list[str], *, kind: str) -> ClusterHit:
        return ClusterHit(
            cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
            title=title, severity="high", coords=(48.0, 37.8), location="",
            sources_to_merge=["FIRMS"],
            layer_hints_to_merge=["firms", "auto_promoter:v1", f"cluster:{key}"],
            timeline_event=IncidentTimelineEvent(t_offset_s=0, kind=kind, text=title),
            contributing_signal_ids=ids,
        )

    store = ClusterStore(clock=fake_clock)
    incident_store = FailTwiceAfterPersist()
    ignition = make_hit("Ignition 3 detections", ["a", "b", "c"], kind="trigger")
    await store.handle(ignition, incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)
    await store.handle(make_hit("follow-up d", ["d"], kind="observation"),
                       incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)
    await store.handle(make_hit("follow-up d", ["d"], kind="observation"),
                       incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)
    await store.handle(make_hit("follow-up e", ["e"], kind="observation"),
                       incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)

    assert len(incident_store.records) == 1
    assert len({incident_id for _request, incident_id in incident_store.calls}) == 1
    assert incident_store.calls[1][0].title == ignition.title
    record = next(iter(incident_store.records.values()))
    assert [event.text for event in record.timeline] == [
        ignition.title, "follow-up d", "follow-up e"
    ]
    state = store.get_by_cluster_key(key)
    assert state is not None
    assert state.contributing_signal_ids == ["a", "b", "c", "d", "e"]
    assert state.hit_count == 5
    assert fake_incident_event_stream.types() == [
        "incident.open", "incident.update", "incident.update"
    ]


@pytest.mark.asyncio
async def test_cancelled_create_releases_reservation_and_reuses_id(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    import asyncio

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    class CancelAfterPersist:
        def __init__(self):
            self.ids = []

        async def create_incident(self, req, *, incident_id=None):
            self.ids.append(incident_id)
            record = await fake_incident_store.create_incident(req, incident_id=incident_id)
            if len(self.ids) == 1:
                raise asyncio.CancelledError
            return record

    store = ClusterStore(clock=fake_clock)
    retry_store = CancelAfterPersist()
    hit = ClusterHit(
        cluster_key="firms:geo:12.0:13.0", detector_id="firms",
        incident_kind="firms.cluster", title="FIRMS ignition", severity="high",
        coords=(12.0, 13.0), location="", sources_to_merge=["FIRMS"],
        layer_hints_to_merge=["auto_promoter:v1"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
        contributing_signal_ids=["a", "b", "c"],
    )
    with pytest.raises(asyncio.CancelledError):
        await store.handle(hit, incident_store=retry_store,
                           incident_event_stream=fake_incident_event_stream)
    assert hit.cluster_key not in store._reserving  # noqa: SLF001
    assert fake_incident_event_stream.types() == []

    await store.handle(hit, incident_store=retry_store,
                       incident_event_stream=fake_incident_event_stream)
    assert retry_store.ids[0] == retry_store.ids[1]
    assert len(fake_incident_store.all()) == 1
    assert fake_incident_event_stream.types() == ["incident.open"]


@pytest.mark.asyncio
async def test_simultaneous_hits_share_one_create_without_early_publication(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    import asyncio

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    entered = asyncio.Event()
    release = asyncio.Event()

    class BarrierStore:
        def __init__(self):
            self.create_count = 0

        async def create_incident(self, req, *, incident_id=None):
            self.create_count += 1
            entered.set()
            await release.wait()
            return await fake_incident_store.create_incident(req, incident_id=incident_id)

    store = ClusterStore(clock=fake_clock)
    barrier_store = BarrierStore()
    hit = ClusterHit(
        cluster_key="firms:geo:14.0:15.0", detector_id="firms",
        incident_kind="firms.cluster", title="FIRMS ignition", severity="high",
        coords=(14.0, 15.0), location="", sources_to_merge=["FIRMS"],
        layer_hints_to_merge=["auto_promoter:v1"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
        contributing_signal_ids=["a", "b", "c"],
    )
    first = asyncio.create_task(store.handle(
        hit, incident_store=barrier_store, incident_event_stream=fake_incident_event_stream
    ))
    await entered.wait()
    await store.handle(hit, incident_store=barrier_store,
                       incident_event_stream=fake_incident_event_stream)
    assert barrier_store.create_count == 1
    assert fake_incident_event_stream.types() == []
    release.set()
    await first
    assert barrier_store.create_count == 1
    assert fake_incident_event_stream.types() == ["incident.open"]


@pytest.mark.asyncio
async def test_cancelled_finalization_wait_releases_reservation(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    import asyncio

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    ready_to_finalize = asyncio.Event()

    class HoldLockAfterPersist:
        async def create_incident(self, req, *, incident_id=None):
            record = await fake_incident_store.create_incident(req, incident_id=incident_id)
            await store._lock.acquire()  # noqa: SLF001
            ready_to_finalize.set()
            return record

    key = "firms:geo:16.0:17.0"
    hit = ClusterHit(
        cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
        title="FIRMS ignition", severity="high", coords=(16.0, 17.0), location="",
        sources_to_merge=["FIRMS"], layer_hints_to_merge=["auto_promoter:v1"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
        contributing_signal_ids=["a", "b", "c"],
    )
    task = asyncio.create_task(store.handle(
        hit, incident_store=HoldLockAfterPersist(),
        incident_event_stream=fake_incident_event_stream,
    ))
    await ready_to_finalize.wait()
    task.cancel()
    store._lock.release()  # noqa: SLF001
    with pytest.raises(asyncio.CancelledError):
        await task
    assert key not in store._reserving  # noqa: SLF001
    assert fake_incident_event_stream.types() == []


@pytest.mark.parametrize(
    ("returned_status", "expected_cluster_status"),
    [("closed", "terminal"), ("promoted", "promoted")],
)
@pytest.mark.asyncio
async def test_terminal_or_promoted_record_is_not_reopened_or_published_as_open(
    fake_clock, fake_incident_event_stream, returned_status, expected_cluster_status
):
    from app.models.incident import IncidentStatus, IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    class TerminalStore:
        def __init__(self):
            self.calls = 0
            self.record = None

        async def create_incident(self, req, *, incident_id=None):
            self.calls += 1
            if self.record is None:
                from app.models.incident import Incident
                self.record = Incident(
                    id=incident_id, kind=req.kind, title=req.title, severity=req.severity,
                    coords=req.coords, location=req.location,
                    status=IncidentStatus(returned_status),
                    trigger_ts=fake_clock(), closed_ts=fake_clock(), sources=list(req.sources),
                    layer_hints=list(req.layer_hints),
                    timeline=[IncidentTimelineEvent(t_offset_s=0, kind="trigger")],
                )
            return self.record

    store = ClusterStore(clock=fake_clock)
    incident_store = TerminalStore()
    key = "firms:geo:18.0:19.0"
    hit = ClusterHit(
        cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
        title="FIRMS ignition", severity="high", coords=(18.0, 19.0), location="",
        sources_to_merge=["FIRMS"], layer_hints_to_merge=["auto_promoter:v1"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
        contributing_signal_ids=["a", "b", "c"],
    )
    await store.handle(hit, incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key(key)
    assert state is not None and state.incident_status == expected_cluster_status
    assert fake_incident_event_stream.types() == []
    await store.handle(hit, incident_store=incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert incident_store.calls == 1
    fake_clock.advance(3600)
    sweep = store.snapshot_for_sweep(quiet_window_sec=60, now=fake_clock())
    assert sweep.stale_open == []
    assert sweep.stale_promoted == [state]


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
