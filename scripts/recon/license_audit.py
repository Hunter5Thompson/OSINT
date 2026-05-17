"""Fail-closed license audit for Skyfall-GS source datasets.

A source group counts as verified only when:
  1. `<licenses_dir>/<slug>.txt` exists and is non-empty (pinned upstream text)
  2. `<licenses_dir>/records.json` has a `records.<source_group>` entry with
     non-empty `slug`, `spdx`, `upstream_url`, `verified_by`, `verified_at`.

Missing or partial verification raises LicenseUnverifiedError. The bootstrap
script catches that and excludes the corresponding scene from the manifest.

JSON (stdlib) is used so the bootstrap has no dependency outside Python
stdlib — runnable from the repo root via `python -m scripts.recon...`.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


_SKYFALL_LINE = (
    "Reconstruction: Skyfall-GS (Lee et al., 2025; arXiv:2510.15869v3) — Apache 2.0."
)


class LicenseUnverifiedError(ValueError):
    """Raised when a scene's source dataset cannot be confirmed as licensed."""


def load_license_records(licenses_dir: Path) -> dict[str, dict[str, Any]]:
    path = Path(licenses_dir) / "records.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text() or "{}")
    return payload.get("records") or {}


def resolve_attribution(*, source_group: str, licenses_dir: Path) -> str:
    records = load_license_records(licenses_dir)
    record = records.get(source_group)
    if record is None:
        raise LicenseUnverifiedError(
            f"no record for source group {source_group!r} in records.json"
        )

    required = ("slug", "spdx", "upstream_url", "verified_by", "verified_at")
    for k in required:
        if not record.get(k):
            raise LicenseUnverifiedError(
                f"record for {source_group!r} missing field {k!r}"
            )

    slug = record["slug"]
    license_file = Path(licenses_dir) / f"{slug}.txt"
    if not license_file.exists():
        raise LicenseUnverifiedError(
            f"license text not found at {license_file} — populate with the "
            f"upstream license text from {record['upstream_url']}"
        )
    if license_file.stat().st_size == 0:
        raise LicenseUnverifiedError(
            f"empty license file at {license_file} — populate with the "
            f"upstream license text from {record['upstream_url']}"
        )

    return (
        f"{_SKYFALL_LINE} "
        f"Source imagery: {source_group} ({record['spdx']}, "
        f"verified {record['verified_at']} by {record['verified_by']}). "
        f"Upstream: {record['upstream_url']}. Local text: {slug}.txt."
    )


def render_licenses_md(licenses_dir: Path) -> str:
    """Emit LICENSES.md content from records.json + on-disk license files."""
    records = load_license_records(licenses_dir)
    lines: list[str] = [
        "# Recon Scene Licenses",
        "",
        "Skyfall-GS model artifacts: Apache 2.0 "
        "(from https://huggingface.co/jayinnn/Skyfall-GS-ply).",
        "",
        "Per-source-imagery licenses:",
        "",
    ]
    for source_group, record in sorted(records.items()):
        slug = record.get("slug", "<missing>")
        spdx = record.get("spdx", "<missing>")
        upstream = record.get("upstream_url", "<missing>")
        verified_by = record.get("verified_by", "<missing>")
        verified_at = record.get("verified_at", "<missing>")
        lines.extend([
            f"## {source_group}",
            f"- SPDX: {spdx}",
            f"- Upstream: {upstream}",
            f"- Verified: {verified_at} by {verified_by}",
            f"- Local text: [`licenses/{slug}.txt`](licenses/{slug}.txt)",
            "",
        ])
    return "\n".join(lines)
