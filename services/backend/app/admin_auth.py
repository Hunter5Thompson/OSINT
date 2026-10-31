"""Shared token enforcement for internal mutations and operator model triggers."""

from __future__ import annotations

import structlog
from fastapi import Header, HTTPException

from app.config import settings

log = structlog.get_logger(__name__)


def select_admin_token(*candidates: str) -> str:
    """Use the first configured candidate after whitespace normalization."""
    return next((token for candidate in candidates if (token := candidate.strip())), "")


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


def require_operator_access(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Authorize model use and dossier mutations with the same operator credential."""
    require_admin_token(
        expected_token=select_admin_token(
            settings.reports_admin_token, settings.incidents_admin_token
        ),
        supplied_token=x_admin_token,
        area="reports",
    )
