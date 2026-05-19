"""Unit tests for PromoterConfig env loading."""
from app.services.incident_promoter.config import PromoterConfig


def test_defaults_match_spec(monkeypatch):
    for key in list(monkeypatch.__class__.__init__.__defaults__ or []):
        pass  # no-op; just to keep monkeypatch in scope
    # Clear any env that might bleed in from the shell.
    for key in [
        "ODIN_PROMOTER_ENABLED",
        "ODIN_PROMOTER_FIRMS_ENABLED",
        "ODIN_PROMOTER_FIRMS_MIN_HITS",
        "ODIN_PROMOTER_SEVERITY_ENABLED",
        "ODIN_PROMOTER_GDELT_ENABLED",
        "ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED",
        "ODIN_PROMOTER_QUIET_WINDOW_SEC",
    ]:
        monkeypatch.delenv(key, raising=False)
    cfg = PromoterConfig.from_env()
    assert cfg.enabled is True
    assert cfg.firms_enabled is True
    assert cfg.firms_min_hits == 3
    assert cfg.firms_window_sec == 86_400
    assert cfg.firms_bucket_deg == 0.1
    assert cfg.severity_enabled is False  # default-off in v1
    assert cfg.gdelt_enabled is False  # default-off in v1
    assert cfg.telegram_enabled is True
    assert cfg.telegram_embeddings_enabled is False
    assert cfg.telegram_jaccard_threshold == 0.55
    assert cfg.quiet_window_sec == 900
    assert cfg.sweeper_tick_sec == 60
    assert cfg.silence_cooldown_sec == 3600


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_FIRMS_MIN_HITS", "7")
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    monkeypatch.setenv("ODIN_PROMOTER_QUIET_WINDOW_SEC", "120")
    cfg = PromoterConfig.from_env()
    assert cfg.firms_min_hits == 7
    assert cfg.severity_enabled is True
    assert cfg.quiet_window_sec == 120


def test_enabled_detector_ids(monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    monkeypatch.setenv("ODIN_PROMOTER_GDELT_ENABLED", "false")
    cfg = PromoterConfig.from_env()
    assert set(cfg.enabled_detector_ids()) == {"firms", "severity", "telegram"}
