from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from notebooklm.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestStatus:
    def test_status_empty(self, runner, tmp_path):
        with patch("notebooklm.cli._get_db") as mock_db:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_db.return_value = mock_conn
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "No notebooks" in result.output or "Notebook" in result.output


class TestRetry:
    def test_retry_requires_id_and_phase(self, runner):
        result = runner.invoke(cli, ["retry"])
        assert result.exit_code != 0

    def test_retry_validates_phase(self, runner):
        result = runner.invoke(cli, ["retry", "--id", "nb1", "--phase", "invalid"])
        assert result.exit_code != 0


class TestHealthcheck:
    def test_healthcheck_fails_gracefully(self, runner):
        with patch("notebooklm.cli._check_voxtral", new_callable=AsyncMock, return_value=False):
            result = runner.invoke(cli, ["healthcheck"])
            assert "FAIL" in result.output or result.exit_code != 0
