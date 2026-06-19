#!/usr/bin/env python3
"""Fail when service coverage drops below the checked-in baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EPSILON = 0.005


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def _coverage_py_metrics(report: dict[str, Any]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    totals = report.get("totals", {})
    files = report.get("files", {})
    metrics = {"lines": float(totals.get("percent_covered", 0.0))}
    file_metrics = {
        path: {"lines": float(data.get("summary", {}).get("percent_covered", 0.0))}
        for path, data in files.items()
    }
    return metrics, file_metrics


def _vitest_summary_metrics(
    report: dict[str, Any],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    total = report.get("total", {})
    metrics = {
        "statements": float(total.get("statements", {}).get("pct", 0.0)),
        "branches": float(total.get("branches", {}).get("pct", 0.0)),
        "functions": float(total.get("functions", {}).get("pct", 0.0)),
        "lines": float(total.get("lines", {}).get("pct", 0.0)),
    }
    file_metrics: dict[str, dict[str, float]] = {}
    for path, data in report.items():
        if path == "total" or not isinstance(data, dict):
            continue
        file_metrics[path] = {
            "statements": float(data.get("statements", {}).get("pct", 0.0)),
            "branches": float(data.get("branches", {}).get("pct", 0.0)),
            "functions": float(data.get("functions", {}).get("pct", 0.0)),
            "lines": float(data.get("lines", {}).get("pct", 0.0)),
        }
    return metrics, file_metrics


def _metrics_for_format(
    report: dict[str, Any], report_format: str
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    if report_format == "coverage.py":
        return _coverage_py_metrics(report)
    if report_format == "vitest-summary":
        return _vitest_summary_metrics(report)
    raise ValueError(f"unsupported format: {report_format}")


def _find_file_metrics(
    file_metrics: dict[str, dict[str, float]], expected_path: str
) -> dict[str, float] | None:
    if expected_path in file_metrics:
        return file_metrics[expected_path]
    suffix = "/" + expected_path
    for path, metrics in file_metrics.items():
        if path.endswith(suffix):
            return metrics
    return None


def _check_metric(
    errors: list[str],
    label: str,
    metric_name: str,
    actual: float,
    expected: float,
) -> None:
    if actual + EPSILON < expected:
        errors.append(
            f"{label} {metric_name} regressed: actual {actual:.2f}% < baseline {expected:.2f}%"
        )


def check_coverage(
    baseline_path: Path,
    service: str,
    report_path: Path,
    report_format: str,
) -> list[str]:
    baseline = _load_json(baseline_path)
    report = _load_json(report_path)

    service_baseline = baseline.get("services", {}).get(service)
    if not isinstance(service_baseline, dict):
        raise ValueError(f"no baseline configured for service: {service}")

    actual_metrics, file_metrics = _metrics_for_format(report, report_format)
    errors: list[str] = []

    for metric_name, expected in service_baseline.get("metrics", {}).items():
        actual = actual_metrics.get(metric_name)
        if actual is None:
            errors.append(f"{service} report missing metric: {metric_name}")
            continue
        _check_metric(errors, service, metric_name, actual, float(expected))

    for file_path, expected_metrics in service_baseline.get("critical_files", {}).items():
        actual_file_metrics = _find_file_metrics(file_metrics, file_path)
        if actual_file_metrics is None:
            errors.append(f"{service} report missing critical file: {file_path}")
            continue
        for metric_name, expected in expected_metrics.items():
            actual = actual_file_metrics.get(metric_name)
            if actual is None:
                errors.append(f"{service} critical file {file_path} missing metric: {metric_name}")
                continue
            _check_metric(errors, f"{service} critical file {file_path}", metric_name, actual, float(expected))

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--format", choices=("coverage.py", "vitest-summary"), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        errors = check_coverage(args.baseline, args.service, args.report, args.format)
    except Exception as exc:
        print(f"coverage ratchet error: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"{args.service} coverage ratchet passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
