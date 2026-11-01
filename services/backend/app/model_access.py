"""Authorize then reserve capacity through the complete HTTP/SSE response."""
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException

from app.admin_auth import require_operator_access
from app.config import settings
from app.services.model_admission import AdmissionBusyError, FileAdmission


async def require_model_access(
    _authorized: None = Depends(require_operator_access),
) -> AsyncIterator[None]:
    try:
        permit = FileAdmission(
            settings.model_admission_dir, settings.model_max_concurrency,
        ).acquire()
    except AdmissionBusyError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "MODEL_BUSY",
                "message": "Analysis capacity is busy. Try again shortly.",
            },
            headers={"Retry-After": "1"},
        ) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Model admission is unavailable") from exc
    try:
        yield
    finally:
        permit.close()
