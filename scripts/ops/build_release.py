"""Build reviewed app contexts from a clean Git commit; never deploy or publish."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SERVICES = {
    "vision-enrichment": ("services/vision-enrichment", "Dockerfile"),
    "backend": ("services/backend", "Dockerfile"),
    "frontend": ("services/frontend", "Dockerfile"),
    "intelligence": ("services/intelligence", "Dockerfile"),
    "data-ingestion": ("", "services/data-ingestion/Dockerfile"),
}


def clean_revision(root: Path, *, runner=subprocess.run) -> str:
    revision = runner(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise ValueError("Invalid full Git revision")
    status = runner(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise ValueError(
            "Release build requires a clean tracked and untracked source tree"
        )
    return revision


def make_plan(path: Path, services: list[str], *, runner=subprocess.run) -> dict:
    root = Path(
        runner(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    ).resolve()
    revision = clean_revision(root, runner=runner)
    if (
        not services
        or len(set(services)) != len(services)
        or any(s not in SERVICES for s in services)
    ):
        raise ValueError("Choose distinct supported application services")
    images = []
    for service in services:
        context, dockerfile = SERVICES[service]
        tag = f"odin-release-build:{service}-{revision}"
        images.append(
            {
                "service": service,
                "tag": tag,
                "context": context or ".",
                "archive_command": [
                    "git",
                    "archive",
                    "--format=tar",
                    revision + (":" + context if context else ""),
                ],
                "build_command": [
                    "docker",
                    "build",
                    "--tag",
                    tag,
                    "--file",
                    dockerfile,
                    "--build-arg",
                    "ODIN_BUILD_REVISION=" + revision,
                    "--build-arg",
                    "VITE_SPATIAL_SCOPE_ENABLED=true",
                    "-",
                ],
            }
        )
    return {
        "schema_version": 1,
        "source_root": str(root),
        "revision": revision,
        "images": images,
    }


def build_plan(plan: dict, artifacts: Path, *, runner=subprocess.run) -> dict:
    root = Path(plan["source_root"])
    revision = plan["revision"]
    artifacts = artifacts.resolve()
    if artifacts == root or root in artifacts.parents:
        raise ValueError("Build artifacts must be outside the source checkout")
    if clean_revision(root, runner=runner) != revision:
        raise ValueError("Git revision changed after the build plan")
    artifacts.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema_version": 1,
        "revision": revision,
        "source": "git-archive",
        "release_qualified": False,
        "images": [],
    }
    for image in plan["images"]:
        if clean_revision(root, runner=runner) != revision:
            raise ValueError("Git revision changed before image build")
        archive = runner(
            image["archive_command"], cwd=root, check=True, capture_output=True
        ).stdout
        if not isinstance(archive, bytes) or not archive:
            raise ValueError("Empty committed build context")
        path = artifacts / (image["service"] + ".context.tar")
        with path.open("xb") as stream:
            stream.write(archive)
        # Docker only receives this immutable committed archive, never the checkout.
        runner(
            image["build_command"],
            cwd=root,
            input=archive,
            check=True,
            capture_output=True,
        )
        if clean_revision(root, runner=runner) != revision:
            raise ValueError("Git source changed during the image build")
        raw = runner(
            ["docker", "image", "inspect", image["tag"]],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        info = json.loads(raw)
        if (
            not isinstance(info, list)
            or len(info) != 1
            or not isinstance(info[0], dict)
        ):
            raise ValueError("Invalid image inspect response")
        info = info[0]
        labels = (info.get("Config") or {}).get("Labels") or {}
        if labels.get("org.opencontainers.image.revision") != revision:
            raise ValueError(
                "Image revision label does not match committed build source"
            )
        identifier = info.get("Id")
        if not isinstance(identifier, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", identifier
        ):
            raise ValueError("Invalid local image identity")
        receipt["images"].append(
            {
                "service": image["service"],
                "tag": image["tag"],
                "image_id": identifier,
                "context": image["context"],
                "context_bytes": len(archive),
                "context_sha256": hashlib.sha256(archive).hexdigest(),
            }
        )
    with (artifacts / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return receipt


def main() -> int:
    if any(
        name in os.environ for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")
    ):
        print(
            "Release build rejected: Git override environment is not supported",
            file=sys.stderr,
        )
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", action="append", choices=tuple(SERVICES))
    parser.add_argument(
        "--build",
        action="store_true",
        help="Explicitly execute the committed image build",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        help="New artifact directory outside the checkout, under /data",
    )
    args = parser.parse_args()
    if args.build and args.artifacts is None:
        parser.error("--build requires --artifacts")
    if (
        args.artifacts is not None
        and Path("/data") not in args.artifacts.resolve().parents
    ):
        parser.error("Keep build artifacts under /data")
    try:
        plan = make_plan(
            Path(__file__).resolve().parents[2], args.service or list(SERVICES)
        )
        result = build_plan(plan, args.artifacts) if args.build else plan
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        print("Release build rejected: " + message, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
