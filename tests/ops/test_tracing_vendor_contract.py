"""Keep independent service packages on one explicit reporter source version."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_service_reporters_match_the_canonical_vendored_source():
    canonical = (ROOT / "vendor/spark-trace-reporter/spark_trace_reporter.py").read_bytes()
    for service in ("intelligence", "data-ingestion"):
        assert (ROOT / f"services/{service}/spark_trace_reporter.py").read_bytes() == canonical
