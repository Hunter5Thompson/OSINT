"""Unit tests for FIRMSGeoClusterDetector helpers."""
import pytest

from app.services.incident_promoter.detectors.firms import (
    _bucket_key,
    _parse_firms_coords,
)


def test_parse_firms_coords_happy():
    url = "https://firms.modaps.eosdis.nasa.gov/map/#d:2026-05-19;@35.0903,51.6177,10z"
    assert _parse_firms_coords(url) == (35.0903, 51.6177)


def test_parse_firms_coords_negative():
    url = "https://firms.example/#d:2026-05-19;@-22.5,-44.1,8z"
    assert _parse_firms_coords(url) == (-22.5, -44.1)


@pytest.mark.parametrize("url", ["", "no-pattern-here", "@bad,format", None])
def test_parse_firms_coords_returns_none_on_malformed(url):
    assert _parse_firms_coords(url) is None


def test_bucket_key_rounds_to_one_decimal():
    assert _bucket_key(48.012, 37.823, deg=0.1) == "firms:geo:48.0:37.8"


def test_bucket_key_handles_negative_lon():
    assert _bucket_key(48.0, -37.86, deg=0.1) == "firms:geo:48.0:-37.9"


def _firms_envelope(signal_envelope_factory, lat=35.09, lon=51.62, **kw):
    url = kw.pop(
        "url",
        f"https://firms.modaps.eosdis.nasa.gov/map/#d:2026-05-19;@{lat},{lon},10z",
    )
    return signal_envelope_factory(source="firms", url=url, **kw)


def test_firms_detector_returns_none_before_threshold(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)

    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    # 2 signals accumulated, no emit yet
    assert det._buckets["firms:geo:35.1:51.6"].signals  # noqa: SLF001


def test_firms_detector_ignores_non_firms_source(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    env = signal_envelope_factory(
        source="rss",
        url="https://example.com/some-rss-item",
    )
    assert det.detect(env) is None
    assert not det._buckets  # noqa: SLF001


def test_firms_detector_ignores_malformed_url(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    env = signal_envelope_factory(source="firms", url="no-coords-here")
    assert det.detect(env) is None
    assert not det._buckets  # noqa: SLF001


def test_firms_detector_ignites_at_min_hits_with_summary_text(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()  # firms_min_hits=3 by default
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)

    env1 = _firms_envelope(signal_envelope_factory)
    env2 = _firms_envelope(signal_envelope_factory)
    env3 = _firms_envelope(signal_envelope_factory)

    assert det.detect(env1) is None
    assert det.detect(env2) is None
    hit = det.detect(env3)
    assert hit is not None
    assert hit.detector_id == "firms"
    assert hit.cluster_key == "firms:geo:35.1:51.6"
    assert hit.severity == "high"
    assert hit.coords == (35.09, 51.62)
    assert hit.incident_kind == "firms.cluster"
    assert "auto_promoter:v1" in hit.layer_hints_to_merge
    assert any(h.startswith("cluster:") for h in hit.layer_hints_to_merge)
    # Ignition summary text — single timeline entry referencing the count
    assert "3 detection" in hit.title.lower()
    assert hit.timeline_event.kind == "trigger"
    assert hit.timeline_event.text == hit.title
    assert len(hit.contributing_signal_ids) == 3
    assert hit.contributing_signal_ids[-1] == env3.event_id
    # Detector marks the bucket as ignited so the next signal is an update
    assert det._buckets[hit.cluster_key].ignited is True  # noqa: SLF001


def test_firms_detector_emits_update_after_ignition(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    for _ in range(3):
        det.detect(_firms_envelope(signal_envelope_factory))

    env4 = _firms_envelope(signal_envelope_factory)
    fake_clock.advance(60)
    hit = det.detect(env4)
    assert hit is not None
    assert hit.timeline_event.kind == "observation"
    assert hit.contributing_signal_ids == [env4.event_id]
    assert hit.severity == "high"  # detector itself never de-escalates
