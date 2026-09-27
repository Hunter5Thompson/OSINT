"""Neo4j-backed Incident persistence — deterministic templates only."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

import neo4j

from app.cypher.incident_read import (
    INCIDENT_BY_ID,
    INCIDENT_LIST_OPEN,
    INCIDENT_LIST_REHYDRATE_CANDIDATES,
)
from app.cypher.incident_write import (
    INCIDENT_CREATE_IDEMPOTENT,
    INCIDENT_DELETE,
    INCIDENT_MUTATION_CLOSE,
    INCIDENT_MUTATION_LOCK,
    INCIDENT_MUTATION_READ,
    INCIDENT_MUTATION_UPDATE,
    INCIDENT_UPSERT,
)
from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
    Severity,
)
from app.services._loc_key import incident_key
from app.services.neo4j_client import read_query, write_query, write_transaction
from app.services.spatial_catalog import (
    IncidentSpatialProjection,
    SpatialCatalogLoader,
)

_REHYDRATE_LIMIT = 500
MutationStatus = Literal["applied", "unchanged", "not_found"]


@dataclass(frozen=True)
class MutationResult:
    status: MutationStatus
    incident: Incident | None


def _ordinal_ms(now: datetime) -> int:
    """Epoch milliseconds. A modulo here wrapped rehydrate order about every 23 days."""
    return int(now.timestamp() * 1000)
_incident_spatial_catalog: SpatialCatalogLoader | None = None


def configure_incident_spatial_catalog(loader: SpatialCatalogLoader | None) -> None:
    global _incident_spatial_catalog
    _incident_spatial_catalog = loader


def _decode_timeline(raw: str | list[Any] | None) -> list[IncidentTimelineEvent]:
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


def _row_to_incident(row: dict[str, Any]) -> Incident:
    return Incident(
        id=str(row["id"]),
        kind=str(row.get("kind") or "manual"),
        title=str(row.get("title") or ""),
        severity=cast(Severity, str(row.get("severity") or "low")),
        coords=(float(row.get("lat") or 0.0), float(row.get("lon") or 0.0)),
        location=str(row.get("location") or ""),
        status=IncidentStatus(str(row.get("status") or "open")),
        trigger_ts=_parse_dt(row.get("trigger_ts")),
        closed_ts=_parse_dt(row.get("closed_ts")) if row.get("closed_ts") else None,
        sources=[str(v) for v in (row.get("sources") or [])],
        layer_hints=[str(v) for v in (row.get("layer_hints") or [])],
        timeline=_decode_timeline(row.get("timeline_json")),
    )


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        s = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(s).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _upsert_params(
    record: Incident,
    ordinal: int,
    projection: IncidentSpatialProjection | None = None,
) -> dict[str, Any]:
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
        "loc_key": incident_key(record.location, record.coords[0], record.coords[1]),
        "spatial_write": projection is not None,
        "country_scope_key": projection.country_scope_key if projection else None,
        "admin1_scope_key": projection.admin1_scope_key if projection else None,
        "admin2_scope_key": projection.admin2_scope_key if projection else None,
        "spatial_basis": projection.spatial_basis if projection else None,
        "spatial_precision": projection.spatial_precision if projection else None,
        "spatial_catalog_revision": (
            projection.spatial_catalog_revision if projection else None
        ),
        "spatial_derivation_revision": (
            projection.spatial_derivation_revision if projection else None
        ),
        "spatial_conflict": projection.spatial_conflict if projection else False,
        "spatial_conflict_scope_keys": (
            list(projection.spatial_conflict_scope_keys) if projection else []
        ),
        "spatial_derivation_status": (
            projection.spatial_derivation_status if projection else "unavailable"
        ),
        "now": datetime.now(UTC).isoformat(),
    }


async def _incident_projection(record: Incident) -> IncidentSpatialProjection | None:
    loader = _incident_spatial_catalog
    if loader is None or record.coords == (0.0, 0.0):
        return None
    result = await loader.project_incident_point(
        latitude=record.coords[0],
        longitude=record.coords[1],
    )
    return result if isinstance(result, IncidentSpatialProjection) else None


async def list_open_incidents(limit: int = 50) -> list[Incident]:
    rows = await read_query(INCIDENT_LIST_OPEN, {"limit": limit})
    return [_row_to_incident(r) for r in rows]


async def get_incident(incident_id: str) -> Incident | None:
    rows = await read_query(INCIDENT_BY_ID, {"incident_id": incident_id})
    if not rows:
        return None
    return _row_to_incident(rows[0])


async def create_incident(
    payload: IncidentCreateRequest, *, incident_id: str | None = None
) -> Incident:
    """Create an incident; an explicit id selects the promoter's retry-safe path.

    The retry-safe query requires the deployed `incident_id_unique` constraint.
    It only initializes a newly-created node and returns current state on replay.
    """
    retry_safe = incident_id is not None
    incident_id = incident_id or f"inc-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    ordinal = _ordinal_ms(now)
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
    params = _upsert_params(record, ordinal, await _incident_projection(record))
    if retry_safe:
        params["create_nonce"] = uuid4().hex
    rows = await write_query(
        INCIDENT_CREATE_IDEMPOTENT if retry_safe else INCIDENT_UPSERT,
        params,
    )
    if not rows:
        raise RuntimeError("failed to persist incident")
    return _row_to_incident(rows[0])


async def append_timeline_event(
    incident_id: str,
    event: IncidentTimelineEvent,
) -> MutationResult:
    return await _mutate_open_incident(
        incident_id,
        event=event,
        severity=None,
        sources_to_merge=[],
        layer_hints_to_merge=[],
    )


async def apply_signal_update(
    incident_id: str,
    *,
    timeline_event: IncidentTimelineEvent,
    severity: str,
    sources_to_merge: list[str],
    layer_hints_to_merge: list[str],
) -> MutationResult:
    """Append one signal while preserving concurrent fields and events."""
    return await _mutate_open_incident(
        incident_id,
        event=timeline_event,
        severity=severity,
        sources_to_merge=sources_to_merge,
        layer_hints_to_merge=layer_hints_to_merge,
    )


_SEVERITY_ORDER = {"low": 0, "elevated": 1, "high": 2, "critical": 3}


async def _transaction_current(
    transaction: neo4j.AsyncManagedTransaction,
    incident_id: str,
    lock_token: str,
) -> dict[str, Any] | None:
    lock_result = await transaction.run(
        INCIDENT_MUTATION_LOCK,
        incident_id=incident_id,
        lock_token=lock_token,
    )
    lock_row = await lock_result.single()
    if lock_row is None:
        return None
    result = await transaction.run(INCIDENT_MUTATION_READ, incident_id=incident_id)
    row = await result.single()
    return dict(row) if row is not None else None


async def _mutate_open_incident(
    incident_id: str,
    *,
    event: IncidentTimelineEvent,
    severity: str | None,
    sources_to_merge: list[str],
    layer_hints_to_merge: list[str],
) -> MutationResult:
    event_snapshot = event.model_copy(deep=True)
    source_snapshot = tuple(sources_to_merge)
    hint_snapshot = tuple(layer_hints_to_merge)
    operation_id = uuid4().hex
    lock_token = uuid4().hex
    now = datetime.now(UTC).isoformat()

    async def mutate(transaction: neo4j.AsyncManagedTransaction) -> MutationResult:
        row = await _transaction_current(transaction, incident_id, lock_token)
        if row is None:
            return MutationResult("not_found", None)
        current = _row_to_incident(row)
        applied_ids = list(row.get("applied_mutation_ids") or [])
        if operation_id in applied_ids:
            return MutationResult("applied", current)
        if current.status != IncidentStatus.OPEN:
            return MutationResult("unchanged", current)

        timeline = [*current.timeline, event_snapshot]
        merged_sources = list(dict.fromkeys([*current.sources, *source_snapshot]))
        merged_hints = list(dict.fromkeys([*current.layer_hints, *hint_snapshot]))
        selected_severity = current.severity
        if severity is not None and _SEVERITY_ORDER[severity] > _SEVERITY_ORDER[current.severity]:
            selected_severity = cast(Severity, severity)
        timeline_json = json.dumps([item.model_dump() for item in timeline], ensure_ascii=True)
        params = {
            "incident_id": incident_id,
            "severity": selected_severity,
            "sources": merged_sources,
            "layer_hints": merged_hints,
            "timeline_json": timeline_json,
            "applied_mutation_ids": [*applied_ids, operation_id],
            "now": now,
        }
        result = await transaction.run(INCIDENT_MUTATION_UPDATE, params)
        updated = await result.single()
        if updated is None:
            return MutationResult("not_found", None)
        return MutationResult("applied", _row_to_incident(dict(updated)))

    return await write_transaction(
        mutate, metadata={"incident_mutation_id": operation_id}
    )


async def close_incident(
    incident_id: str,
    status: IncidentStatus,
    when: datetime | None = None,
) -> MutationResult:
    if status == IncidentStatus.OPEN:
        raise ValueError("close_incident target status must be terminal")
    operation_id = uuid4().hex
    lock_token = uuid4().hex
    now = datetime.now(UTC).isoformat()
    closed_ts = (when or datetime.now(UTC)).isoformat()

    async def close(transaction: neo4j.AsyncManagedTransaction) -> MutationResult:
        row = await _transaction_current(transaction, incident_id, lock_token)
        if row is None:
            return MutationResult("not_found", None)
        current = _row_to_incident(row)
        applied_ids = list(row.get("applied_mutation_ids") or [])
        if operation_id in applied_ids:
            return MutationResult("applied", current)
        if current.status != IncidentStatus.OPEN:
            return MutationResult("unchanged", current)
        result = await transaction.run(
            INCIDENT_MUTATION_CLOSE,
            {
                "incident_id": incident_id,
                "status": status.value,
                "closed_ts": closed_ts,
                "applied_mutation_ids": [*applied_ids, operation_id],
                "now": now,
            },
        )
        updated = await result.single()
        if updated is None:
            return MutationResult("not_found", None)
        return MutationResult("applied", _row_to_incident(dict(updated)))

    return await write_transaction(
        close, metadata={"incident_mutation_id": operation_id}
    )


async def delete_incident(incident_id: str) -> bool:
    current = await get_incident(incident_id)
    if current is None:
        return False
    await write_query(INCIDENT_DELETE, {"incident_id": incident_id})
    return True


async def list_owned_for_rehydrate() -> list[Incident]:
    """Return open/promoted incidents owned by the auto-promoter.

    Filters in Python by the ``auto_promoter:v1`` marker in ``layer_hints``.
    Status filter also admits ``PROMOTED`` so the Promoter can rehydrate
    clusters that the analyst owned at restart time.
    """
    rows = await read_query(
        INCIDENT_LIST_REHYDRATE_CANDIDATES,
        {"limit": _REHYDRATE_LIMIT},
    )
    owned: list[Incident] = []
    for row in rows:
        if "auto_promoter:v1" not in (row.get("layer_hints") or []):
            continue
        owned.append(_row_to_incident(row))
    return owned
