from app.models.recon import DefaultCamera, GeoBounds, ReconManifest, ReconScene


def test_geobounds_accepts_valid_coordinates():
    b = GeoBounds(center_lat=30.33, center_lon=-81.65, radius_m=350)
    assert b.center_lat == 30.33


def test_default_camera_serializes_position_as_tuple():
    c = DefaultCamera(position=(0.0, 0.0, 200.0), look_at=(0.0, 0.0, 0.0), fov_deg=60.0)
    assert c.model_dump()["position"] == (0.0, 0.0, 200.0)


def test_recon_scene_requires_source_canonical_value():
    s = ReconScene(
        scene_id="jax_068", hf_filename="JAX_068_final.ply",
        display_name="Jacksonville District 068",
        ply_url="/static/recon/JAX_068_final.ply?sha=" + "a" * 64,
        ply_size_bytes=240164505,
        ply_sha256="a" * 64,
        bounds=GeoBounds(center_lat=30.33, center_lon=-81.65, radius_m=350),
        bounds_source="spacenet_metadata",
        default_camera=DefaultCamera(position=(0, 0, 200), look_at=(0, 0, 0), fov_deg=60),
        attribution="Reconstruction: Skyfall-GS ...",
        source="skyfall_gs_hf",
    )
    assert s.scene_id == "jax_068"
    assert s.ply_url.endswith("?sha=" + "a" * 64)


def test_recon_scene_rejects_ply_url_without_sha_query():
    """The cache-busting ?sha=<sha256> query is required to make 'immutable' safe."""
    import pytest
    with pytest.raises(ValueError):
        ReconScene(
            scene_id="jax_068", hf_filename="JAX_068_final.ply",
            display_name="x",
            ply_url="/static/recon/JAX_068_final.ply",  # no ?sha=
            ply_size_bytes=1, ply_sha256="a"*64,
            bounds=GeoBounds(center_lat=0, center_lon=0, radius_m=1),
            bounds_source="manual",
            default_camera=DefaultCamera(position=(0,0,1), look_at=(0,0,0), fov_deg=60),
            attribution="x", source="skyfall_gs_hf",
        )


def test_recon_manifest_parses_v2_payload():
    payload = {
        "version": 2,
        "generated_at": "2026-05-17T00:00:00Z",
        "source_commit": "deadbeef",
        "scenes": [],
    }
    m = ReconManifest.model_validate(payload)
    assert m.version == 2
