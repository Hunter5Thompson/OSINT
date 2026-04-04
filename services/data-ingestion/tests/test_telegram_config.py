"""Tests for Telegram + Vision configuration fields."""

from config import Settings


def test_telegram_defaults():
    """Verify Telegram config defaults are sane."""
    s = Settings(neo4j_password="test")
    assert s.telegram_api_id == 0
    assert s.telegram_api_hash == ""
    assert s.telegram_session_path == "/data/telegram/odin"
    assert s.telegram_media_path == "/data/telegram/media"
    assert s.telegram_media_max_size == 20_971_520
    assert s.telegram_channels_config == "feeds/telegram_channels.yaml"
    assert s.telegram_base_interval == 300
    assert s.telegram_max_interval == 1800


def test_vision_defaults():
    """Verify Vision config defaults are sane."""
    s = Settings(neo4j_password="test")
    assert s.vision_vllm_url == "http://localhost:8011"
    assert s.vision_vllm_model == "qwen-vl"
    assert s.vision_queue_name == "vision:pending"
    assert s.vision_queue_max_pending == 100
    assert s.vision_dead_letter_queue == "vision:dead_letter"


def test_telegram_env_override(monkeypatch):
    """Telegram settings are overridable via environment."""
    monkeypatch.setenv("TELEGRAM_API_ID", "99999")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc123")
    monkeypatch.setenv("TELEGRAM_BASE_INTERVAL", "120")
    s = Settings(neo4j_password="test")
    assert s.telegram_api_id == 99999
    assert s.telegram_api_hash == "abc123"
    assert s.telegram_base_interval == 120
