def test_fulltext_settings_defaults():
    from config import Settings
    s = Settings()
    assert s.fulltext_enabled is False                 # opt-in, OFF by default
    assert s.crawl4ai_url == "http://localhost:11235"
    assert s.docling_url == "http://localhost:5001"
    assert s.fulltext_min_body_chars == 1500
    assert s.fulltext_min_paragraphs == 3
    assert s.fulltext_chunk_tokens == 650
    assert s.fulltext_chunk_overlap == 100
    assert s.fulltext_max_attempts == 4
    assert s.fulltext_batch_size == 25
    assert s.fulltext_interval_minutes == 60
    assert s.fulltext_rate_limit_per_domain_s == 2.0


def test_fulltext_enabled_env_override(monkeypatch):
    monkeypatch.setenv("FULLTEXT_ENABLED", "true")
    from config import Settings
    assert Settings().fulltext_enabled is True
