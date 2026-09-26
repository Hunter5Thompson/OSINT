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


def test_cli_backfill_accepts_minute_precise_bounds(monkeypatch):
    """A gap rarely starts at midnight; --from/--to must take a slice time."""
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock

    captured = {}

    async def fake_run_backfill(start, end, **kwargs):
        captured["start"], captured["end"] = start, end

    monkeypatch.setattr("gdelt_raw.cli.run_backfill", fake_run_backfill)
    monkeypatch.setattr(
        "gdelt_raw.cli.open_clients",
        AsyncMock(return_value=MagicMock(aclose=AsyncMock())),
    )

    result = CliRunner().invoke(
        main, ["backfill", "--from", "2026-08-14T18:00", "--to", "2026-09-26T10:30"],
    )
    assert result.exit_code == 0, result.output
    assert captured == {
        "start": datetime(2026, 8, 14, 18, 0),
        "end": datetime(2026, 9, 26, 10, 30),
    }
