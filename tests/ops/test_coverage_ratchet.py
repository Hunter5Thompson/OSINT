"""Tests for the ODIN coverage ratchet checker."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "ops" / "quality-loop" / "check_coverage_ratchet.py"


class CoverageRatchetTests(unittest.TestCase):
    def test_coverage_py_report_passes_when_metrics_match_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            report = tmp_path / "coverage.json"

            baseline.write_text(
                json.dumps(
                    {
                        "services": {
                            "backend": {
                                "metrics": {"lines": 80.0},
                                "critical_files": {"app/cypher/report_write.py": {"lines": 100.0}},
                            }
                        }
                    }
                )
            )
            report.write_text(
                json.dumps(
                    {
                        "totals": {"percent_covered": 80.0},
                        "files": {
                            "app/cypher/report_write.py": {
                                "summary": {"percent_covered": 100.0}
                            }
                        },
                    }
                )
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--baseline",
                    str(baseline),
                    "--service",
                    "backend",
                    "--report",
                    str(report),
                    "--format",
                    "coverage.py",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("backend coverage ratchet passed", result.stdout)

    def test_coverage_py_report_fails_on_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            report = tmp_path / "coverage.json"

            baseline.write_text(
                json.dumps({"services": {"backend": {"metrics": {"lines": 80.0}}}})
            )
            report.write_text(json.dumps({"totals": {"percent_covered": 79.99}}))

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--baseline",
                    str(baseline),
                    "--service",
                    "backend",
                    "--report",
                    str(report),
                    "--format",
                    "coverage.py",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lines regressed", result.stderr)

    def test_vitest_summary_report_checks_multiple_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            report = tmp_path / "coverage-summary.json"

            baseline.write_text(
                json.dumps(
                    {
                        "services": {
                            "frontend": {
                                "metrics": {
                                    "statements": 56.82,
                                    "branches": 44.24,
                                    "functions": 67.06,
                                    "lines": 58.51,
                                }
                            }
                        }
                    }
                )
            )
            report.write_text(
                json.dumps(
                    {
                        "total": {
                            "statements": {"pct": 56.82},
                            "branches": {"pct": 44.24},
                            "functions": {"pct": 67.06},
                            "lines": {"pct": 58.51},
                        }
                    }
                )
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--baseline",
                    str(baseline),
                    "--service",
                    "frontend",
                    "--report",
                    str(report),
                    "--format",
                    "vitest-summary",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("frontend coverage ratchet passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
