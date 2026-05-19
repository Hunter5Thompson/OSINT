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
