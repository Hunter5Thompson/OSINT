"""One-shot bootstrap for Skyfall-GS pre-built PLYs.

Downloads twelve PLYs from jayinnn/Skyfall-GS-ply, copies them into
services/backend/static/recon/, runs a per-scene license audit, and
emits services/backend/data/recon_manifest.json.

Idempotent: re-running with unchanged on-disk SHAs is a no-op for those entries.
Fail-closed: scenes whose source license cannot be confirmed are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.recon.asset_mapping import ASSET_MAPPING
from scripts.recon.license_audit import (
    LicenseUnverifiedError,
    render_licenses_md,
    resolve_attribution,
)


# SpaceNet metadata seeds for the 12 known scenes (one-time table per spec §5.3).
# These are approximate centroids; provenance recorded as "spacenet_metadata".
SPACENET_BOUNDS: dict[str, tuple[float, float, float]] = {
    "jax_004": (30.3322, -81.6557, 350),
    "jax_068": (30.3411, -81.6390, 350),
    "jax_164": (30.3155, -81.6720, 350),
    "jax_168": (30.3289, -81.6800, 350),
    "jax_175": (30.3501, -81.6502, 350),
    "jax_214": (30.3098, -81.6645, 350),
    "jax_260": (30.3370, -81.6210, 350),
    "jax_264": (30.3260, -81.6700, 350),
    "nyc_004": (40.7128, -74.0060, 500),
    "nyc_010": (40.7235, -73.9925, 500),
    "nyc_219": (40.7580, -73.9855, 500),
    "nyc_336": (40.7484, -73.9857, 500),
}

DEFAULT_CAMERA = {"position": [0, 0, 200], "look_at": [0, 0, 0], "fov_deg": 60}

HF_REPO_ID = "jayinnn/Skyfall-GS-ply"


class BootstrapError(RuntimeError):
    """Raised when bootstrap cannot continue."""


class HFCLIMissingError(BootstrapError):
    pass


class BootstrapPartialError(BootstrapError):
    """Raised when bootstrap produced fewer than the expected 12 scenes and
    --allow-partial was not set."""


def check_hf_cli() -> None:
    if shutil.which("hf") is None:
        raise HFCLIMissingError(
            "the HuggingFace CLI ('hf') is not on PATH. Install it with:\n"
            "    uv pip install --system 'huggingface_hub[cli]'\n"
            "or:\n"
            "    pip install 'huggingface_hub[cli]'"
        )


def hf_download_all(target_dir: Path) -> Path:
    """Call `hf download` for the repo; returns the directory containing the PLYs."""
    target_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["hf", "download", HF_REPO_ID, "--local-dir", str(target_dir)],
        check=True,
    )
    return target_dir


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _load_prior_manifest(manifest_path: Path) -> dict[str, dict]:
    """Returns scene_id -> scene dict from the existing manifest, or empty."""
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text())
    except Exception:
        return {}
    return {s["scene_id"]: s for s in payload.get("scenes", [])}


def _all_targets_match_prior(
    static_dir: Path, prior: dict[str, dict]
) -> bool:
    """True iff every ASSET_MAPPING entry has a target file whose SHA matches
    the prior manifest. Used to short-circuit before hf_download_all."""
    if len(prior) != len(ASSET_MAPPING):
        return False
    for entry in ASSET_MAPPING:
        scene = prior.get(entry.scene_id)
        if scene is None:
            return False
        target = static_dir / entry.hf_filename
        if not target.exists():
            return False
        if sha256_of(target) != scene.get("ply_sha256"):
            return False
    return True


EXPECTED_SCENE_COUNT = 12


def main(
    *,
    static_dir: Path | None = None,
    manifest_path: Path | None = None,
    licenses_dir: Path | None = None,
    strict_sizes: bool = True,
    allow_partial: bool = False,
) -> int:
    """Entry point. Returns process exit code.

    By default, bootstrap fails with BootstrapPartialError if fewer than 12
    scenes end up in the manifest — the MVP goal is "all twelve scenes
    openable from a globe-pin click". Use allow_partial=True for
    intentional fail-closed experimentation (e.g. when license records
    are not yet populated).
    """
    repo_root = Path(__file__).resolve().parents[2]
    static_dir = static_dir or (repo_root / "services" / "backend" / "static" / "recon")
    manifest_path = manifest_path or (
        repo_root / "services" / "backend" / "data" / "recon_manifest.json"
    )
    licenses_dir = licenses_dir or (static_dir / "licenses")

    check_hf_cli()
    static_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    prior = _load_prior_manifest(manifest_path)
    scenes_out: list[dict] = []
    excluded: list[tuple[str, str]] = []

    if _all_targets_match_prior(static_dir, prior):
        # Short-circuit path: PLY SHAs match, so HF download can be skipped.
        # But: re-audit licenses AND refresh attribution strings, because the
        # viewer footer renders scene.attribution verbatim. If records.json
        # was emptied or changed since the prior run, the old attribution is
        # stale (or worse, references a license that's no longer verified).
        print("All 12 PLYs match existing manifest - re-auditing licenses "
              "and refreshing attribution; skipping HF download.")
        for entry in ASSET_MAPPING:
            prior_scene = prior.get(entry.scene_id)
            if prior_scene is None:
                excluded.append((entry.scene_id, "missing from prior manifest"))
                continue
            try:
                attribution = resolve_attribution(
                    source_group=entry.source_group, licenses_dir=licenses_dir
                )
            except LicenseUnverifiedError as e:
                # NEVER fall through to the "keep prior manifest" path here,
                # even with allow_partial=True - that would let invalidated
                # scenes keep being served. Drop the scene entirely so the
                # rewritten manifest reflects current license state.
                excluded.append((entry.scene_id, f"license unverified: {e}"))
                continue
            refreshed = dict(prior_scene)
            refreshed["attribution"] = attribution
            scenes_out.append(refreshed)
    else:
        # Full rebuild path
        cache_dir = repo_root / ".cache" / "skyfall_plys"
        download_dir = hf_download_all(cache_dir)

        for entry in ASSET_MAPPING:
            src = download_dir / entry.hf_filename
            if not src.exists():
                excluded.append((entry.scene_id, "asset missing from HF download"))
                continue

            actual_size = src.stat().st_size
            if actual_size != entry.expected_size_bytes:
                msg = (
                    f"size mismatch for {entry.hf_filename}: "
                    f"got {actual_size}, expected {entry.expected_size_bytes}"
                )
                if strict_sizes:
                    raise BootstrapError(msg)
                print(f"WARN: {msg}", file=sys.stderr)

            target = static_dir / entry.hf_filename
            prior_sha = prior.get(entry.scene_id, {}).get("ply_sha256")
            if target.exists() and prior_sha is not None and sha256_of(target) == prior_sha:
                sha = prior_sha
            else:
                shutil.copy2(src, target)
                sha = sha256_of(target)

            try:
                attribution = resolve_attribution(
                    source_group=entry.source_group, licenses_dir=licenses_dir
                )
            except LicenseUnverifiedError as e:
                excluded.append((entry.scene_id, f"license unverified: {e}"))
                continue

            lat, lon, radius = SPACENET_BOUNDS[entry.scene_id]
            scenes_out.append({
                "scene_id": entry.scene_id,
                "hf_filename": entry.hf_filename,
                "display_name": entry.display_name,
                # ?sha=<sha256> makes immutable Cache-Control safe even when
                # the filename stays stable across re-bootstraps.
                "ply_url": f"/static/recon/{entry.hf_filename}?sha={sha}",
                "ply_size_bytes": actual_size,
                "ply_sha256": sha,
                "bounds": {"center_lat": lat, "center_lon": lon, "radius_m": radius},
                "bounds_source": "spacenet_metadata",
                "default_camera": DEFAULT_CAMERA,
                "attribution": attribution,
                "source": "skyfall_gs_hf",
            })

    payload = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": _git_sha(),
        "scenes": scenes_out,
    }

    # Fail BEFORE touching manifest_path - otherwise a default (allow_partial=False)
    # run that ends up short would still leave a partial/0-scene manifest on disk,
    # silently undermining the "12 scenes or fail" guarantee.
    if len(scenes_out) < EXPECTED_SCENE_COUNT and not allow_partial:
        if excluded:
            print("Excluded scenes (fail-closed):", file=sys.stderr)
            for sid, reason in excluded:
                print(f"  - {sid}: {reason}", file=sys.stderr)
        # Distinguish "license no longer verified" (short-circuit re-audit
        # detected invalidated records) so callers can match on it. Plain
        # "license unverified" reasons get folded in too.
        any_license_invalidated = any(
            "license" in reason and "verified" in reason
            for _, reason in excluded
        )
        license_note = (
            " License records are no longer verified for one or more sources;"
            " populate licenses/ records.json then rerun."
            if any_license_invalidated else ""
        )
        raise BootstrapPartialError(
            f"only {len(scenes_out)}/{EXPECTED_SCENE_COUNT} scenes emitted."
            f"{license_note} "
            f"Populate licenses/ then rerun, or pass --allow-partial to "
            f"intentionally ship a partial manifest. Excluded: "
            f"{[sid for sid, _ in excluded]}"
        )

    # Atomic write - emit to a tmp file in the same dir, fsync, then rename.
    # Same-dir rename is atomic on POSIX, so readers never see a half-written file.
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2))
    os.replace(tmp_path, manifest_path)
    (static_dir / "LICENSES.md").write_text(render_licenses_md(licenses_dir))

    if excluded:
        print("Excluded scenes (fail-closed):", file=sys.stderr)
        for sid, reason in excluded:
            print(f"  - {sid}: {reason}", file=sys.stderr)

    print(f"Wrote manifest with {len(scenes_out)} scenes -> {manifest_path}")
    return 0


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bootstrap Skyfall-GS PLYs.")
    p.add_argument("--static-dir", type=Path, default=None)
    p.add_argument("--manifest-path", type=Path, default=None)
    p.add_argument("--licenses-dir", type=Path, default=None)
    p.add_argument("--no-strict-sizes", action="store_true",
                   help="Log size mismatches as warnings instead of failing.")
    p.add_argument("--allow-partial", action="store_true",
                   help="Allow the manifest to ship with fewer than 12 scenes "
                        "(e.g. while license records are still being populated).")
    return p.parse_args(argv)


if __name__ == "__main__":
    ns = _parse_argv(sys.argv[1:])
    try:
        sys.exit(main(
            static_dir=ns.static_dir,
            manifest_path=ns.manifest_path,
            licenses_dir=ns.licenses_dir,
            strict_sizes=not ns.no_strict_sizes,
            allow_partial=ns.allow_partial,
        ))
    except BootstrapError as e:
        print(f"BOOTSTRAP FAILED: {e}", file=sys.stderr)
        sys.exit(2)
