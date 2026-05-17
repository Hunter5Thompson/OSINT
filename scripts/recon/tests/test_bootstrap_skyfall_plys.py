import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from scripts.recon.bootstrap_skyfall_plys import (
    main,
    BootstrapError,
    check_hf_cli,
    HFCLIMissingError,
    sha256_of,
)


def test_check_hf_cli_raises_actionable_message_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(HFCLIMissingError) as exc:
        check_hf_cli()
    assert "pip install" in str(exc.value) or "uv pip install" in str(exc.value)


def test_sha256_of_computes_hex_digest(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert sha256_of(f) == hashlib.sha256(b"hello").hexdigest()


@pytest.fixture()
def fake_hf_cache(tmp_path):
    """Simulates 'hf download' having already populated a local dir."""
    cache = tmp_path / "hf_cache"
    cache.mkdir()
    for name in (
        "JAX_004_final.ply", "JAX_068_final.ply", "JAX_164_final.ply",
        "JAX_168_final.ply", "JAX_175_final.ply", "JAX_214_final.ply",
        "JAX_260_final.ply", "JAX_264_final.ply",
        "NYC_004_final.ply", "NYC_010_final.ply", "NYC_219_final.ply",
        "NYC_336_final.ply",
    ):
        # 1-byte stubs (size mismatch is expected and tested below)
        (cache / name).write_bytes(b"x")
    return cache


@pytest.fixture()
def fake_licenses_dir(tmp_path):
    """Seed a fully-verified licenses dir for both SpaceNet groups."""
    licenses = tmp_path / "licenses"
    licenses.mkdir()
    import json as _json
    (licenses / "spacenet-2.txt").write_text("SPACENET 2 LICENSE TEXT")
    (licenses / "spacenet-4.txt").write_text("SPACENET 4 LICENSE TEXT")
    (licenses / "records.json").write_text(_json.dumps({"records": {
        "SpaceNet 2": {
            "slug": "spacenet-2", "spdx": "CC-BY-SA-4.0",
            "upstream_url": "https://spacenet.ai/spacenet-buildings-dataset-v2/",
            "verified_by": "test", "verified_at": "2026-05-17",
        },
        "SpaceNet 4": {
            "slug": "spacenet-4", "spdx": "CC-BY-SA-4.0",
            "upstream_url": "https://spacenet.ai/off-nadir-building-detection/",
            "verified_by": "test", "verified_at": "2026-05-17",
        },
    }}))
    return licenses


def test_main_emits_manifest_validating_against_pydantic(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(
            static_dir=static_dir,
            manifest_path=manifest_path,
            licenses_dir=fake_licenses_dir,
            strict_sizes=False,
        )

    # Validate against backend Pydantic model
    sys.path.insert(0, str(Path("services/backend").resolve()))
    from app.models.recon import ReconManifest
    m = ReconManifest.model_validate_json(manifest_path.read_text())
    assert m.version == 2
    assert len(m.scenes) == 12
    assert {s.scene_id for s in m.scenes} >= {"jax_068", "nyc_010"}
    # ply_url includes ?sha=<sha256> for cache safety
    for s in m.scenes:
        assert s.ply_url.endswith(f"?sha={s.ply_sha256}")


def test_main_emits_licenses_md(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"
    licenses_md = static_dir / "LICENSES.md"

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False)

    assert licenses_md.exists()
    text = licenses_md.read_text()
    assert "SpaceNet 2" in text
    assert "SpaceNet 4" in text
    assert "Apache 2.0" in text


def test_main_is_idempotent_and_skips_download_when_shas_match(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # First run: download is called once
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ) as download_first:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False)
        first = manifest_path.read_text()
    assert download_first.call_count == 1

    # Second run: all PLYs already on disk with matching SHAs → no download
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all"
    ) as download_second:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False)
        second = manifest_path.read_text()
    assert download_second.call_count == 0, "rerun must short-circuit before HF download"

    # Manifest content stable across runs (timestamps may differ — compare scenes)
    a = json.loads(first)["scenes"]
    b = json.loads(second)["scenes"]
    assert a == b


def test_main_raises_when_fewer_than_12_scenes_and_not_allow_partial(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """Default behavior: bootstrap exits non-zero AND leaves no manifest behind."""
    from scripts.recon.bootstrap_skyfall_plys import BootstrapPartialError
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"
    assert not manifest_path.exists()

    def fake_resolve(*, source_group, licenses_dir):
        if source_group == "SpaceNet 2":
            from scripts.recon.license_audit import LicenseUnverifiedError
            raise LicenseUnverifiedError("simulated")
        return "ok-attribution"

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ), patch(
        "scripts.recon.bootstrap_skyfall_plys.resolve_attribution",
        side_effect=fake_resolve,
    ):
        with pytest.raises(BootstrapPartialError):
            main(static_dir=static_dir, manifest_path=manifest_path,
                 licenses_dir=fake_licenses_dir, strict_sizes=False,
                 allow_partial=False)

    # Manifest must NOT be written on partial-fail — otherwise a half-baked
    # 0/4/8-scene file would silently undermine the "12 or fail" guarantee.
    assert not manifest_path.exists()
    # And no half-written tmp file either
    assert not manifest_path.with_suffix(manifest_path.suffix + ".tmp").exists()


def test_main_partial_fail_preserves_existing_manifest(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """If a previous good manifest exists, a subsequent partial-fail run must
    not clobber it — atomic-rename semantics."""
    from scripts.recon.bootstrap_skyfall_plys import BootstrapPartialError
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # First: a clean run with all licenses populated → 12 scenes
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    good = manifest_path.read_text()
    assert len(json.loads(good)["scenes"]) == 12

    # Second: simulate license records getting wiped — must fail without
    # overwriting the existing good manifest.
    def fake_resolve(*, source_group, licenses_dir):
        from scripts.recon.license_audit import LicenseUnverifiedError
        raise LicenseUnverifiedError("simulated wipe")

    # Force a re-download path (existing files match prior so short-circuit
    # would fire; we test the post-download write-guard here, so wipe targets).
    for entry in __import__(
        "scripts.recon.asset_mapping", fromlist=["ASSET_MAPPING"]
    ).ASSET_MAPPING:
        (static_dir / entry.hf_filename).unlink(missing_ok=True)

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ), patch(
        "scripts.recon.bootstrap_skyfall_plys.resolve_attribution",
        side_effect=fake_resolve,
    ):
        with pytest.raises(BootstrapPartialError):
            main(static_dir=static_dir, manifest_path=manifest_path,
                 licenses_dir=fake_licenses_dir, strict_sizes=False,
                 allow_partial=False)

    assert manifest_path.read_text() == good


def test_short_circuit_reaudits_licenses_and_fails_if_invalidated(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """A rerun with all PLY SHAs intact but invalidated license records must
    NOT keep serving the prior manifest unless --allow-partial is set."""
    from scripts.recon.bootstrap_skyfall_plys import BootstrapPartialError
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # Run 1: clean — 12 scenes land on disk + in manifest
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)

    # Wipe records.json — short-circuit path must catch this
    (fake_licenses_dir / "records.json").write_text(json.dumps({"records": {}}))

    # Run 2: PLYs still match, but license re-audit must fail
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all"
    ) as no_download:
        with pytest.raises(BootstrapPartialError, match="no longer verified"):
            main(static_dir=static_dir, manifest_path=manifest_path,
                 licenses_dir=fake_licenses_dir, strict_sizes=False,
                 allow_partial=False)
    # Short-circuit should still have prevented HF download
    assert no_download.call_count == 0


def test_short_circuit_allow_partial_rewrites_to_smaller_manifest(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """Short-circuit + allow_partial + partial license invalidation must
    REWRITE the manifest (not keep the old 12-scene one with invalidated
    attributions). Otherwise the viewer would still serve unverified scenes."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    # Run 1: clean 12-scene manifest
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    assert len(json.loads(manifest_path.read_text())["scenes"]) == 12

    # Invalidate only SpaceNet 2 (the 4 NYC scenes) by removing its record
    records = json.loads((fake_licenses_dir / "records.json").read_text())
    del records["records"]["SpaceNet 2"]
    (fake_licenses_dir / "records.json").write_text(json.dumps(records))

    # Run 2: short-circuit + allow_partial → expect 8 JAX scenes only, no NYC
    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all"
    ) as no_download:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=True)
    assert no_download.call_count == 0, "must skip HF on SHA match"

    payload = json.loads(manifest_path.read_text())
    scene_ids = {s["scene_id"] for s in payload["scenes"]}
    assert len(scene_ids) == 8
    assert all(sid.startswith("jax_") for sid in scene_ids)


def test_short_circuit_refreshes_attribution_when_records_change(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """If license records remain valid but content changed (e.g. verified_by),
    the short-circuit path must rewrite manifest.attribution from current
    records — the viewer footer renders that field verbatim."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    before = json.loads(manifest_path.read_text())["scenes"]
    assert all("verified 2026-05-17 by test" in s["attribution"] for s in before)

    # Bump verified_by + verified_at
    records = json.loads((fake_licenses_dir / "records.json").read_text())
    for sg in records["records"]:
        records["records"][sg]["verified_by"] = "operator-2"
        records["records"][sg]["verified_at"] = "2026-06-01"
    (fake_licenses_dir / "records.json").write_text(json.dumps(records))

    with patch("scripts.recon.bootstrap_skyfall_plys.hf_download_all") as no_dl:
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=False)
    assert no_dl.call_count == 0
    after = json.loads(manifest_path.read_text())["scenes"]
    assert all("verified 2026-06-01 by operator-2" in s["attribution"] for s in after)


def test_main_skips_scenes_with_unverified_license_when_allow_partial(
    tmp_path, fake_hf_cache, fake_licenses_dir, monkeypatch
):
    """With --allow-partial, license-failed scenes are excluded but the run succeeds."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/hf")
    static_dir = tmp_path / "static"
    manifest_path = tmp_path / "manifest.json"

    def fake_resolve(*, source_group, licenses_dir):
        if source_group == "SpaceNet 2":
            from scripts.recon.license_audit import LicenseUnverifiedError
            raise LicenseUnverifiedError("simulated")
        return "ok-attribution"

    with patch(
        "scripts.recon.bootstrap_skyfall_plys.hf_download_all",
        return_value=fake_hf_cache,
    ), patch(
        "scripts.recon.bootstrap_skyfall_plys.resolve_attribution",
        side_effect=fake_resolve,
    ):
        main(static_dir=static_dir, manifest_path=manifest_path,
             licenses_dir=fake_licenses_dir, strict_sizes=False,
             allow_partial=True)

    payload = json.loads(manifest_path.read_text())
    scene_ids = {s["scene_id"] for s in payload["scenes"]}
    assert all(not sid.startswith("nyc_") for sid in scene_ids)
    assert any(sid.startswith("jax_") for sid in scene_ids)
