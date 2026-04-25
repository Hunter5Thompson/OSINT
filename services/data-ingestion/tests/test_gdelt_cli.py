from click.testing import CliRunner

from gdelt_raw.cli import main


def test_cli_help():
    runner = CliRunner()
    res = runner.invoke(main, ["--help"])
    assert res.exit_code == 0
    assert "status" in res.output
    assert "forward" in res.output
    assert "backfill" in res.output
    assert "resume" in res.output
    assert "doctor" in res.output


def test_cli_backfill_requires_from_flag():
    runner = CliRunner()
    res = runner.invoke(main, ["backfill"])
    assert res.exit_code != 0
    assert "--from" in res.output or "Missing" in res.output


def test_cli_config_dumps_settings():
    runner = CliRunner()
    res = runner.invoke(main, ["config"])
    assert res.exit_code == 0
    assert "base_url" in res.output or "BASE_URL" in res.output
