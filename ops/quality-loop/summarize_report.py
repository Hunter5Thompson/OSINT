#!/usr/bin/env python3
"""Create a compact Codex handoff from the latest ODIN quality-loop report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXCLUDED_COVERAGE_PARTS = (
    "/tests/",
    "/test/",
    ".test.",
    "_test.py",
    "/__tests__/",
    ".d.ts",
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _latest_report(log_dir: Path) -> Path:
    reports = sorted(log_dir.glob("report-*.md"), key=lambda path: path.stat().st_mtime)
    if not reports:
        raise FileNotFoundError(f"no report-*.md files found in {log_dir}")
    return reports[-1]


def _clean_command(command_line: str) -> str:
    command = command_line[2:].strip()
    if command.startswith("cd "):
        parts = command.split(" && ", 1)
        if len(parts) == 2:
            return f"cd {parts[0][3:]} && {parts[1]}"
    return command


def _report_context(report: Path) -> tuple[str | None, str | None]:
    current_section: str | None = None
    last_section: str | None = None
    last_command: str | None = None

    for line in report.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip()
        elif line.startswith("$ "):
            last_section = current_section
            last_command = _clean_command(line)

    return last_section, last_command


def _is_production_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith(("tests/", "test/")):
        return False
    return not any(part in normalized for part in EXCLUDED_COVERAGE_PARTS)


def _coverage_py_candidates(path: Path) -> list[tuple[str, float]]:
    report = _load_json(path)
    files = report.get("files", {})
    candidates: list[tuple[str, float]] = []
    if not isinstance(files, dict):
        return candidates

    for file_path, data in files.items():
        if not isinstance(file_path, str) or not _is_production_path(file_path):
            continue
        if not isinstance(data, dict):
            continue
        summary = data.get("summary", {})
        if not isinstance(summary, dict):
            continue
        candidates.append((file_path, float(summary.get("percent_covered", 0.0))))
    return candidates


def _vitest_candidates(path: Path) -> list[tuple[str, float]]:
    report = _load_json(path)
    candidates: list[tuple[str, float]] = []
    for file_path, data in report.items():
        if file_path == "total" or not isinstance(file_path, str):
            continue
        if not _is_production_path(file_path) or not isinstance(data, dict):
            continue
        lines = data.get("lines", {})
        if isinstance(lines, dict):
            candidates.append((file_path, float(lines.get("pct", 0.0))))
    return candidates


def _coverage_candidates(
    log_dir: Path, coverage_paths: list[Path] | None = None
) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    if coverage_paths:
        for coverage_path in coverage_paths:
            if "coverage-summary" in coverage_path.name:
                candidates.extend(_vitest_candidates(coverage_path))
            else:
                candidates.extend(_coverage_py_candidates(coverage_path))
    else:
        for coverage_path in sorted(log_dir.glob("*coverage.json")):
            candidates.extend(_coverage_py_candidates(coverage_path))
        for coverage_path in sorted(log_dir.glob("*coverage-summary.json")):
            candidates.extend(_vitest_candidates(coverage_path))
    return sorted(candidates, key=lambda item: (item[1], item[0]))[:10]


def summarize(
    report: Path,
    log_dir: Path,
    exit_code: int | None,
    coverage_paths: list[Path] | None = None,
) -> str:
    status = "UNKNOWN" if exit_code is None else ("PASS" if exit_code == 0 else "FAIL")
    failed_section, last_command = _report_context(report)
    candidates = _coverage_candidates(log_dir, coverage_paths)

    lines = [
        "# ODIN Quality Loop Codex Handoff",
        "",
        f"Report: {report}",
        f"Status: {status}",
    ]

    if status == "FAIL":
        lines.append(f"Failed section: {failed_section or 'unknown'}")
        lines.append(f"Last command: `{last_command or 'unknown'}`")
        lines.append("First action: reproduce the failing command before changing code.")
    elif last_command:
        lines.append(f"Last command: `{last_command}`")

    lines.extend(["", "## Test Candidates"])
    if candidates:
        for file_path, coverage in candidates:
            lines.append(f"- {file_path}: {coverage:.2f}% lines")
    else:
        lines.append("- No coverage JSON files found yet.")

    lines.extend(
        [
            "",
            "## Working Rule",
            "- Start with the first failing command if status is FAIL.",
            "- Otherwise add meaningful tests for the lowest production files first.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path, default=Path(".quality-loop/logs"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--coverage", action="append", type=Path, default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_dir = args.log_dir
    report = args.report or _latest_report(log_dir)
    print(summarize(report, log_dir, args.exit_code, args.coverage), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
