"""Report CRUD + report-scoped chat message endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.models.report import (
    ReportCreateRequest,
    ReportMessage,
    ReportMessageCreate,
    ReportRecord,
    ReportUpdateRequest,
)
from app.services import report_store

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportRecord])
async def list_reports(
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ReportRecord]:
    try:
        return await report_store.list_reports(limit=limit)
    except Exception as exc:
        log.warning("reports_list_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="reports backend unavailable") from exc


@router.post("", response_model=ReportRecord, status_code=status.HTTP_201_CREATED)
async def create_report(payload: ReportCreateRequest) -> ReportRecord:
    try:
        return await report_store.create_report(payload)
    except Exception as exc:
        log.warning("report_create_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="report create failed") from exc


@router.get("/{report_id}", response_model=ReportRecord)
async def get_report(report_id: str) -> ReportRecord:
    try:
        report = await report_store.get_report(report_id)
    except Exception as exc:
        log.warning("report_get_failed", report_id=report_id, error=str(exc))
        raise HTTPException(status_code=503, detail="reports backend unavailable") from exc

    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@router.patch("/{report_id}", response_model=ReportRecord)
async def patch_report(report_id: str, patch: ReportUpdateRequest) -> ReportRecord:
    try:
        report = await report_store.update_report(report_id, patch)
    except Exception as exc:
        log.warning("report_patch_failed", report_id=report_id, error=str(exc))
        raise HTTPException(status_code=503, detail="report update failed") from exc

    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: str) -> None:
    try:
        deleted = await report_store.delete_report(report_id)
    except Exception as exc:
        log.warning("report_delete_failed", report_id=report_id, error=str(exc))
        raise HTTPException(status_code=503, detail="report delete failed") from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="report not found")


@router.get("/{report_id}/messages", response_model=list[ReportMessage])
async def list_report_messages(
    report_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[ReportMessage]:
    try:
        report = await report_store.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return await report_store.list_report_messages(report_id, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("report_messages_list_failed", report_id=report_id, error=str(exc))
        raise HTTPException(status_code=503, detail="report messages unavailable") from exc


@router.post(
    "/{report_id}/messages",
    response_model=ReportMessage,
    status_code=status.HTTP_201_CREATED,
)
async def create_report_message(report_id: str, payload: ReportMessageCreate) -> ReportMessage:
    try:
        report = await report_store.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")

        message = await report_store.append_report_message(report_id, payload)
        if message is None:
            raise HTTPException(status_code=503, detail="message persistence failed")
        return message
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("report_message_create_failed", report_id=report_id, error=str(exc))
        raise HTTPException(status_code=503, detail="report messages unavailable") from exc
