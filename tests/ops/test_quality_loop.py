"""Tests for the daily ODIN quality loop assets."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = ROOT / "ops" / "quality-loop"


class QualityLoopTests(unittest.TestCase):
    def test_quality_loop_timer_runs_daily_at_0130(self) -> None:
        timer = (OPS_DIR / "odin-quality-loop.timer").read_text()

        self.assertIn("OnCalendar=*-*-* 01:30:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_quality_loop_service_executes_repo_script_with_ceiling(self) -> None:
        service = (OPS_DIR / "odin-quality-loop.service").read_text()

        self.assertIn("Type=oneshot", service)
        self.assertIn("WorkingDirectory=/home/deadpool-ultra/ODIN/OSINT", service)
        self.assertIn(
            "ExecStart=/home/deadpool-ultra/ODIN/OSINT/ops/quality-loop/"
            "quality_loop.sh",
            service,
        )
        self.assertIn("TimeoutStartSec=7200", service)
        self.assertNotIn("RuntimeMaxSec=", service)

    def test_quality_loop_dry_run_lists_all_service_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = os.environ.copy()
            env["ODIN_QUALITY_LOOP_DRY_RUN"] = "1"
            env["ODIN_QUALITY_LOG_DIR"] = str(tmp_path)
            env["ODIN_QUALITY_STAMP"] = "test"

            result = subprocess.run(
                [str(OPS_DIR / "quality_loop.sh")],
                cwd=ROOT,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

            output = result.stdout
            self.assertIn("ODIN Quality Loop test", output)
            self.assertIn("Coverage mode: ratchet", output)
            self.assertIn("DRY RUN: no commands will be executed", output)
            self.assertIn("services/backend", output)
            self.assertIn("uv sync --all-extras", output)
            self.assertIn("uv run --with pytest-cov pytest --cov=app", output)
            self.assertIn("--cov-report=json:", output)
            self.assertNotIn("--cov-fail-under=100", output)
            self.assertIn("check_coverage_ratchet.py", output)
            self.assertIn("coverage-baseline.json", output)
            self.assertIn("uv run ruff check app/", output)
            self.assertIn("uv run mypy app/", output)
            self.assertIn("services/frontend", output)
            self.assertIn("npm install", output)
            self.assertIn("npm run lint", output)
            self.assertIn("npm run type-check", output)
            self.assertIn("npm test", output)
            self.assertIn("npm run coverage", output)
            self.assertIn("services/intelligence", output)
            self.assertIn("--cov=agents", output)
            self.assertNotIn(
                "services/intelligence && uv run --with pytest-cov pytest --cov=.",
                output,
            )
            self.assertIn("services/data-ingestion", output)
            self.assertIn("--cov=canonicalize", output)
            self.assertNotIn(
                "services/data-ingestion && uv run --with pytest-cov pytest --cov=.",
                output,
            )
            self.assertIn("services/vision-enrichment", output)
            self.assertIn("--cov=consumer", output)
            self.assertNotIn(
                "services/vision-enrichment && uv run --with pytest-cov pytest --cov=.",
                output,
            )
            self.assertIn("./odin.sh smoke", output)

            report = tmp_path / "report-test.md"
            self.assertTrue(report.exists())
            self.assertIn("ODIN Quality Loop test", report.read_text())

            handoff = tmp_path / "handoff-test.md"
            self.assertTrue(handoff.exists())
            handoff_text = handoff.read_text()
            self.assertIn("ODIN Quality Loop Codex Handoff", handoff_text)
            self.assertIn("Status: PASS", handoff_text)
            self.assertIn(f"Handoff: {handoff}", output)

    def test_quality_loop_baseline_tracks_all_services(self) -> None:
        baseline = (OPS_DIR / "coverage-baseline.json").read_text()

        for service in (
            "backend",
            "frontend",
            "intelligence",
            "data-ingestion",
            "vision-enrichment",
        ):
            self.assertIn(f'"{service}"', baseline)

    def test_quality_loop_does_not_publish_failed_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Cover the old and the new per-run filename so this test proves the
            # publication guard independently of the naming migration.
            (tmp_path / "backend-coverage.json").write_text("{broken", encoding="utf-8")
            (tmp_path / "backend-coverage-test.json").write_text(
                "{broken", encoding="utf-8"
            )
            env = os.environ.copy()
            env["ODIN_QUALITY_LOOP_DRY_RUN"] = "1"
            env["ODIN_QUALITY_LOG_DIR"] = str(tmp_path)
            env["ODIN_QUALITY_STAMP"] = "test"

            result = subprocess.run(
                [str(OPS_DIR / "quality_loop.sh")],
                cwd=ROOT,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertFalse((tmp_path / "handoff-test.md").exists())
            self.assertIn("WARNING: handoff generation failed", result.stdout)


if __name__ == "__main__":
    unittest.main()
