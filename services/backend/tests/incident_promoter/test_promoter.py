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

    url = "https://firms.example/#@10.0,20.0,10z"
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
        Incident, IncidentCreateRequest, IncidentStatus,
    )
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    # Pre-seed an owned open incident at the FIRMS bucket we'll hit
    seeded = await fake_incident_store.create_incident(
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
        signal_envelope_factory(source="firms", url="https://firms.example/#@10.0,20.0,10z")
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
        signal_envelope_factory(source="firms", url="https://firms.example/#@10.0,20.0,10z")
    )
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@10.0,20.0,10z")
    )
    await promoter._drain_one()  # noqa: SLF001
    await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.update"]
    assert all(t != "incident.open" for t in fake_incident_event_stream.types())


async def test_sweeper_closes_stale_open_and_drops_promoted(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta
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
