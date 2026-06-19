"""Persistence helpers for Briefing reports + report-scoped messages."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast

from neo4j.exceptions import ConstraintError

from app.cypher.report_read import (
    REPORT_BY_ID,
    REPORT_BY_SCOPE,
    REPORT_COUNT,
    REPORT_LIST,
    REPORT_MESSAGES_BY_REPORT_ID,
    REPORT_NEXT_PARAGRAPH,
)
from app.cypher.report_write import (
    REPORT_APPEND_MESSAGE,
    REPORT_CREATE,
    REPORT_DELETE,
    REPORT_ID_UNIQUE_CONSTRAINT,
    REPORT_SCOPE_UNIQUE_CONSTRAINT,
    REPORT_UPSERT,
)
from app.models.intel import IntelAnalysis
from app.models.report import (
    AccentTone,
    DossierMetric,
    MarginEntry,
    MessageRole,
    ReportCreateRequest,
    ReportMessage,
    ReportMessageCreate,
    ReportRecord,
    ReportStatus,
    ReportUpdateRequest,
)
from app.services.briefing import parse_munin_report
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


def _decode_metrics(raw: str | list[dict[str, Any]] | None) -> list[DossierMetric]:
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


def _decode_margin(raw: str | list[dict[str, Any]] | None) -> list[MarginEntry]:
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


def _coerce_report_status(value: object) -> ReportStatus:
    raw = str(value or "Draft")
    if raw in ("Draft", "Published", "Archived"):
        return cast(ReportStatus, raw)
    return "Draft"


def _coerce_message_role(value: object) -> MessageRole:
    raw = str(value or "system")
    if raw in ("user", "munin", "system"):
        return cast(MessageRole, raw)
    return "system"


def _row_to_report(row: dict[str, Any]) -> ReportRecord:
    created_at = _parse_dt(row.get("created_at"))
    updated_at = _parse_dt(row.get("updated_at"), fallback=created_at)
    return ReportRecord(
        id=str(row.get("id", "")),
        paragraph_num=int(row.get("paragraph_num") or 0),
        stamp=str(row.get("stamp") or ""),
        title=str(row.get("title") or ""),
        scope_key=row.get("scope_key"),
        status=_coerce_report_status(row.get("status")),
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


def _row_to_message(row: dict[str, Any]) -> ReportMessage:
    return ReportMessage(
        id=str(row.get("id") or ""),
        role=_coerce_message_role(row.get("role")),
        text=str(row.get("text") or ""),
        ts=_parse_dt(row.get("ts")),
        refs=[str(v) for v in (row.get("refs") or [])],
    )


def _report_params(
    report_id: str,
    paragraph_num: int,
    stamp: str,
    payload: ReportCreateRequest | ReportRecord,
) -> dict[str, Any]:
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
        "scope_key": getattr(payload, "scope_key", None),
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
    for _ in range(5):
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

        try:
            rows = await write_query(
                REPORT_CREATE, _report_params(report_id, paragraph, stamp, hydrated)
            )
        except ConstraintError:
            # REPORT_CREATE uses CREATE, so a duplicate id genuinely raises (report_id_unique).
            # Message-independent: if this id now resolves to a real node it was an id race →
            # retry with a fresh paragraph; otherwise it's a scope collision (CREATE rolled back,
            # id absent) → re-raise so get_or_create_report_by_scope re-reads the winner.
            if await get_report(report_id) is not None:
                continue
            raise
        if not rows:
            raise RuntimeError("failed to create report")
        return _row_to_report(rows[0])
    raise RuntimeError("failed to allocate a unique report id after retries")


async def update_report(report_id: str, patch: ReportUpdateRequest) -> ReportRecord | None:
    current = await get_report(report_id)
    if current is None:
        return None

    # merge patch over current, then re-validate so DossierMetric/MarginEntry rebuild from dicts.
    # exclude_none drops explicit-null patch fields (nulling a required field was never valid →
    # ReportRecord forbids it) so a PATCH like {"title": null} is a NO-OP, not a 500. Zero/empty
    # values (confidence=0.0, findings=[]) are not None → still applied.
    merged = ReportRecord.model_validate(
        {**current.model_dump(), **patch.model_dump(exclude_unset=True, exclude_none=True)}
    )
    rows = await write_query(
        REPORT_UPSERT,
        _report_params(report_id, current.paragraph_num, current.stamp, merged),
    )
    if not rows:
        return None
    return _row_to_report(rows[0])


# Munin threat label → DossierMetric accent tone (AccentTone Literal: sentinel|amber|sage).
_THREAT_TONE: dict[str, AccentTone] = {
    "CRITICAL": "amber",
    "HIGH": "amber",
    "ELEVATED": "amber",
    "MODERATE": "sentinel",
}
_DEFAULT_TONE: AccentTone = "sentinel"


def build_hydration_patch(analysis: IntelAnalysis, country_name: str) -> ReportUpdateRequest:
    """Map a finished Munin IntelAnalysis into a dossier hydration patch."""
    parsed = parse_munin_report(analysis.analysis)
    threat = analysis.threat_assessment or "MODERATE"
    metrics = [
        DossierMetric(
            label="Threat", value=threat, sub="assessment",
            tone=_THREAT_TONE.get(threat, _DEFAULT_TONE),
        ),
        DossierMetric(
            label="Confidence", value=f"{analysis.confidence:.0%}", sub="munin", tone="sage",
        ),
        DossierMetric(
            label="Sources", value=str(len(analysis.sources_used)), sub="evidence", tone="sentinel",
        ),
    ]
    return ReportUpdateRequest(
        confidence=analysis.confidence,
        context=parsed.context,
        findings=parsed.findings,
        body_title=f"{country_name} — Munin Lagebriefing",
        body_paragraphs=parsed.body_paragraphs,
        sources=analysis.sources_used,
        metrics=metrics,
    )


async def bootstrap_report_schema() -> None:
    """Idempotent unique constraints. Run once at startup (main.py lifespan)."""
    await write_query(REPORT_ID_UNIQUE_CONSTRAINT, {})
    await write_query(REPORT_SCOPE_UNIQUE_CONSTRAINT, {})


async def get_report_by_scope(scope_key: str) -> ReportRecord | None:
    rows = await read_query(REPORT_BY_SCOPE, {"scope_key": scope_key})
    return _row_to_report(rows[0]) if rows else None


async def get_or_create_report_by_scope(
    scope_key: str, title: str, location: str, coords: str
) -> ReportRecord:
    existing = await get_report_by_scope(scope_key)
    if existing is not None:
        return existing
    try:
        return await create_report(
            ReportCreateRequest(
                scope_key=scope_key, title=title, location=location, coords=coords
            )
        )
    except ConstraintError:
        winner = await get_report_by_scope(scope_key)
        if winner is None:
            raise
        return winner


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
