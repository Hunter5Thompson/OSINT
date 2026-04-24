"""Settings for GDELT raw files ingestion — loaded from env via pydantic-settings."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class GDELTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GDELT_", extra="ignore")

    base_url: str = "http://data.gdeltproject.org/gdeltv2"
    forward_interval_seconds: int = 900
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


settings = GDELTSettings()
