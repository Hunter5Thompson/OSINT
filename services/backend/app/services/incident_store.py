"""Neo4j-backed Incident persistence — deterministic templates only."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from app.cypher.incident_read import (
    INCIDENT_BY_ID,
    INCIDENT_LIST_OPEN,
    INCIDENT_NEXT_ORDINAL,
)
from app.cypher.incident_write import INCIDENT_DELETE, INCIDENT_UPSERT
from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.services.neo4j_client import read_query, write_query


def _decode_timeline(raw: str | list | None) -> list[IncidentTimelineEvent]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
    else:
        data = raw
    if not isinstance(data, list):
        return []
    out: list[IncidentTimelineEvent] = []
    for item in data:
        try:
            out.append(IncidentTimelineEvent.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out


def _row_to_incident(row: dict) -> Incident:
    return Incident(
        id=str(row["id"]),
        kind=str(row.get("kind") or "manual"),
        title=str(row.get("title") or ""),
        severity=str(row.get("severity") or "low"),  # type: ignore[arg-type]
        coords=(float(row.get("lat") or 0.0), float(row.get("lon") or 0.0)),
        location=str(row.get("location") or ""),
        status=IncidentStatus(str(row.get("status") or "open")),
        trigger_ts=_parse_dt(row.get("trigger_ts")),
        closed_ts=_parse_dt(row.get("closed_ts")) if row.get("closed_ts") else None,
        sources=[str(v) for v in (row.get("sources") or [])],
        layer_hints=[str(v) for v in (row.get("layer_hints") or [])],
        timeline=_decode_timeline(row.get("timeline_json")),
    )


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        s = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(s).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _upsert_params(record: Incident, ordinal: int) -> dict:
    return {
        "incident_id": record.id,
        "ordinal": ordinal,
        "kind": record.kind,
        "title": record.title,
        "severity": record.severity,
        "lat": record.coords[0],
        "lon": record.coords[1],
        "location": record.location,
        "status": record.status.value,
        "trigger_ts": record.trigger_ts.isoformat(),
        "closed_ts": record.closed_ts.isoformat() if record.closed_ts else None,
        "sources": record.sources,
        "layer_hints": record.layer_hints,
        "timeline_json": json.dumps(
            [e.model_dump() for e in record.timeline],
            ensure_ascii=True,
        ),
        "now": datetime.now(UTC).isoformat(),
    }


async def list_open_incidents(limit: int = 50) -> list[Incident]:
    rows = await read_query(INCIDENT_LIST_OPEN, {"limit": limit})
    return [_row_to_incident(r) for r in rows]


async def get_incident(incident_id: str) -> Incident | None:
    rows = await read_query(INCIDENT_BY_ID, {"incident_id": incident_id})
    if not rows:
        return None
    return _row_to_incident(rows[0])


async def create_incident(payload: IncidentCreateRequest) -> Incident:
    ordinal_rows = await read_query(INCIDENT_NEXT_ORDINAL, {})
    ordinal = int(ordinal_rows[0].get("next_ordinal") or 1) if ordinal_rows else 1
    incident_id = f"inc-{ordinal:03d}"
    now = datetime.now(UTC)
    initial = IncidentTimelineEvent(
        t_offset_s=0.0,
        kind="trigger",
        text=payload.initial_text or f"trigger · {payload.kind}",
        severity=payload.severity,
    )
    record = Incident(
        id=incident_id,
        kind=payload.kind,
        title=payload.title,
        severity=payload.severity,
        coords=payload.coords,
        location=payload.location,
        status=IncidentStatus.OPEN,
        trigger_ts=now,
        sources=payload.sources,
        layer_hints=payload.layer_hints,
        timeline=[initial],
    )
    rows = await write_query(INCIDENT_UPSERT, _upsert_params(record, ordinal))
    if not rows:
        raise RuntimeError("failed to persist incident")
    return _row_to_incident(rows[0])


async def append_timeline_event(
    incident_id: str,
    event: IncidentTimelineEvent,
) -> Incident | None:
    current = await get_incident(incident_id)
    if current is None:
        return None
    next_timeline = [*current.timeline, event]
    next_record = current.model_copy(update={"timeline": next_timeline})
    # Re-derive ordinal from id (`inc-007` → 7); avoids an extra Cypher hop.
    try:
        ordinal = int(incident_id.split("-")[-1])
    except (ValueError, IndexError):
        ordinal = 1
    rows = await write_query(INCIDENT_UPSERT, _upsert_params(next_record, ordinal))
    if not rows:
        return None
    return _row_to_incident(rows[0])


async def close_incident(
    incident_id: str,
    status: IncidentStatus,
    when: datetime | None = None,
) -> Incident | None:
    current = await get_incident(incident_id)
    if current is None:
        return None
    next_record = current.model_copy(
        update={"status": status, "closed_ts": when or datetime.now(UTC)}
    )
    try:
        ordinal = int(incident_id.split("-")[-1])
    except (ValueError, IndexError):
        ordinal = 1
    rows = await write_query(INCIDENT_UPSERT, _upsert_params(next_record, ordinal))
    if not rows:
        return None
    return _row_to_incident(rows[0])


async def delete_incident(incident_id: str) -> bool:
    current = await get_incident(incident_id)
    if current is None:
        return False
    await write_query(INCIDENT_DELETE, {"incident_id": incident_id})
    return True
