"""Unit tests for detector base types and timeline build helpers."""
from app.models.incident import IncidentTimelineEvent
from app.services.incident_promoter.detectors.base import (
    ClusterHit,
    build_ignition_timeline_event,
    build_update_timeline_event,
)


def _hit(**overrides) -> ClusterHit:
    defaults: dict = {
        "cluster_key": "firms:geo:48.0:37.8",
        "detector_id": "firms",
        "incident_kind": "firms.cluster",
        "title": "FIRMS cluster ignited · 3 detections in firms:geo:48.0:37.8",
        "severity": "high",
        "coords": (48.0, 37.8),
        "location": "Test bucket",
        "sources_to_merge": ["FIRMS · VIIRS_SNPP_NRT"],
        "layer_hints_to_merge": ["firms", "events", "auto_promoter:v1",
                                 "cluster:firms:geo:48.0:37.8"],
        "timeline_event": IncidentTimelineEvent(
            t_offset_s=0.0, kind="trigger", text="seed", severity="high"
        ),
        "contributing_signal_ids": ["a", "b", "c"],
    }
    defaults.update(overrides)
    return ClusterHit(**defaults)


def test_cluster_hit_is_frozen():
    h = _hit()
    import dataclasses
    assert dataclasses.is_dataclass(h)
    try:
        h.title = "mutated"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ClusterHit must be frozen")


def test_build_ignition_timeline_event_uses_hit_title_and_severity():
    h = _hit()
    ev = build_ignition_timeline_event(h)
    assert ev.t_offset_s == 0.0
    assert ev.kind == "trigger"
    assert ev.text == h.title
    assert ev.severity == h.severity


def test_build_update_timeline_event_uses_hit_title_and_offset():
    h = _hit()
    ev = build_update_timeline_event(h, t_offset_s=180.0)
    assert ev.t_offset_s == 180.0
    assert ev.kind == "observation"
    assert ev.text == h.title
    assert ev.severity == h.severity
