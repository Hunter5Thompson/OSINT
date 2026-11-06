"""Runtime key files are private configuration, never report fields."""

from config import Settings


def test_tavily_can_be_enabled_with_a_mounted_private_env_file(tmp_path):
    path = tmp_path / "tavily.env"
    path.write_text("TAVILY_API_KEY=fixture-private-key\n")
    settings = Settings(_env_file=None, tavily_api_key_file=path)
    assert settings.current_search_key.get_secret_value() == "fixture-private-key"
    assert "fixture-private-key" not in settings.model_dump_json()


def test_unreadable_key_file_keeps_local_research_available(tmp_path):
    settings = Settings(_env_file=None, tavily_api_key_file=tmp_path / "absent.env")
    assert settings.current_search_key.get_secret_value() == ""
