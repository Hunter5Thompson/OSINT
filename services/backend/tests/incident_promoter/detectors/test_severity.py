"""Unit tests for Severity Burst detector."""


def test_severity_disabled_by_default(fake_clock, signal_envelope_factory):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    assert cfg.severity_enabled is False
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    for _ in range(10):
        env = signal_envelope_factory(severity="high")
        assert det.detect(env) is None


def test_severity_ignition_at_min_hits_with_non_spatial(fake_clock, signal_envelope_factory,
                                                       monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    # 4 high signals — pre-trigger
    for _ in range(4):
        assert det.detect(signal_envelope_factory(severity="high", source="rss")) is None
    hit = det.detect(signal_envelope_factory(severity="high", source="telegram"))
    assert hit is not None
    assert hit.cluster_key == "severity:global"
    assert hit.coords is None
    assert hit.severity == "high"
    assert "auto_promoter:v1" in hit.layer_hints_to_merge


def test_severity_low_signals_do_not_count(fake_clock, signal_envelope_factory, monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    for _ in range(10):
        assert det.detect(signal_envelope_factory(severity="low")) is None
    assert not det._buckets["severity:global"].signals  # noqa: SLF001


def test_severity_on_cluster_terminated_resets(fake_clock, signal_envelope_factory, monkeypatch):
    from datetime import timedelta
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    for _ in range(5):
        det.detect(signal_envelope_factory(severity="high"))
    until = fake_clock() + timedelta(hours=1)
    det.on_cluster_terminated("severity:global", suppress_until=until)
    for _ in range(5):
        assert det.detect(signal_envelope_factory(severity="high")) is None
    fake_clock.advance(3601)
    # Restart accumulation
    for _ in range(4):
        assert det.detect(signal_envelope_factory(severity="high")) is None
    assert det.detect(signal_envelope_factory(severity="high")) is not None
