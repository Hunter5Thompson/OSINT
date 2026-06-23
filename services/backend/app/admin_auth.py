"""Shared admin-token enforcement for mutating internal endpoints."""

from __future__ import annotations

import structlog
from fastapi import HTTPException

log = structlog.get_logger(__name__)


def require_admin_token(
    *,
    expected_token: str,
    supplied_token: str | None,
    area: str,
) -> None:
    if not expected_token:
        log.warning("admin_token_not_configured", area=area)
        raise HTTPException(
            status_code=503,
            detail=f"{area} admin token not configured",
        )
    if supplied_token != expected_token:
        raise HTTPException(status_code=401, detail="invalid admin token")
