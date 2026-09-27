"""Promoter shell — startup/shutdown and config gating."""
import asyncio

import pytest

from app.services.incident_promoter.cluster_store import ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.promoter import Promoter


@pytest.fixture
def disabled_config() -> PromoterConfig:
    return PromoterConfig.from_env().__class__(
        **{**PromoterConfig.from_env().__dict__, "enabled": False}
    )


async def test_promoter_request_stop_is_idempotent(fake_clock, disabled_config,
                                                   fake_incident_store,
                                                   fake_incident_event_stream):
    promoter = Promoter(
        signal_stream=None,                       # not used while disabled
        cluster_store=ClusterStore(clock=fake_clock),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=disabled_config,
        clock=fake_clock,
        detectors=[],
    )
    promoter.request_stop()
    promoter.request_stop()    # no exception
    assert promoter.is_stop_requested() is True


async def test_promoter_run_exits_promptly_when_disabled(fake_clock, disabled_config,
                                                        fake_incident_store,
                                                        fake_incident_event_stream):
    promoter = Promoter(
        signal_stream=None,
        cluster_store=ClusterStore(clock=fake_clock),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=disabled_config,
        clock=fake_clock,
        detectors=[],
    )
    # When disabled, run() should return without subscribing or draining.
    await asyncio.wait_for(promoter.run(), timeout=0.5)


async def test_drain_one_processes_a_single_envelope(
    fake_clock, fake_incident_store, fake_incident_event_stream, signal_envelope_factory
):
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    cluster_store = ClusterStore(clock=fake_clock)
    detector = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    cluster_store.add_termination_listener(detector.on_cluster_terminated)

    class _FakeSignalStream:
        def __init__(self):
            self.queue = __import__("asyncio").Queue()
        def subscribe(self):
            return self.queue
        def unsubscribe(self, q): pass

    signal_stream = _FakeSignalStream()

    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=cluster_store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001

    url = "https://firms.example/#@20.0,10.0,10z"
    for _ in range(3):
        await signal_stream.queue.put(
            signal_envelope_factory(source="firms", url=url)
        )
    # drain 3 envelopes: 2 None, 1 ignition
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001

    assert fake_incident_event_stream.types() == ["incident.open"]


async def test_rehydrate_then_subscribe_avoids_double_create(
    fake_clock, fake_incident_store, fake_incident_event_stream, signal_envelope_factory
):
    """Spec §9.2 #6 — buffer fills during rehydrate; first signal updates, not creates."""
    from app.models.incident import (
        IncidentCreateRequest,
    )
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    # Pre-seed an owned open incident at the FIRMS bucket we'll hit
    await fake_incident_store.create_incident(
        IncidentCreateRequest(
            title="FIRMS cluster ignited · 3 detections in firms:geo:10.0:20.0",
            kind="firms.cluster",
            severity="high",
            coords=(10.0, 20.0),
            layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:10.0:20.0"],
            initial_text="seed",
        )
    )

    cluster_store = ClusterStore(clock=fake_clock)
    detector = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    cluster_store.add_termination_listener(detector.on_cluster_terminated)

    class _FakeSignalStream:
        def __init__(self):
            self.queue = __import__("asyncio").Queue()
        def subscribe(self):
            return self.queue
        def unsubscribe(self, q): pass

    signal_stream = _FakeSignalStream()
    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=cluster_store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001
    # Enqueue a matching FIRMS envelope BEFORE rehydrate completes
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@20.0,10.0,10z")
    )
    await promoter._rehydrate()  # noqa: SLF001
    # The pre-seeded incident is in the store; queued envelope is post-ignition update
    # The detector hasn't accumulated 3 yet → still None. So no event is emitted.
    await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == []
    # Now drive accumulation to ignition — but detector treats this as a fresh bucket,
    # so it takes 2 more signals before emitting an ignition for the SAME cluster_key.
    # Once it does, ClusterStore sees an existing cluster (rehydrated) → UPDATE.
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@20.0,10.0,10z")
    )
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@20.0,10.0,10z")
    )
    await promoter._drain_one()  # noqa: SLF001
    await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.update"]
    assert all(t != "incident.open" for t in fake_incident_event_stream.types())


async def test_poison_owned_row_blocks_drain_for_its_cluster(
    fake_clock, fake_incident_event_stream
):
    from types import SimpleNamespace

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.detectors.base import ClusterHit

    class SignalStream:
        def __init__(self):
            self.queue = asyncio.Queue()

        def subscribe(self):
            return self.queue

        def unsubscribe(self, queue):
            assert queue is self.queue

    class Detector:
        id = "firms"
        enabled = True

        def detect(self, _envelope):
            return ClusterHit(
                cluster_key="firms:geo:9:9", detector_id="firms",
                incident_kind="firms.cluster", title="poison", severity="high",
                coords=(9, 9), location="", sources_to_merge=[],
                layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:9:9"],
                timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
                contributing_signal_ids=["signal-1"],
            )

        def on_cluster_terminated(self, _cluster_key):
            pass

    class Store:
        creates = 0

        async def list_owned_for_rehydrate(self):
            return SimpleNamespace(incidents=[], degraded=True, invalid_rows=1)

        async def create_incident(self, *_args, **_kwargs):
            self.creates += 1
            raise AssertionError("drain must not promote before clean rehydration")

    stream = SignalStream()
    await stream.queue.put(object())
    store = Store()
    promoter = Promoter(
        signal_stream=stream,
        cluster_store=ClusterStore(clock=fake_clock),
        incident_store=store,
        incident_event_stream=fake_incident_event_stream,
        config=PromoterConfig.from_env(),
        clock=fake_clock,
        detectors=[Detector()],
    )

    await promoter.run()

    assert stream.queue.qsize() == 1
    assert store.creates == 0


async def test_sweeper_closes_stale_open_and_drops_promoted(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.base import ClusterHit
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    store = ClusterStore(clock=fake_clock)

    # Seed two clusters via real handle() paths
    hit_open = ClusterHit(
        cluster_key="firms:geo:4.0:4.0", detector_id="firms",
        incident_kind="firms.cluster", title="seed", severity="high",
        coords=(4.0, 4.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:4.0:4.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    hit_prom = ClusterHit(
        cluster_key="firms:geo:5.0:5.0", detector_id="firms",
        incident_kind="firms.cluster", title="seed2", severity="high",
        coords=(5.0, 5.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:5.0:5.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["y"],
    )
    await store.handle(hit_open, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    await store.handle(hit_prom, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    # Promote second — mirror the real /promote router: write PROMOTED to DB
    # AND flip the in-memory ClusterStore state.
    promoted_state = store.get_by_cluster_key("firms:geo:5.0:5.0")
    from app.models.incident import IncidentStatus
    await fake_incident_store.close_incident(promoted_state.incident_id, IncidentStatus.PROMOTED)
    promoted_state.incident_status = "promoted"

    # Both clusters are last_signal_ts == now; advance past quiet window
    fake_clock.advance(cfg.quiet_window_sec + 60)

    promoter = Promoter(
        signal_stream=None,
        cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[],
    )
    await promoter._sweep_once()  # noqa: SLF001

    # incident.open × 2 then incident.close × 1 (only for stale_open)
    assert fake_incident_event_stream.types().count("incident.close") == 1
    # Both clusters are gone from the store
    assert store.get_by_cluster_key("firms:geo:4.0:4.0") is None
    assert store.get_by_cluster_key("firms:geo:5.0:5.0") is None
    # The promoted incident is still PROMOTED in the fake store (not CLOSED)
    promoted_record = next(
        i for i in fake_incident_store.all() if i.title == "seed2"
    )
    from app.models.incident import IncidentStatus
    assert promoted_record.status == IncidentStatus.PROMOTED


@pytest.mark.parametrize(
    ("database_status", "expected_local", "expected_present"),
    [
        ("closed", None, False),
        ("promoted", "promoted", True),
        ("silenced", "terminal", True),
        ("missing", None, False),
    ],
)
@pytest.mark.asyncio
async def test_sweeper_syncs_terminal_race_without_false_close_or_listener_reset(
    fake_clock, fake_incident_store, fake_incident_event_stream,
    database_status, expected_local, expected_present,
):
    from app.models.incident import IncidentStatus, IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.base import ClusterHit
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    store = ClusterStore(clock=fake_clock)
    key = "firms:geo:7.0:7.0"
    hit = ClusterHit(
        cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
        title="sweeper race", severity="high", coords=(7.0, 7.0), location="",
        sources_to_merge=[], layer_hints_to_merge=["auto_promoter:v1"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key(key)
    assert state is not None
    terminated: list[tuple[str, object]] = []
    store.add_termination_listener(
        lambda cluster_key, suppress_until=None: terminated.append(
            (cluster_key, suppress_until)
        )
    )
    if database_status == "missing":
        fake_incident_store._by_id.pop(state.incident_id)
    else:
        terminal_status = IncidentStatus(database_status)
        await fake_incident_store.close_incident(state.incident_id, terminal_status)
    fake_clock.advance(cfg.quiet_window_sec + 1)
    promoter = Promoter(
        signal_stream=None, cluster_store=store, incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream, config=cfg, clock=fake_clock,
        detectors=[],
    )

    await promoter._sweep_once()  # noqa: SLF001

    local = store.get_by_cluster_key(key)
    assert (local is not None) is expected_present
    if local is not None:
        assert local.incident_status == expected_local
    assert fake_incident_event_stream.types().count("incident.close") == 0
    if database_status in {"closed", "missing"}:
        assert terminated == [(key, None)]
    else:
        assert terminated == []
    assert store.cooldowns() == {}


@pytest.mark.asyncio
async def test_late_sweeper_not_found_cannot_drop_replacement_cluster(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    import asyncio
    from dataclasses import replace

    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.base import ClusterHit
    from app.services.incident_promoter.promoter import Promoter
    from app.services.incident_store import MutationResult

    cfg = PromoterConfig.from_env()
    store = ClusterStore(clock=fake_clock)
    key = "firms:geo:8.0:8.0"
    hit = ClusterHit(
        cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
        title="old sweeper state", severity="high", coords=(8.0, 8.0), location="",
        sources_to_merge=[], layer_hints_to_merge=["auto_promoter:v1"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    old_state = store.get_by_cluster_key(key)
    assert old_state is not None
    fake_clock.advance(cfg.quiet_window_sec + 1)
    entered = asyncio.Event()
    release = asyncio.Event()

    class DelayedMissingStore:
        async def close_incident(self, *_args, **_kwargs):
            entered.set()
            await release.wait()
            return MutationResult("not_found", None)

    promoter = Promoter(
        signal_stream=None, cluster_store=store, incident_store=DelayedMissingStore(),
        incident_event_stream=fake_incident_event_stream, config=cfg, clock=fake_clock,
        detectors=[],
    )
    sweep_task = asyncio.create_task(promoter._sweep_once())  # noqa: SLF001
    await asyncio.wait_for(entered.wait(), timeout=1)
    await store.drop_cluster(key, expected_incident_id=old_state.incident_id)
    await store.handle(
        replace(hit, title="replacement sweeper state", contributing_signal_ids=["new"]),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
    )
    replacement = store.get_by_cluster_key(key)
    assert replacement is not None and replacement.incident_id != old_state.incident_id
    release.set()
    await sweep_task

    assert store.get_by_cluster_key(key).incident_id == replacement.incident_id


async def test_rehydrate_preserves_detector_id_for_escalation(
    fake_clock, fake_incident_store, fake_incident_event_stream, signal_envelope_factory
):
    """C1 regression: rehydrated ClusterState.detector_id must be the leading segment
    of cluster_key (e.g. 'telegram'), not the second segment (e.g. 'topic')."""
    from app.models.incident import IncidentCreateRequest
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    cluster_store = ClusterStore(clock=fake_clock)

    # Pre-seed an owned open telegram incident
    await fake_incident_store.create_incident(
        IncidentCreateRequest(
            title="Telegram cluster · 3 matching posts",
            kind="telegram.burst",
            severity="elevated",
            coords=(0.0, 0.0),
            layer_hints=["telegram", "auto_promoter:v1",
                         "cluster:telegram:topic:abc123"],
            initial_text="seed",
        )
    )

    promoter = Promoter(
        signal_stream=None,
        cluster_store=cluster_store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[],
    )
    await promoter._rehydrate()  # noqa: SLF001

    state = cluster_store.get_by_cluster_key("telegram:topic:abc123")
    assert state is not None
    # detector_id must be "telegram" — the leading segment — not "topic"
    assert state.detector_id == "telegram", (
        f"detector_id should be 'telegram' to drive escalation curves; "
        f"got {state.detector_id!r}"
    )
