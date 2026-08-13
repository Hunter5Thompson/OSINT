"""Neo4j-backed Incident persistence — deterministic templates only."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from app.cypher.incident_read import (
    INCIDENT_BY_ID,
    INCIDENT_LIST_OPEN,
    INCIDENT_LIST_REHYDRATE_CANDIDATES,
)
from app.cypher.incident_write import INCIDENT_DELETE, INCIDENT_UPSERT
from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
    Severity,
)
from app.services._loc_key import incident_key
from app.services.neo4j_client import read_query, write_query
from app.services.spatial_catalog import (
    IncidentSpatialProjection,
    SpatialCatalogLoader,
)

_REHYDRATE_LIMIT = 500
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


async def create_incident(payload: IncidentCreateRequest) -> Incident:
    incident_id = f"inc-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    ordinal = int(now.timestamp() * 1000) % 2_000_000_000
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
    rows = await write_query(
        INCIDENT_UPSERT,
        _upsert_params(record, ordinal, await _incident_projection(record)),
    )
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
    ordinal = int(datetime.now(UTC).timestamp() * 1000) % 2_000_000_000
    rows = await write_query(
        INCIDENT_UPSERT,
        _upsert_params(next_record, ordinal, await _incident_projection(next_record)),
    )
    if not rows:
        return None
    return _row_to_incident(rows[0])


async def apply_signal_update(
    incident_id: str,
    *,
    timeline_event: IncidentTimelineEvent,
    severity: str,
    sources_to_merge: list[str],
    layer_hints_to_merge: list[str],
) -> Incident | None:
    """Atomic write: append a timeline event, escalate severity, merge sources/hints.

    No-op (returns ``None``) if the incident does not exist. Severity is
    monotonic in the caller (ClusterStore only escalates); this function
    simply writes the value provided.
    """
    current = await get_incident(incident_id)
    if current is None:
        return None
    merged_sources = list(dict.fromkeys([*current.sources, *sources_to_merge]))
    merged_hints = list(dict.fromkeys([*current.layer_hints, *layer_hints_to_merge]))
    next_record = current.model_copy(
        update={
            "timeline": [*current.timeline, timeline_event],
            "severity": severity,
            "sources": merged_sources,
            "layer_hints": merged_hints,
        }
    )
    ordinal = int(datetime.now(UTC).timestamp() * 1000) % 2_000_000_000
    rows = await write_query(
        INCIDENT_UPSERT,
        _upsert_params(next_record, ordinal, await _incident_projection(next_record)),
    )
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
    # Idempotent: any non-open status is terminal and is returned unchanged.
    if current.status != IncidentStatus.OPEN:
        return current
    next_record = current.model_copy(
        update={"status": status, "closed_ts": when or datetime.now(UTC)}
    )
    ordinal = int(datetime.now(UTC).timestamp() * 1000) % 2_000_000_000
    rows = await write_query(
        INCIDENT_UPSERT,
        _upsert_params(next_record, ordinal, await _incident_projection(next_record)),
    )
    if not rows:
        return None
    return _row_to_incident(rows[0])


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
