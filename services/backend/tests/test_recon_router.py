import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import recon as recon_router
from app.services.recon_manifest import ReconManifestLoader


def _seed_manifest(tmp_path: Path) -> ReconManifestLoader:
    sha = "a" * 64
    payload = {
        "version": 2,
        "generated_at": "2026-05-17T00:00:00Z",
        "source_commit": "x",
        "scenes": [
            {
                "scene_id": "jax_068",
                "hf_filename": "JAX_068_final.ply",
                "display_name": "Jacksonville District 068",
                "ply_url": f"/static/recon/JAX_068_final.ply?sha={sha}",
                "ply_size_bytes": 240164505,
                "ply_sha256": sha,
                "bounds": {
                    "center_lat": 30.33,
                    "center_lon": -81.65,
                    "radius_m": 350,
                },
                "bounds_source": "spacenet_metadata",
                "default_camera": {
                    "position": [0, 0, 200],
                    "look_at": [0, 0, 0],
                    "fov_deg": 60,
                },
                "attribution": "test",
                "source": "skyfall_gs_hf",
            }
        ],
    }
    p = tmp_path / "m.json"
    p.write_text(json.dumps(payload))
    loader = ReconManifestLoader(p)
    loader.load()
    return loader


def _build_app(loader: ReconManifestLoader) -> FastAPI:
    app = FastAPI()
    app.state.recon_manifest = loader
    app.include_router(recon_router.router, prefix="/api")
    return app


def test_list_scenes_returns_manifest_shape(tmp_path):
    client = TestClient(_build_app(_seed_manifest(tmp_path)))
    r = client.get("/api/recon/scenes")
    assert r.status_code == 200
    body = r.json()
    assert "scenes" in body
    assert body["scenes"][0]["scene_id"] == "jax_068"


def test_get_scene_by_id(tmp_path):
    client = TestClient(_build_app(_seed_manifest(tmp_path)))
    r = client.get("/api/recon/scenes/jax_068")
    assert r.status_code == 200
    assert r.json()["scene_id"] == "jax_068"


def test_get_scene_404_for_unknown_id(tmp_path):
    client = TestClient(_build_app(_seed_manifest(tmp_path)))
    r = client.get("/api/recon/scenes/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "scene not found"


def test_router_503_when_manifest_not_loaded(tmp_path):
    loader = ReconManifestLoader(tmp_path / "absent.json")  # not loaded
    client = TestClient(_build_app(loader))
    r = client.get("/api/recon/scenes")
    assert r.status_code == 503
