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
    expected = expected_token.strip()
    supplied = supplied_token.strip() if isinstance(supplied_token, str) else ""
    if not expected:
        log.warning("admin_token_not_configured", area=area)
        raise HTTPException(
            status_code=503,
            detail=f"{area} admin token not configured",
        )
    if supplied != expected:
        raise HTTPException(status_code=401, detail="invalid admin token")
