import json

import pytest

from app.services.recon_manifest import (
    ReconManifestLoader,
    ReconManifestMissingError,
)


def _valid_manifest_dict():
    sha = "a" * 64
    return {
        "version": 2,
        "generated_at": "2026-05-17T00:00:00Z",
        "source_commit": "deadbeef",
        "scenes": [
            {
                "scene_id": "jax_068",
                "hf_filename": "JAX_068_final.ply",
                "display_name": "Jacksonville District 068",
                "ply_url": f"/static/recon/JAX_068_final.ply?sha={sha}",
                "ply_size_bytes": 240164505,
                "ply_sha256": sha,
                "bounds": {"center_lat": 30.33, "center_lon": -81.65, "radius_m": 350},
                "bounds_source": "spacenet_metadata",
                "default_camera": {"position": [0, 0, 200], "look_at": [0, 0, 0], "fov_deg": 60},
                "attribution": "test attribution",
                "source": "skyfall_gs_hf",
            }
        ],
    }


def test_loader_reads_manifest_into_memory_dict(tmp_path):
    path = tmp_path / "recon_manifest.json"
    path.write_text(json.dumps(_valid_manifest_dict()))
    loader = ReconManifestLoader(path)
    loader.load()
    assert loader.is_loaded
    assert loader.get_scene("jax_068") is not None
    assert loader.get_scene("jax_068").display_name == "Jacksonville District 068"
    assert loader.get_scene("missing") is None


def test_loader_list_scenes_returns_all(tmp_path):
    path = tmp_path / "recon_manifest.json"
    path.write_text(json.dumps(_valid_manifest_dict()))
    loader = ReconManifestLoader(path)
    loader.load()
    assert len(loader.list_scenes()) == 1


def test_loader_missing_file_raises(tmp_path):
    loader = ReconManifestLoader(tmp_path / "absent.json")
    with pytest.raises(ReconManifestMissingError):
        loader.load()
    assert not loader.is_loaded
