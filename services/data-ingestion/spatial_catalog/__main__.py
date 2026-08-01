"""Command line entry point for the offline spatial-catalog compiler."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from spatial_catalog.audit import audit_catalog, verify_catalog
from spatial_catalog.compiler import compile_catalog
from spatial_catalog.source_lock import (
    LockedSource,
    SourceLock,
    load_source_lock,
    read_verified_repo_source,
    verify_source_bytes,
)

_MAX_FETCH_BYTES = 128 * 1024 * 1024


def cached_source_path(cache_dir: Path, source: LockedSource) -> Path:
    """Map a grammar-validated source ID to one opaque cache blob."""

    return cache_dir / f"{source.source_id}.source"


def fetch_sources(
    source_lock: SourceLock,
    *,
    cache_dir: Path,
    repo_root: Path,
    downloader: Callable[[LockedSource], bytes] | None = None,
) -> tuple[Path, ...]:
    """The sole network-capable phase; every blob is hashed before publish."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    download = downloader or _download_source
    written: list[Path] = []
    for source in sorted(source_lock.sources, key=lambda item: item.source_id):
        if source.url.startswith("repo:"):
            payload = read_verified_repo_source(source, repo_root=repo_root)
        else:
            payload = download(source)
            verify_source_bytes(source, payload)
        destination = cached_source_path(cache_dir, source)
        _atomic_write(destination, payload)
        written.append(destination)
    return tuple(written)


def read_cached_source[ParsedSource](
    source: LockedSource,
    *,
    cache_dir: Path,
    parser: Callable[[bytes], ParsedSource] | None = None,
) -> bytes | ParsedSource:
    """Read an offline blob and verify its hash before invoking its parser."""

    payload = cached_source_path(cache_dir, source).read_bytes()
    verify_source_bytes(source, payload)
    return payload if parser is None else parser(payload)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m spatial_catalog")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="download locked inputs into an explicit cache")
    fetch.add_argument("--source-lock", type=Path, required=True)
    fetch.add_argument("--cache-dir", type=Path, required=True)
    fetch.add_argument("--repo-root", type=Path)

    build = commands.add_parser("build", help="compile a reviewed immutable catalog offline")
    build.add_argument("--source-lock", type=Path, required=True)
    build.add_argument("--cache-dir", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--policy", choices=("odin-reference-v1",), required=True)

    verify = commands.add_parser("verify", help="verify a published catalog offline")
    verify.add_argument("--catalog", type=Path, required=True)

    audit = commands.add_parser("audit", help="emit a deterministic catalog audit")
    audit.add_argument("--catalog", type=Path, required=True)
    audit.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "fetch":
            source_lock_path: Path = arguments.source_lock
            source_lock = load_source_lock(source_lock_path)
            repo_root = arguments.repo_root or _discover_repo_root(source_lock_path)
            paths = fetch_sources(
                source_lock,
                cache_dir=arguments.cache_dir,
                repo_root=repo_root,
            )
            for path in paths:
                print(path)
            return 0
        if arguments.command == "build":
            return _run_build(arguments)
        if arguments.command == "verify":
            result = verify_catalog(arguments.catalog)
            print(
                f"{result.catalog_revision}: pass "
                f"({result.asset_count} assets, {result.total_bytes} bytes)"
            )
            return 0
        if arguments.command == "audit":
            report = audit_catalog(arguments.catalog)
            _atomic_write(arguments.report, report)
            print(arguments.report)
            return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    parser.error(f"unknown command: {arguments.command}")
    return 2


def _run_build(arguments: argparse.Namespace) -> int:
    source_lock = load_source_lock(arguments.source_lock)
    destination = compile_catalog(
        source_lock=source_lock,
        cache_dir=arguments.cache_dir,
        output_root=arguments.out,
        policy=arguments.policy,
    )
    print(destination)
    return 0


def _download_source(source: LockedSource) -> bytes:
    with (
        httpx.Client(follow_redirects=True, timeout=60.0) as client,
        client.stream("GET", source.url) as response,
    ):
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) > _MAX_FETCH_BYTES:
            raise ValueError(f"SOURCE_TOO_LARGE: {source.source_id}")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > _MAX_FETCH_BYTES:
                raise ValueError(f"SOURCE_TOO_LARGE: {source.source_id}")
            chunks.append(chunk)
    return b"".join(chunks)


def _discover_repo_root(source_lock_path: Path) -> Path:
    for candidate in (source_lock_path.resolve().parent, *source_lock_path.resolve().parents):
        if (candidate / "services" / "data-ingestion" / "spatial_catalog").is_dir():
            return candidate
    raise ValueError("REPO_ROOT_NOT_FOUND: pass --repo-root explicitly")


def _atomic_write(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
