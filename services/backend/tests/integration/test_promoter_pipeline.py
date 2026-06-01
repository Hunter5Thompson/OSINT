"""Integration tests — Promoter + ClusterStore + real FIRMS detector + fakes.

Scenarios from spec §9.2: #1 FIRMS pipeline, #4 Promote mid-cluster,
#5 Silence mid-cluster (both layers), #6 Rehydrate-then-subscribe.
Tests #2 (Severity) and #3 (Telegram) live in Phases 5 and 6.
"""
import asyncio
from datetime import timedelta

import pytest

from app.models.incident import IncidentStatus
from app.services.incident_promoter.cluster_store import ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
from app.services.incident_promoter.promoter import Promoter


@pytest.fixture
def cfg(monkeypatch) -> PromoterConfig:
    monkeypatch.setenv("ODIN_PROMOTER_QUIET_WINDOW_SEC", "900")
    monkeypatch.setenv("ODIN_PROMOTER_FIRMS_MIN_HITS", "3")
    return PromoterConfig.from_env()


class _FakeSignalStream:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
    def subscribe(self):
        return self.queue
    def unsubscribe(self, q):
        pass


async def _make_promoter(cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
                         signal_stream):
    detector = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    store = ClusterStore(clock=fake_clock)
    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    store.add_termination_listener(detector.on_cluster_terminated)
    await promoter._subscribe()  # noqa: SLF001
    return promoter, store, detector


async def test_firms_full_pipeline_open_update_close(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #1."""
    signal_stream = _FakeSignalStream()
    promoter, store, _ = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    await promoter._rehydrate()  # noqa: SLF001 — nothing to rehydrate

    url = "https://firms.example/#@1.0,1.0,10z"
    for _ in range(4):
        await signal_stream.queue.put(
            signal_envelope_factory(source="firms", url=url)
        )
    for _ in range(4):
        await promoter._drain_one()  # noqa: SLF001

    types = fake_incident_event_stream.types()
    assert types == ["incident.open", "incident.update"]
    incident = fake_incident_event_stream.published[0][1]
    assert "3 detection" in incident.title.lower()
    assert len(incident.timeline) == 1  # ignition adds a single trigger entry

    # advance past quiet window and sweep
    fake_clock.advance(cfg.quiet_window_sec + 60)
    await promoter._sweep_once()  # noqa: SLF001
    assert fake_incident_event_stream.types()[-1] == "incident.close"
    assert store.get_by_cluster_key("firms:geo:1.0:1.0") is None


async def test_promote_mid_cluster_absorbs_then_drops(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #4."""
    signal_stream = _FakeSignalStream()
    promoter, store, _ = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    await promoter._rehydrate()  # noqa: SLF001

    url = "https://firms.example/#@2.0,2.0,10z"
    for _ in range(3):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.open"]
    incident_id = fake_incident_event_stream.published[0][1].id

    await store.mark_promoted(incident_id)

    for _ in range(2):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(2):
        await promoter._drain_one()  # noqa: SLF001
    # No new SSE frames
    assert fake_incident_event_stream.types() == ["incident.open"]

    fake_clock.advance(cfg.quiet_window_sec + 60)
    await promoter._sweep_once()  # noqa: SLF001
    assert store.get_by_cluster_key("firms:geo:2.0:2.0") is None
    # Promoted incident is NOT auto-closed
    promoted = fake_incident_store.get(incident_id)
    assert promoted is not None and promoted.status == IncidentStatus.OPEN
    # ^ Promoter doesn't write the promoted state to DB itself; the router does.
    #   This test is store-only, so the incident stays OPEN in the fake store.


async def test_silence_drops_at_detector_and_at_store(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #5 — both layers."""
    signal_stream = _FakeSignalStream()
    promoter, store, detector = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    await promoter._rehydrate()  # noqa: SLF001

    url = "https://firms.example/#@3.0,3.0,10z"
    for _ in range(3):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001
    incident_id = fake_incident_event_stream.published[0][1].id
    until = fake_clock() + timedelta(seconds=cfg.silence_cooldown_sec)
    await store.mark_silenced(incident_id, until=until)

    # Layer 1 — detector drops signals silently (returns None, no accumulation)
    for _ in range(5):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(5):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert not detector._buckets  # noqa: SLF001

    # Layer 2 — synthesize a ClusterHit directly and call handle() during cooldown
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.detectors.base import ClusterHit

    synth = ClusterHit(
        cluster_key="firms:geo:3.0:3.0", detector_id="firms",
        incident_kind="firms.cluster", title="bypass", severity="high",
        coords=(3.0, 3.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:3.0:3.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["bypass"],
    )
    await store.handle(synth, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert "firms:geo:3.0:3.0" in store.cooldowns()

    # After cooldown expires, a fresh sequence ignites
    fake_clock.advance(cfg.silence_cooldown_sec + 1)
    for _ in range(3):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types().count("incident.open") == 2


async def test_rehydrate_then_subscribe_does_not_double_create(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #6 — see existing test in tests/incident_promoter/test_promoter.py."""
    # This is a thinner integration variant that exercises the full Promoter.run
    # composition (subscribe → enqueue → rehydrate → drain) end-to-end.
    from app.models.incident import IncidentCreateRequest

    await fake_incident_store.create_incident(
        IncidentCreateRequest(
            title="FIRMS cluster ignited · 3 detections in firms:geo:6.0:6.0",
            kind="firms.cluster",
            severity="high",
            coords=(6.0, 6.0),
            layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:6.0:6.0"],
            initial_text="seed",
        )
    )

    signal_stream = _FakeSignalStream()
    promoter, store, _ = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    # signal arrives BEFORE rehydrate finishes
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@6.0,6.0,10z")
    )
    await promoter._rehydrate()  # noqa: SLF001
    # drain — first FIRMS signal is pre-trigger (accumulation), no event yet
    await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == []
    # 2 more signals → 3rd is detector-ignition, but ClusterStore sees rehydrated key
    for _ in range(2):
        await signal_stream.queue.put(
            signal_envelope_factory(source="firms", url="https://firms.example/#@6.0,6.0,10z")
        )
    for _ in range(2):
        await promoter._drain_one()  # noqa: SLF001
    assert "incident.open" not in fake_incident_event_stream.types()
    assert "incident.update" in fake_incident_event_stream.types()


async def test_telegram_cluster_pipeline(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #3 — Telegram topic cluster + unrelated signal."""
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    detector = TelegramTopicDetector(config=cfg, clock=fake_clock)
    store = ClusterStore(clock=fake_clock)
    store.add_termination_listener(detector.on_cluster_terminated)

    signal_stream = _FakeSignalStream()
    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001
    await promoter._rehydrate()  # noqa: SLF001

    matching = [
        "Strike on Kharkiv overnight powerful explosions reported",
        "Overnight strike on Kharkiv with powerful explosions",
        "Powerful overnight strike on Kharkiv explosions reported",
        "Kharkiv strike overnight powerful explosions",
    ]
    unrelated = "Argentina election results final tally posted"
    for title in matching:
        await signal_stream.queue.put(
            signal_envelope_factory(source="telegram", title=title, url="https://t.me/a/1")
        )
    await signal_stream.queue.put(
        signal_envelope_factory(source="telegram", title=unrelated, url="https://t.me/b/1")
    )
    for _ in range(5):
        await promoter._drain_one()  # noqa: SLF001

    types = fake_incident_event_stream.types()
    assert types.count("incident.open") == 1
    assert types.count("incident.update") == 1
    # unrelated didn't ignite (only 1 hit in its own centroid)


async def test_severity_burst_pipeline_with_map_no_pin(
    monkeypatch, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #2 — severity burst on opt-in flag, coords=(0,0)+map:no_pin."""
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    detector = SeverityBurstDetector(config=cfg, clock=fake_clock)
    store = ClusterStore(clock=fake_clock)
    store.add_termination_listener(detector.on_cluster_terminated)

    signal_stream = _FakeSignalStream()
    promoter = Promoter(
        signal_stream=signal_stream, cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg, clock=fake_clock, detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001
    await promoter._rehydrate()  # noqa: SLF001

    sources = ["rss", "telegram", "firms", "rss", "telegram"]
    for s in sources:
        await signal_stream.queue.put(signal_envelope_factory(source=s, severity="high"))
    for _ in range(5):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.open"]
    incident = fake_incident_event_stream.published[0][1]
    assert incident.coords == (0.0, 0.0)
    assert "map:no_pin" in incident.layer_hints
