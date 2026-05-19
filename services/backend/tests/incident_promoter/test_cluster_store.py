"""Structural tests for ClusterStore (data + listener registration only)."""
from datetime import UTC, datetime

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
