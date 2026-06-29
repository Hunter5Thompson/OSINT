"""Tests for the quality-loop Codex handoff summarizer."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUMMARIZER = ROOT / "ops" / "quality-loop" / "summarize_report.py"


class ReportSummarizerTests(unittest.TestCase):
    def test_failed_report_identifies_section_and_last_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = tmp_path / "report-night.md"
            report.write_text(
                "\n".join(
                    [
                        "# ODIN Quality Loop night",
                        "",
                        "## Backend",
                        "$ cd services/backend && uv run pytest",
                        "backend coverage ratchet passed",
                        "",
                        "## Frontend",
                        "$ cd services/frontend && npm run lint",
                        "GraphCanvas.tsx",
                        "warning  Unused eslint-disable directive",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZER),
                    "--report",
                    str(report),
                    "--log-dir",
                    str(tmp_path),
                    "--exit-code",
                    "1",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Status: FAIL", result.stdout)
            self.assertIn("Failed section: Frontend", result.stdout)
            self.assertIn("Last command: `cd services/frontend && npm run lint`", result.stdout)
            self.assertIn("First action: reproduce the failing command", result.stdout)

    def test_coverage_reports_list_lowest_files_as_test_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = tmp_path / "report-night.md"
            report.write_text("# ODIN Quality Loop night\n\n## Smoke\nok\n", encoding="utf-8")
            (tmp_path / "backend-coverage.json").write_text(
                json.dumps(
                    {
                        "files": {
                            "app/services/high_value.py": {
                                "summary": {"percent_covered": 42.0}
                            },
                            "app/services/already_good.py": {
                                "summary": {"percent_covered": 93.0}
                            },
                            "tests/test_skip.py": {"summary": {"percent_covered": 0.0}},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (tmp_path / "frontend-coverage-summary.json").write_text(
                json.dumps(
                    {
                        "total": {},
                        "src/lib/useful.ts": {"lines": {"pct": 37.5}},
                        "src/lib/useful.test.ts": {"lines": {"pct": 0.0}},
                        "src/lib/covered.ts": {"lines": {"pct": 88.0}},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZER),
                    "--report",
                    str(report),
                    "--log-dir",
                    str(tmp_path),
                    "--exit-code",
                    "0",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("Status: PASS", result.stdout)
            self.assertIn("app/services/high_value.py: 42.00% lines", result.stdout)
            self.assertIn("src/lib/useful.ts: 37.50% lines", result.stdout)
            self.assertNotIn("tests/test_skip.py", result.stdout)
            self.assertNotIn("src/lib/useful.test.ts", result.stdout)

    def test_explicit_coverage_files_ignore_stale_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = tmp_path / "report-current.md"
            report.write_text("# current\n", encoding="utf-8")
            stale = tmp_path / "backend-coverage-old.json"
            current = tmp_path / "backend-coverage-current.json"
            stale.write_text(
                json.dumps(
                    {"files": {"app/stale.py": {"summary": {"percent_covered": 1.0}}}}
                ),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps(
                    {"files": {"app/current.py": {"summary": {"percent_covered": 42.0}}}}
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SUMMARIZER),
                    "--report",
                    str(report),
                    "--log-dir",
                    str(tmp_path),
                    "--coverage",
                    str(current),
                    "--exit-code",
                    "0",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("app/current.py: 42.00% lines", result.stdout)
            self.assertNotIn("app/stale.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
