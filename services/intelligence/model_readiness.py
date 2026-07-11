"""Runtime readiness contract for the configured vLLM models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import httpx


class ReadinessReason(StrEnum):
    """Machine-readable outcomes for a model-catalog check."""

    READY = "ready"
    MISSING_MODELS = "missing_models"
    CATALOG_UNAVAILABLE = "catalog_unavailable"
    INVALID_CATALOG = "invalid_catalog"


@dataclass(frozen=True)
class ModelReadiness:
    """Result of comparing configured models with the live catalog."""

    ready: bool
    reason: ReadinessReason
    required_models: tuple[str, ...]
    missing_models: tuple[str, ...]


def _required_models(base_model: str, synthesis_model: str) -> tuple[str, ...]:
    configured = (base_model, synthesis_model)
    return tuple(dict.fromkeys(model for model in configured if model))


async def check_model_readiness(
    *,
    base_url: str,
    base_model: str,
    synthesis_model: str,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_s: float = 2.0,
) -> ModelReadiness:
    """Return whether every configured model is advertised by vLLM."""
    required = _required_models(base_model, synthesis_model)

    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout_s) as client:
            response = await client.get(f"{base_url.rstrip('/')}/models")
            response.raise_for_status()
    except httpx.HTTPError:
        return ModelReadiness(
            ready=False,
            reason=ReadinessReason.CATALOG_UNAVAILABLE,
            required_models=required,
            missing_models=(),
        )

    try:
        data = response.json()["data"]
        if not isinstance(data, list):
            raise TypeError("model catalog data must be a list")
        if not all(
            isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
            for item in data
        ):
            raise TypeError("each model catalog entry must have a non-empty string id")
        available = {item["id"] for item in data}
    except (KeyError, TypeError, ValueError):
        return ModelReadiness(
            ready=False,
            reason=ReadinessReason.INVALID_CATALOG,
            required_models=required,
            missing_models=(),
        )

    missing = tuple(model for model in required if model not in available)
    return ModelReadiness(
        ready=not missing,
        reason=(ReadinessReason.MISSING_MODELS if missing else ReadinessReason.READY),
        required_models=required,
        missing_models=missing,
    )
