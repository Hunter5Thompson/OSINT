import re
from scripts.recon.asset_mapping import ASSET_MAPPING, AssetEntry  # noqa: F401


def test_twelve_entries():
    assert len(ASSET_MAPPING) == 12


def test_scene_ids_unique_and_lowercase():
    ids = [e.scene_id for e in ASSET_MAPPING]
    assert len(set(ids)) == len(ids)
    for sid in ids:
        assert sid == sid.lower()
        assert re.fullmatch(r"(jax|nyc)_\d{3}", sid)


def test_hf_filenames_match_scene_ids():
    for e in ASSET_MAPPING:
        # jax_068 -> JAX_068_final.ply
        prefix, num = e.scene_id.split("_")
        assert e.hf_filename == f"{prefix.upper()}_{num}_final.ply"


def test_sizes_are_positive():
    for e in ASSET_MAPPING:
        assert e.expected_size_bytes > 0


def test_source_group_is_known():
    valid = {"SpaceNet 2", "SpaceNet 4"}
    for e in ASSET_MAPPING:
        assert e.source_group in valid


def test_eight_jax_four_nyc():
    jax = [e for e in ASSET_MAPPING if e.scene_id.startswith("jax_")]
    nyc = [e for e in ASSET_MAPPING if e.scene_id.startswith("nyc_")]
    assert len(jax) == 8
    assert len(nyc) == 4
