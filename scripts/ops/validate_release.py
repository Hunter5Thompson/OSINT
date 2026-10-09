"""Validate rendered release JSON without printing configuration or secrets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

APP_SERVICES = (
    "backend",
    "frontend",
    "intelligence",
    "data-ingestion",
    "data-ingestion-spark",
    "vision-enrichment",
    "tei-rerank",
)
DATA_TARGETS = {
    "backend": "/app/data",
    "intelligence": "/app/data/spatial",
    "data-ingestion": "/app/data/spatial",
    "data-ingestion-spark": "/app/data/spatial",
}
CHECKOUT = Path(__file__).resolve().parents[2]


def tracing_errors(name: str, service: dict, *, check_paths: bool) -> list[str]:
    environment = service.get("environment", {})
    if not environment.get("SPARK_TRACE_ENDPOINT"):
        return []
    failures = []
    if environment["SPARK_TRACE_ENDPOINT"] != "unix:/run/spark-tracing/ingest.sock":
        failures.append(f"{name}: release tracing requires the local Unix socket")
    if environment.get("SPARK_TRACE_TOKEN_FILE") != "/run/spark-tracing-token":
        failures.append(f"{name}: tracing token must use the reviewed file mount")
    if environment.get("SPARK_TRACE_CAPTURE") not in ("metadata", "text"):
        failures.append(f"{name}: tracing capture must be metadata or text")
    mounts = {mount.get("target"): mount for mount in service.get("volumes", [])}
    for target in ("/run/spark-tracing", "/run/spark-tracing-token"):
        mount = mounts.get(target, {})
        source = Path(mount.get("source", ""))
        if (mount.get("type") != "bind" or not source.is_absolute()
                or not mount.get("read_only")
                or mount.get("bind", {}).get("create_host_path", True)
                or source.resolve().is_relative_to(CHECKOUT)):
            failures.append(f"{name}: tracing requires existing absolute read-only runtime binds")
        elif check_paths:
            exists = source.is_dir() if target == "/run/spark-tracing" else source.is_file()
            if not exists:
                failures.append(f"{name}: reviewed tracing runtime input is missing")
    return failures


def errors(config: dict, *, check_paths: bool = False) -> list[str]:
    """The guard establishes the deployment contract; it is not image attestation."""
    failures = []
    services = config.get("services", {})
    data_sources = {}
    for name in APP_SERVICES:
        service = services.get(name)
        if not isinstance(service, dict):
            failures.append(f"{name}: missing release service")
            continue
        if not re.fullmatch(r"\S+@sha256:[0-9a-f]{64}", service.get("image", "")):
            failures.append(f"{name}: image must use a full sha256 digest")
        if service.get("build") is not None:
            failures.append(f"{name}: local build is forbidden in release mode")
        if service.get("command") is not None or service.get("entrypoint") is not None:
            failures.append(f"{name}: image start command must not be overridden")
        if name in ("intelligence", "data-ingestion", "data-ingestion-spark"):
            failures.extend(tracing_errors(name, service, check_paths=check_paths))
        roots = ("/app",)
        if name == "frontend":
            roots += ("/usr/share/nginx/html", "/etc/nginx")
        data_target = DATA_TARGETS.get(name)
        for mount in service.get("volumes", []):
            target = mount.get("target", "").rstrip("/") or "/"
            if target == data_target:
                source = Path(mount.get("source", ""))
                if (
                    mount.get("type") != "bind"
                    or not source.is_absolute()
                    or not mount.get("read_only")
                    or mount.get("bind", {}).get("create_host_path", True)
                ):
                    failures.append(
                        f"{name}: release data must be an existing absolute read-only bind"
                    )
                elif check_paths and not source.is_dir():
                    failures.append(f"{name}: reviewed release data directory is missing")
                if source.resolve().is_relative_to(CHECKOUT):
                    failures.append(
                        f"{name}: release data must be outside the application checkout"
                    )
                data_sources[name] = source
                continue
            if any(
                target == root
                or target.startswith(root + "/")
                or root.startswith(target.rstrip("/") + "/")
                for root in roots
            ):
                failures.append(f"{name}: mount overrides image code or runtime")
        if data_target and name not in data_sources:
            failures.append(f"{name}: required release data bind is missing")
    backend = data_sources.get("backend")
    if backend is not None:
        for name in DATA_TARGETS:
            if name != "backend" and data_sources.get(name) != backend / "spatial":
                failures.append(f"{name}: spatial data differs from backend release input")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-paths", action="store_true")
    args = parser.parse_args()
    try:
        config = json.load(sys.stdin)
        if not isinstance(config, dict):
            raise TypeError("expected Compose object")
        failures = errors(config, check_paths=args.check_paths)
    except (ValueError, TypeError, AttributeError):
        print("ERROR invalid release Compose JSON", file=sys.stderr)
        return 1
    for failure in failures:
        print(f"ERROR {failure}", file=sys.stderr)
    if failures:
        return 1
    print("OK release images, mounts and data inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
