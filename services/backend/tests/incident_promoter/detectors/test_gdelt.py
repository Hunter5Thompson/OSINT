"""Unit tests for GDELT skeleton — default-off behavior only."""
from __future__ import annotations


def test_gdelt_disabled_by_default_returns_none(fake_clock, signal_envelope_factory):
    """Verify GDELT is disabled and returns None for all signals."""
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.gdelt import GDELTToneSpikeDetector

    cfg = PromoterConfig.from_env()
    assert cfg.gdelt_enabled is False

    det = GDELTToneSpikeDetector(config=cfg, clock=fake_clock)

    # Feed 10 signals with hypothetical tone fields (would be in a real payload)
    for i in range(10):
        env = signal_envelope_factory(
            source="gdelt",
            title=f"Event {i}",
            extras={
                "actor1_geo_lat": 10.0 + i,
                "actor1_geo_lon": 20.0 + i,
                "tone": -8.5,
                "mention_count": 5,
            },
        )
        assert det.detect(env) is None


def test_gdelt_on_cluster_terminated_is_noop(fake_clock):
    """Verify on_cluster_terminated handles GDELT keys without error."""
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.gdelt import GDELTToneSpikeDetector

    det = GDELTToneSpikeDetector(
        config=PromoterConfig.from_env(), clock=fake_clock
    )

    # Should not raise any exception
    det.on_cluster_terminated("gdelt:geo:10.0:20.0:RUS")
    det.on_cluster_terminated("gdelt:geo:35.1:51.6:IRN")


def test_gdelt_enabled_property_reflects_config(fake_clock):
    """Verify enabled property is derived from config."""
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.gdelt import GDELTToneSpikeDetector

    cfg = PromoterConfig(gdelt_enabled=False)
    det = GDELTToneSpikeDetector(config=cfg, clock=fake_clock)
    assert det.enabled is False

    cfg_enabled = PromoterConfig(gdelt_enabled=True)
    det_enabled = GDELTToneSpikeDetector(config=cfg_enabled, clock=fake_clock)
    assert det_enabled.enabled is True
