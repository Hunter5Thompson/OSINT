from gdelt_raw.config import GDELTSettings


def test_defaults_loadable():
    s = GDELTSettings(_env_file=None)
    assert s.base_url == "http://data.gdeltproject.org/gdeltv2"
    assert s.forward_interval_seconds == 900
    assert s.parquet_path == "/data/gdelt"
    assert s.filter_mode == "alpha"
    assert s.cameo_root_allowlist == [15, 18, 19, 20]
    assert "ARMEDCONFLICT" in s.theme_allowlist
    assert "NUCLEAR" in s.theme_allowlist
    assert s.max_parse_error_pct == 5.0
    assert s.backfill_parallel_slices == 4


def test_allowlist_parses_from_csv_env(monkeypatch):
    monkeypatch.setenv("GDELT_CAMEO_ROOT_ALLOWLIST", "18,19")
    monkeypatch.setenv("GDELT_THEME_ALLOWLIST", "ARMEDCONFLICT,NUCLEAR")
    s = GDELTSettings()
    assert s.cameo_root_allowlist == [18, 19]
    assert s.theme_allowlist == ["ARMEDCONFLICT", "NUCLEAR"]
