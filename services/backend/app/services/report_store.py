"""Persistence helpers for Briefing reports + report-scoped messages."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from datetime import UTC, datetime

from app.cypher.report_read import (
    REPORT_BY_ID,
    REPORT_COUNT,
    REPORT_LIST,
    REPORT_MESSAGES_BY_REPORT_ID,
    REPORT_NEXT_PARAGRAPH,
)
from app.cypher.report_write import REPORT_APPEND_MESSAGE, REPORT_DELETE, REPORT_UPSERT
from app.models.report import (
    DossierMetric,
    MarginEntry,
    ReportCreateRequest,
    ReportMessage,
    ReportMessageCreate,
    ReportRecord,
    ReportUpdateRequest,
)
from app.services.neo4j_client import read_query, write_query

_DEFAULT_FINDINGS = [
    "Initial signal basket created. Add first confirmed indicator.",
    "Attach one corroborating source before publication.",
    "Define next data pull and confidence target.",
]

_DEFAULT_METRICS = [
    DossierMetric(label="coverage", value="0", sub="sources linked", tone="sentinel"),
    DossierMetric(label="window", value="24h", sub="analysis span", tone="amber"),
    DossierMetric(label="confidence", value="0.62", sub="initial", tone="sage"),
]

_DEFAULT_MARGIN = [
    MarginEntry(label="status", value="draft"),
    MarginEntry(label="owner", value="analyst"),
]


def _roman_month(month_index: int) -> str:
    romans = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
    return romans[month_index]


def _stamp_from(now: datetime) -> str:
    day = str(now.day).zfill(2)
    return f"{day}·{_roman_month(now.month - 1)}"


def _parse_dt(value: str | datetime | None, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(value).astimezone(UTC)
        except ValueError:
            pass
    return fallback or datetime.now(UTC)


def _decode_metrics(raw: str | list[dict] | None) -> list[DossierMetric]:
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            data = []
    else:
        data = []
    out: list[DossierMetric] = []
    for item in data:
        try:
            out.append(DossierMetric.model_validate(item))
        except Exception:
            continue
    return out


def _decode_margin(raw: str | list[dict] | None) -> list[MarginEntry]:
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            data = []
    else:
        data = []
    out: list[MarginEntry] = []
    for item in data:
        try:
            out.append(MarginEntry.model_validate(item))
        except Exception:
            continue
    return out


def _row_to_report(row: dict) -> ReportRecord:
    created_at = _parse_dt(row.get("created_at"))
    updated_at = _parse_dt(row.get("updated_at"), fallback=created_at)
    return ReportRecord(
        id=str(row.get("id", "")),
        paragraph_num=int(row.get("paragraph_num") or 0),
        stamp=str(row.get("stamp") or ""),
        title=str(row.get("title") or ""),
        status=str(row.get("status") or "Draft"),
        confidence=float(row.get("confidence") or 0.0),
        location=str(row.get("location") or ""),
        coords=str(row.get("coords") or ""),
        findings=[str(v) for v in (row.get("findings") or [])],
        metrics=_decode_metrics(row.get("metrics_json")),
        context=str(row.get("context") or ""),
        body_title=str(row.get("body_title") or ""),
        body_paragraphs=[str(v) for v in (row.get("body_paragraphs") or [])],
        margin=_decode_margin(row.get("margin_json")),
        sources=[str(v) for v in (row.get("sources") or [])],
        created_at=created_at,
        updated_at=updated_at,
    )


def _row_to_message(row: dict) -> ReportMessage:
    return ReportMessage(
        id=str(row.get("id") or ""),
        role=str(row.get("role") or "system"),
        text=str(row.get("text") or ""),
        ts=_parse_dt(row.get("ts")),
        refs=[str(v) for v in (row.get("refs") or [])],
    )


def _report_params(
    report_id: str,
    paragraph_num: int,
    stamp: str,
    payload: ReportCreateRequest | ReportRecord,
) -> dict:
    metrics = payload.metrics if isinstance(payload.metrics, list) else []
    margin = payload.margin if isinstance(payload.margin, list) else []
    return {
        "report_id": report_id,
        "paragraph_num": paragraph_num,
        "stamp": stamp,
        "title": payload.title,
        "status": payload.status,
        "confidence": float(payload.confidence),
        "location": payload.location,
        "coords": payload.coords,
        "findings": payload.findings,
        "metrics_json": json.dumps([m.model_dump() for m in metrics], ensure_ascii=True),
        "context": payload.context,
        "body_title": payload.body_title,
        "body_paragraphs": payload.body_paragraphs,
        "margin_json": json.dumps([m.model_dump() for m in margin], ensure_ascii=True),
        "sources": payload.sources,
        "now": datetime.now(UTC).isoformat(),
    }


async def _next_paragraph() -> int:
    rows = await read_query(REPORT_NEXT_PARAGRAPH, {})
    if not rows:
        return 1
    return int(rows[0].get("next_paragraph") or 1)


async def list_reports(limit: int = 200) -> list[ReportRecord]:
    rows = await read_query(REPORT_LIST, {"limit": limit})
    return [_row_to_report(r) for r in rows]


async def get_report(report_id: str) -> ReportRecord | None:
    rows = await read_query(REPORT_BY_ID, {"report_id": report_id})
    if not rows:
        return None
    return _row_to_report(rows[0])


async def create_report(payload: ReportCreateRequest) -> ReportRecord:
    paragraph = await _next_paragraph()
    now = datetime.now(UTC)
    stamp = _stamp_from(now)
    report_id = f"r-{paragraph:03d}"

    findings = payload.findings or deepcopy(_DEFAULT_FINDINGS)
    metrics = payload.metrics or deepcopy(_DEFAULT_METRICS)
    margin = payload.margin or deepcopy(_DEFAULT_MARGIN)
    sources = payload.sources or ["pending·1"]
    body_paragraphs = payload.body_paragraphs or [
        (
            "Start with the operational summary, then expand into competing "
            "hypotheses, risk corridors, and open questions."
        ),
    ]

    hydrated = payload.model_copy(
        update={
            "findings": findings,
            "metrics": metrics,
            "margin": margin,
            "sources": sources,
            "body_paragraphs": body_paragraphs,
        }
    )

    rows = await write_query(REPORT_UPSERT, _report_params(report_id, paragraph, stamp, hydrated))
    if not rows:
        raise RuntimeError("failed to create report")
    return _row_to_report(rows[0])


async def update_report(report_id: str, patch: ReportUpdateRequest) -> ReportRecord | None:
    current = await get_report(report_id)
    if current is None:
        return None

    merged = current.model_copy(update=patch.model_dump(exclude_unset=True))
    rows = await write_query(
        REPORT_UPSERT,
        _report_params(report_id, current.paragraph_num, current.stamp, merged),
    )
    if not rows:
        return None
    return _row_to_report(rows[0])


async def delete_report(report_id: str) -> bool:
    current = await get_report(report_id)
    if current is None:
        return False
    await write_query(REPORT_DELETE, {"report_id": report_id})
    return True


async def list_report_messages(report_id: str, limit: int = 500) -> list[ReportMessage]:
    rows = await read_query(
        REPORT_MESSAGES_BY_REPORT_ID,
        {"report_id": report_id, "limit": limit},
    )
    return [_row_to_message(r) for r in rows]


async def append_report_message(
    report_id: str,
    payload: ReportMessageCreate,
) -> ReportMessage | None:
    ts = payload.ts or datetime.now(UTC)
    rows = await write_query(
        REPORT_APPEND_MESSAGE,
        {
            "report_id": report_id,
            "message_id": f"msg-{time.time_ns()}",
            "role": payload.role,
            "text": payload.text,
            "ts": ts.isoformat(),
            "refs": payload.refs,
            "ordering": time.time_ns(),
            "now": datetime.now(UTC).isoformat(),
        },
    )
    if not rows:
        return None
    return _row_to_message(rows[0])


async def count_reports() -> int:
    rows = await read_query(REPORT_COUNT, {})
    if not rows:
        return 0
    return int(rows[0].get("count") or 0)
