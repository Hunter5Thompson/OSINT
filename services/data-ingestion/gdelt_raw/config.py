"""Settings for GDELT raw files ingestion — loaded from env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from gdelt_raw.cameo_mapping import map_cameo_root


class GDELTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GDELT_", extra="ignore")

    base_url: str = "https://data.gdeltproject.org/gdeltv2"
    forward_interval_seconds: int = 900
    # newest N slices a forward tick may catch up; older gaps -> backfill CLI
    forward_max_catchup_slices: int = 8
    # a 404 slice this many slices older than the announced one is treated as
    # never-published and skipped (younger 404s = not published yet -> wait;
    # files ~40 min late were observed live, so keep a 1.5 h margin)
    forward_missing_grace_slices: int = 6
    download_timeout: float = 60.0
    max_parse_error_pct: float = 5.0
    parquet_path: str = "/data/gdelt"
    filter_mode: str = "alpha"  # "alpha" | "delta"
    cameo_root_allowlist: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [15, 18, 19, 20]
    )
    theme_allowlist: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "ARMEDCONFLICT", "KILL",
            "CRISISLEX_*", "TERROR", "TERROR_*",
            "MILITARY", "NUCLEAR", "WMD",
            "WEAPONS_*", "WEAPONS_PROLIFERATION",
            "SANCTIONS", "CYBER_ATTACK", "ESPIONAGE", "COUP",
            "HUMAN_RIGHTS_ABUSES", "REFUGEE", "DISPLACEMENT",
        ]
    )
    nuclear_override_themes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["NUCLEAR", "WMD", "WEAPONS_PROLIFERATION", "WEAPONS_*"]
    )
    backfill_parallel_slices: int = 4
    backfill_default_days: int = 30

    @model_validator(mode="after")
    def _require_mapped_allowlist_roots(self) -> GDELTSettings:
        unmapped = sorted(
            root for root in self.cameo_root_allowlist if map_cameo_root(root) is None
        )
        if unmapped:
            raise ValueError(f"unmapped CAMEO roots in allowlist: {unmapped}")
        return self

    @field_validator("cameo_root_allowlist", mode="before")
    @classmethod
    def _split_int_csv(cls, v):
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v

    @field_validator("theme_allowlist", "nuclear_override_themes", mode="before")
    @classmethod
    def _split_str_csv(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> GDELTSettings:
    return GDELTSettings()
