"""Integration smoke for the real app wiring (router + static mount)."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_with_seeded_manifest(tmp_path, monkeypatch):
    static_dir = tmp_path / "static" / "recon"
    static_dir.mkdir(parents=True)
    ply = static_dir / "JAX_TEST_final.ply"
    ply.write_bytes(b"PLYDATA" * 10)  # 70 bytes

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    sha = "b" * 64
    manifest = {
        "version": 2, "generated_at": "2026-05-17T00:00:00Z", "source_commit": "x",
        "scenes": [{
            "scene_id": "jax_test", "hf_filename": "JAX_TEST_final.ply",
            "display_name": "Test",
            "ply_url": f"/static/recon/JAX_TEST_final.ply?sha={sha}",
            "ply_size_bytes": 70, "ply_sha256": sha,
            "bounds": {"center_lat": 30.0, "center_lon": -81.0, "radius_m": 100},
            "bounds_source": "manual",
            "default_camera": {"position": [0, 0, 100], "look_at": [0, 0, 0], "fov_deg": 60},
            "attribution": "test", "source": "skyfall_gs_hf",
        }],
    }
    (data_dir / "recon_manifest.json").write_text(json.dumps(manifest))

    monkeypatch.setenv("RECON_MANIFEST_PATH", str(data_dir / "recon_manifest.json"))
    monkeypatch.setenv("RECON_STATIC_DIR", str(static_dir))

    # Re-import the app fresh so the module-level mount picks up env vars.
    # Use TestClient as a context manager so the FastAPI lifespan executes
    # and the manifest loader is wired into app.state.
    import importlib

    import app.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client


def test_recon_scenes_endpoint_live(app_with_seeded_manifest):
    r = app_with_seeded_manifest.get("/api/recon/scenes")
    assert r.status_code == 200
    assert r.json()["scenes"][0]["scene_id"] == "jax_test"


def test_recon_ply_static_serves_with_immutable_cache_control(app_with_seeded_manifest):
    r = app_with_seeded_manifest.get("/static/recon/JAX_TEST_final.ply")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_recon_ply_range_returns_206(app_with_seeded_manifest):
    r = app_with_seeded_manifest.get(
        "/static/recon/JAX_TEST_final.ply",
        headers={"Range": "bytes=0-2"},
    )
    assert r.status_code == 206
    assert r.content == b"PLY"
