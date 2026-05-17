"""Frozen asset mapping for Skyfall-GS pre-built PLYs.

Source: https://huggingface.co/api/models/jayinnn/Skyfall-GS-ply/tree/main
Verified 2026-05-11. Sizes copied from HF API; SHA values are populated at
bootstrap time (not stored here).
"""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AssetEntry:
    scene_id: str           # canonical lowercase: jax_068
    hf_filename: str        # verbatim HF: JAX_068_final.ply
    display_name: str
    expected_size_bytes: int
    source_group: Literal["SpaceNet 2", "SpaceNet 4"]


ASSET_MAPPING: tuple[AssetEntry, ...] = (
    AssetEntry("jax_004", "JAX_004_final.ply", "Jacksonville District 004", 158_510_569, "SpaceNet 4"),
    AssetEntry("jax_068", "JAX_068_final.ply", "Jacksonville District 068", 240_164_505, "SpaceNet 4"),
    AssetEntry("jax_164", "JAX_164_final.ply", "Jacksonville District 164", 290_453_497, "SpaceNet 4"),
    AssetEntry("jax_168", "JAX_168_final.ply", "Jacksonville District 168", 265_047_857, "SpaceNet 4"),
    AssetEntry("jax_175", "JAX_175_final.ply", "Jacksonville District 175", 232_601_521, "SpaceNet 4"),
    AssetEntry("jax_214", "JAX_214_final.ply", "Jacksonville District 214", 222_097_625, "SpaceNet 4"),
    AssetEntry("jax_260", "JAX_260_final.ply", "Jacksonville District 260", 227_118_225, "SpaceNet 4"),
    AssetEntry("jax_264", "JAX_264_final.ply", "Jacksonville District 264", 272_916_913, "SpaceNet 4"),
    AssetEntry("nyc_004", "NYC_004_final.ply", "New York City Tile 004", 243_791_921, "SpaceNet 2"),
    AssetEntry("nyc_010", "NYC_010_final.ply", "New York City Tile 010", 320_689_209, "SpaceNet 2"),
    AssetEntry("nyc_219", "NYC_219_final.ply", "New York City Tile 219", 324_186_833, "SpaceNet 2"),
    AssetEntry("nyc_336", "NYC_336_final.ply", "New York City Tile 336", 213_483_617, "SpaceNet 2"),
)
