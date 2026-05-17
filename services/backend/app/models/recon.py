from typing import Literal

from pydantic import BaseModel, Field, model_validator


class GeoBounds(BaseModel):
    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0)


class DefaultCamera(BaseModel):
    position: tuple[float, float, float]
    look_at: tuple[float, float, float]
    fov_deg: float = Field(gt=0, le=180)


class ReconScene(BaseModel):
    scene_id: str
    hf_filename: str
    display_name: str
    ply_url: str
    ply_size_bytes: int = Field(gt=0)
    ply_sha256: str = Field(min_length=64, max_length=64)
    bounds: GeoBounds
    bounds_source: Literal["spacenet_metadata", "manual"]
    default_camera: DefaultCamera
    attribution: str
    source: str

    @model_validator(mode="after")
    def _ply_url_must_carry_sha_query(self) -> "ReconScene":
        # Immutable Cache-Control is only safe when the URL changes whenever
        # bytes change. Bootstrap embeds ?sha=<ply_sha256> in ply_url; reject
        # manifests that don't.
        expected = f"?sha={self.ply_sha256}"
        if not self.ply_url.endswith(expected):
            raise ValueError(
                f"ply_url must end with {expected!r} for cache-bust safety; "
                f"got {self.ply_url!r}"
            )
        return self


class ReconManifest(BaseModel):
    version: int
    generated_at: str
    source_commit: str
    scenes: list[ReconScene]


class ReconScenesResponse(BaseModel):
    scenes: list[ReconScene]
