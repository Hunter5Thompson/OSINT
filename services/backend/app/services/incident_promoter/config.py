"""Env-driven config for the auto-promoter.

All values come from environment variables (prefix ``ODIN_PROMOTER_``). The
config is read once at lifespan-start via :meth:`PromoterConfig.from_env`;
the resulting instance is immutable for the lifetime of the Promoter task.
Uses ``pydantic_settings.BaseSettings`` to match ``app.config.Settings``.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class PromoterConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ODIN_PROMOTER_",
        extra="ignore",
        frozen=True,
    )

    enabled: bool = True
    firms_enabled: bool = True
    firms_min_hits: int = 3
    firms_window_sec: int = 86_400
    firms_bucket_deg: float = 0.1
    severity_enabled: bool = False
    severity_min_hits: int = 5
    severity_window_sec: int = 900
    telegram_enabled: bool = True
    telegram_min_hits: int = 3
    telegram_window_sec: int = 1800
    telegram_jaccard_threshold: float = 0.55
    telegram_jaccard_threshold_domain: float = 0.45
    telegram_embeddings_enabled: bool = False
    gdelt_enabled: bool = False
    gdelt_min_hits: int = 3
    gdelt_window_sec: int = 3600
    quiet_window_sec: int = 900
    sweeper_tick_sec: int = 60
    silence_cooldown_sec: int = 3600

    @classmethod
    def from_env(cls) -> PromoterConfig:
        """Convenience alias for call sites that want to read env explicitly."""
        return cls()

    def enabled_detector_ids(self) -> list[str]:
        ids: list[str] = []
        if self.firms_enabled:
            ids.append("firms")
        if self.severity_enabled:
            ids.append("severity")
        if self.telegram_enabled:
            ids.append("telegram")
        if self.gdelt_enabled:
            ids.append("gdelt")
        return ids
