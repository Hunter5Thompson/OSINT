#!/usr/bin/env python3
"""Rebuild the reviewed Mapshaper runtime closure from npm-verified archives."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

SPATIAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = SPATIAL_ROOT / "data/mapshaper-offline-bundle-manifest.json"
DEFAULT_SOURCE_LOCK = REPO_ROOT / "services/backend/data/spatial/source-lock.json"
MAPSHAPER_FILES = frozenset(
    {
        "LICENSE",
        "README.md",
        "bin/mapshaper",
        "mapshaper.js",
        "package.json",
    }
)
MAX_PACKAGE_FILES = 5_000
MAX_PACKAGE_BYTES = 64 * 1024 * 1024


class BundleBuildError(RuntimeError):
    """The upstream closure or deterministic bundle contract is invalid."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild and byte-verify the committed Mapshaper offline bundle."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-lock", type=Path, default=DEFAULT_SOURCE_LOCK)
    parser.add_argument("--npm", default="npm")
    args = parser.parse_args()

    manifest = _json_object(args.manifest)
    expected_bundle_hash = _expected_bundle_hash(args.source_lock, manifest)
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise BundleBuildError("bundle manifest packages must be a non-empty array")

    _require_reproducible_archive_tools()
    npm = shutil.which(args.npm)
    if npm is None:
        raise BundleBuildError(f"npm executable not found: {args.npm}")

    with tempfile.TemporaryDirectory(prefix="odin-mapshaper-bundle-") as temporary:
        temporary_root = Path(temporary)
        downloads = temporary_root / "downloads"
        staging = temporary_root / "staging"
        downloads.mkdir()
        staging.mkdir()

        for raw_package in packages:
            package = _package_record(raw_package)
            archive = _npm_pack(npm, package, downloads=downloads)
            _verify_upstream_archive(archive, package)
            _copy_package_archive(archive, package=package, staging=staging)

        shutil.copyfile(args.manifest, staging / "bundle-manifest.json")
        _normalize_modes(staging, entrypoint=str(manifest.get("entrypoint", "")))
        candidate = temporary_root / "mapshaper-offline.tgz"
        _create_deterministic_archive(staging, candidate)
        actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_bundle_hash):
            raise BundleBuildError(
                "bundle SHA-256 mismatch: "
                f"expected {expected_bundle_hash}, got {actual_hash}"
            )
        _atomic_copy(candidate, args.output)

    print(f"verified sha256:{expected_bundle_hash}  {args.output}")
    return 0


def _json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BundleBuildError(f"expected a JSON object: {path}")
    return payload


def _expected_bundle_hash(source_lock_path: Path, manifest: dict[str, object]) -> str:
    source_lock = _json_object(source_lock_path)
    sources = source_lock.get("sources")
    if not isinstance(sources, list):
        raise BundleBuildError("source lock sources must be an array")
    matching = [
        source
        for source in sources
        if isinstance(source, dict) and source.get("source_id") == "mapshaper"
    ]
    if len(matching) != 1:
        raise BundleBuildError("source lock must contain exactly one mapshaper source")
    source = matching[0]
    if source.get("release") != manifest.get("bundle_release"):
        raise BundleBuildError("source lock and bundle manifest releases differ")
    expected_hash = source.get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise BundleBuildError("source lock has an invalid mapshaper SHA-256")
    return expected_hash


def _package_record(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise BundleBuildError("package manifest entry must be an object")
    required = ("name", "version", "integrity", "license")
    if any(not isinstance(payload.get(key), str) for key in required):
        raise BundleBuildError("package manifest entry is incomplete")
    return {key: str(payload[key]) for key in payload}


def _npm_pack(npm: str, package: dict[str, str], *, downloads: Path) -> Path:
    environment = os.environ.copy()
    environment.update(
        {
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "npm_config_ignore_scripts": "true",
        }
    )
    result = subprocess.run(
        [
            npm,
            "pack",
            f"{package['name']}@{package['version']}",
            "--pack-destination",
            str(downloads),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )
    metadata = json.loads(result.stdout)
    if not isinstance(metadata, list) or len(metadata) != 1:
        raise BundleBuildError(f"unexpected npm pack response for {package['name']}")
    record = metadata[0]
    if not isinstance(record, dict) or record.get("integrity") != package["integrity"]:
        raise BundleBuildError(f"npm integrity metadata mismatch for {package['name']}")
    filename = record.get("filename")
    if not isinstance(filename, str) or PurePosixPath(filename).name != filename:
        raise BundleBuildError(f"unsafe npm archive name for {package['name']}")
    archive = downloads / filename
    if not archive.is_file():
        raise BundleBuildError(f"npm did not create archive for {package['name']}")
    return archive


def _verify_upstream_archive(archive: Path, package: dict[str, str]) -> None:
    payload = archive.read_bytes()
    actual_integrity = "sha512-" + base64.b64encode(
        hashlib.sha512(payload).digest()
    ).decode("ascii")
    if not hmac.compare_digest(actual_integrity, package["integrity"]):
        raise BundleBuildError(f"npm integrity mismatch for {package['name']}")
    if package["name"] == "mapshaper":
        expected_sha256 = package.get("source_sha256")
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is None or not hmac.compare_digest(
            actual_sha256, expected_sha256
        ):
            raise BundleBuildError(
                "mapshaper upstream SHA-256 mismatch: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )


def _copy_package_archive(
    archive_path: Path,
    *,
    package: dict[str, str],
    staging: Path,
) -> None:
    target_root = (
        staging / "mapshaper"
        if package["name"] == "mapshaper"
        else staging / "node_modules" / package["name"]
    )
    target_root.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    seen: set[str] = set()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) > MAX_PACKAGE_FILES:
            raise BundleBuildError(f"package file limit exceeded: {package['name']}")
        for member in members:
            source_path = PurePosixPath(member.name)
            if (
                source_path.is_absolute()
                or ".." in source_path.parts
                or not source_path.parts
                or source_path.parts[0] != "package"
                or not (member.isdir() or member.isfile())
            ):
                raise BundleBuildError(
                    f"unsafe npm archive member: {package['name']}:{member.name}"
                )
            relative = PurePosixPath(*source_path.parts[1:])
            if not relative.parts:
                continue
            relative_name = relative.as_posix()
            if package["name"] == "mapshaper" and relative_name not in MAPSHAPER_FILES:
                continue
            if relative_name in seen:
                raise BundleBuildError(
                    f"duplicate npm archive member: {package['name']}:{relative_name}"
                )
            seen.add(relative_name)
            destination = target_root / Path(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                destination.mkdir(exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise BundleBuildError(
                    f"unreadable npm archive member: {package['name']}:{relative_name}"
                )
            content = source.read(MAX_PACKAGE_BYTES + 1)
            if len(content) != member.size:
                raise BundleBuildError(
                    f"npm archive size mismatch: {package['name']}:{relative_name}"
                )
            total_bytes += len(content)
            if total_bytes > MAX_PACKAGE_BYTES:
                raise BundleBuildError(f"package size limit exceeded: {package['name']}")
            destination.write_bytes(content)


def _normalize_modes(staging: Path, *, entrypoint: str) -> None:
    expected_entrypoint = staging / Path(*PurePosixPath(entrypoint).parts)
    if not expected_entrypoint.is_file():
        raise BundleBuildError(f"bundle entrypoint is missing: {entrypoint}")
    staging.chmod(0o755)
    for path in staging.rglob("*"):
        path.chmod(0o755 if path.is_dir() or path == expected_entrypoint else 0o644)


def _require_reproducible_archive_tools() -> None:
    expected = (("tar", "tar (GNU tar) 1.35"), ("gzip", "gzip 1.12"))
    for executable, expected_first_line in expected:
        path = shutil.which(executable)
        if path is None:
            raise BundleBuildError(f"required archive tool is missing: {executable}")
        result = subprocess.run(
            [path, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout.splitlines()[0] != expected_first_line:
            raise BundleBuildError(
                f"unsupported {executable} version; expected {expected_first_line!r}"
            )


def _create_deterministic_archive(staging: Path, destination: Path) -> None:
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "SOURCE_DATE_EPOCH": "0"})
    subprocess.run(
        [
            "tar",
            "--sort=name",
            "--mtime=@0",
            "--owner=0",
            "--group=0",
            "--numeric-owner",
            "--format=ustar",
            "--use-compress-program=gzip -n -9",
            "-cf",
            str(destination),
            "-C",
            str(staging),
            ".",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}-",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        with source.open("rb") as source_file:
            shutil.copyfileobj(source_file, temporary)
    temporary_path.chmod(0o644)
    os.replace(temporary_path, destination)


if __name__ == "__main__":
    raise SystemExit(main())
