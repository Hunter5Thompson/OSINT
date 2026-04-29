# ODIN S4 · War Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the live-incident cockpit (`/warroom`) — incident SSE stream + Toast pattern + four-quadrant cockpit (§I Theatre · §II Timeline · §III Munin · §IV Raw) — fulfilling spec §4.4 of `docs/superpowers/specs/2026-04-14-odin-4layer-hlidskjalf-design.md`.

**Architecture:** A new in-memory `IncidentStream` mirrors the existing `SignalStream` (ring buffer + SSE replay) so the frontend can subscribe over `/api/incidents/stream`. Incidents persist to Neo4j via deterministic Cypher templates (no LLM-generated queries — project rule). A frontend `useIncidents` hook fans the stream into a global `IncidentContext` consumed by an `IncidentToast` (any page) and by the dedicated `WarRoomPage`. The four quadrants compose existing primitives (Cesium viewer, signal-feed item, agent message) plus three new ones inspired by the design-`i` reference (LeaderCallout, MuninCrystal, AgentStreamLine).

**Tech Stack:** FastAPI + Pydantic v2 + Neo4j (backend) · React 19 + TypeScript + Vite + Cesium (frontend) · sse-starlette (server) + native EventSource (client) · pytest + Vitest + RTL.

**Visual Direction:** Hlíðskjalf Noir (locked — `services/frontend/src/theme/hlidskjalf.css`). Two specific motifs are borrowed from the design reference `i` ("Pandemic Prediction System" big-board) but **re-coloured** for Hlíðskjalf — no cyan, no rounded corners:
- **Leader callouts** on §I Theatre: floating Basalt cards with a hair-line leader running from the card edge to the entity dot on the globe, terminating in a small Sentinel/Amber dot. Card label in Hanken Grotesk eyebrow style; KPI in Instrument Serif italic.
- **Munin crystal** in §III Munin Stream: a small inline SVG (an isometric three-stack of stroked rhombi in Amber on Granite) flanked by a fan of branched hair-lines that point to live tool-call labels — the visual bridges the existing Orrery vocabulary into the agent context.

The arc-route motif from reference `u` is borrowed only for the **empty-state Theatre** (no active incident): ambient global flow lines fade in at low opacity behind the "§ no active incident · standing watch" message.

---

## File Structure

### Backend (created)
- `services/backend/app/models/incident.py` — Pydantic models for Incident + IncidentEnvelope
- `services/backend/app/cypher/incident_read.py` — read-only Cypher (list, by_id, count)
- `services/backend/app/cypher/incident_write.py` — write Cypher (upsert, close, append timeline event)
- `services/backend/app/services/incident_store.py` — Neo4j-backed CRUD over the templates
- `services/backend/app/services/incident_stream.py` — in-memory ring buffer + live fan-out (mirrors `signal_stream.py`)
- `services/backend/app/routers/incidents.py` — REST + SSE + admin trigger
- `services/backend/tests/test_incident_models.py`
- `services/backend/tests/test_incident_store.py`
- `services/backend/tests/test_incident_stream.py`
- `services/backend/tests/test_incidents_router.py`

### Backend (modified)
- `services/backend/app/main.py` — import + mount `incidents.router`

### Frontend (created — primitives)
- `services/frontend/src/components/hlidskjalf/IncidentBar.tsx`
- `services/frontend/src/components/hlidskjalf/IncidentToast.tsx`
- `services/frontend/src/components/hlidskjalf/AgentStreamLine.tsx`
- `services/frontend/src/components/hlidskjalf/LeaderCallout.tsx`
- `services/frontend/src/components/hlidskjalf/MuninCrystal.tsx`

### Frontend (created — War Room components + glue)
- `services/frontend/src/components/warroom/TheatreQuadrant.tsx`
- `services/frontend/src/components/warroom/TimelineQuadrant.tsx`
- `services/frontend/src/components/warroom/MuninStreamQuadrant.tsx`
- `services/frontend/src/components/warroom/RawSourcesQuadrant.tsx`
- `services/frontend/src/components/warroom/warRoomLayout.css`
- `services/frontend/src/state/IncidentProvider.tsx` — single SSE subscription + React context for the whole tree
- `services/frontend/src/hooks/useIncidents.ts` — thin context consumer
- `services/frontend/src/hooks/useTPlus.ts` — `T+hh:mm:ss` clock anchored to a trigger timestamp
- `services/frontend/src/types/incident.ts`

### Frontend (modified)
- `services/frontend/src/services/api.ts` — add `INCIDENT_STREAM_URL`, `getIncidents`, `triggerIncident` (admin), `INCIDENT_MUNIN_URL` helper
- `services/frontend/src/app/AppShell.tsx` — wrap with `<IncidentProvider>`, mount `<IncidentToast />`
- `services/frontend/src/components/hlidskjalf/TopBar.tsx` — pulse War Room dot via `useIncidents` when an incident is active
- `services/frontend/src/pages/WarRoomPage.tsx` — replace stub with full assembly

### Frontend (tests created)
- `services/frontend/src/hooks/__tests__/useIncidents.test.tsx` — provider+consumer behaviour
- `services/frontend/src/hooks/__tests__/useTPlus.test.ts`
- `services/frontend/src/components/hlidskjalf/IncidentBar.test.tsx`
- `services/frontend/src/components/hlidskjalf/IncidentToast.test.tsx`
- `services/frontend/src/components/hlidskjalf/AgentStreamLine.test.tsx`
- `services/frontend/src/components/hlidskjalf/LeaderCallout.test.tsx`
- `services/frontend/src/components/hlidskjalf/MuninCrystal.test.tsx`
- `services/frontend/src/components/warroom/TimelineQuadrant.test.tsx`
- `services/frontend/src/components/warroom/MuninStreamQuadrant.test.tsx`
- `services/frontend/src/components/warroom/RawSourcesQuadrant.test.tsx`
- `services/frontend/src/pages/WarRoomPage.test.tsx`

---

## Scope Cuts vs. Spec §4.4

These items in spec §4.4 are explicitly deferred and noted in the plan body so reviewers can see the tradeoff:

| Spec item | v1 behaviour | Deferred to |
|---|---|---|
| Real `services/incident-detector` (FIRMS-cluster, UCDP-delta, AIS-anomaly) | Out of scope per spec §8. v1 ships only the admin POST trigger. | Follow-up spec |
| Multi-incident bar collapsing list | v1 shows only the most recent active incident in the bar. Older actives still in the API list but not surfaced. | S4.1 if needed |
| WebSocket Munin upgrade (bidirectional) | Spec §6 explicitly allows SSE fallback for v1. Use `/api/intel/query` SSE keyed on `report_id = "incident-<id>"`. | Future |
| Munin auto-runs on incident open + tool-call breadcrumbs to dedicated stream | v1: Munin runs on the first user "Ask" inside §III via the existing `queryIntel` SSE (`/api/intel/query`). Status frames (`{ agent }`) become AgentStreamLine entries; the final `IntelAnalysis.analysis` body (prefixed by `threat_assessment` when present) populates the working hypothesis. No auto-on-open. | Future |
| Promote-to-dossier with pre-filled findings + agent-context init | v1 wires the button to POST `/api/reports` with `title`, `location`, `coords`, `findings=[incident.title]`, `confidence=incident.severity_to_conf`. Pre-fill the body title; leave full prefilling to a follow-up. | Polish PR |

---

## Task 1 · Backend Incident Models

**Files:**
- Create: `services/backend/app/models/incident.py`
- Test:   `services/backend/tests/test_incident_models.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/test_incident_models.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentEnvelope,
    IncidentStatus,
    IncidentTimelineEvent,
    SEVERITY_TO_CONF,
)


def test_severity_table_covers_all_levels() -> None:
    assert set(SEVERITY_TO_CONF) == {"low", "elevated", "high", "critical"}
    assert 0.0 < SEVERITY_TO_CONF["low"] < SEVERITY_TO_CONF["critical"] <= 1.0


def test_incident_create_request_minimum_fields() -> None:
    req = IncidentCreateRequest(
        title="Sinjar ridge thermal cluster",
        kind="firms.cluster",
        severity="high",
        coords=[36.34, 41.87],
        location="Sinjar ridge",
        sources=["firms·1", "ucdp·#44821"],
    )
    assert req.severity == "high"
    assert req.coords == (36.34, 41.87)


def test_incident_create_request_rejects_bad_coords() -> None:
    with pytest.raises(ValidationError):
        IncidentCreateRequest(
            title="bad",
            kind="firms.cluster",
            severity="low",
            coords=[200.0, 0.0],
            location="-",
        )


def test_incident_record_status_default_open() -> None:
    inc = Incident(
        id="inc-001",
        kind="firms.cluster",
        title="x",
        severity="low",
        coords=(0.0, 0.0),
        location="-",
        status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
        sources=[],
        timeline=[],
    )
    assert inc.status is IncidentStatus.OPEN
    assert inc.confidence == pytest.approx(SEVERITY_TO_CONF["low"], rel=1e-6)


def test_envelope_has_event_id_and_type() -> None:
    env = IncidentEnvelope(
        event_id="0001712841723482-000001",
        ts="2026-04-14T16:42:03.482Z",
        type="incident.open",
        payload=Incident(
            id="inc-002",
            kind="firms.cluster",
            title="x",
            severity="elevated",
            coords=(10.0, 20.0),
            location="-",
            status=IncidentStatus.OPEN,
            trigger_ts=datetime.now(UTC),
            sources=[],
            timeline=[IncidentTimelineEvent(t_offset_s=0.0, kind="trigger", text="t0")],
        ),
    )
    assert env.type == "incident.open"
    assert env.payload.timeline[0].kind == "trigger"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/backend && uv run pytest tests/test_incident_models.py -x
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.incident'`.

- [ ] **Step 3: Write minimal implementation**

```python
# services/backend/app/models/incident.py
"""Pydantic models for /api/incidents.

The severity vocabulary is fixed (low/elevated/high/critical) and maps to the
spec's `Conf` field via SEVERITY_TO_CONF. Trigger detection is out of scope
for S4 — incidents are created via the admin POST stub.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


SEVERITY_TO_CONF: dict[str, float] = {
    "low": 0.55,
    "elevated": 0.70,
    "high": 0.85,
    "critical": 0.95,
}

Severity = Literal["low", "elevated", "high", "critical"]


class IncidentStatus(str, Enum):
    OPEN = "open"
    SILENCED = "silenced"
    PROMOTED = "promoted"
    CLOSED = "closed"


class IncidentTimelineEvent(BaseModel):
    """One bullet on §II Timeline."""

    t_offset_s: float = Field(..., description="Seconds since trigger_ts")
    kind: str = Field(..., description="trigger | signal | agent | source | note")
    text: str = ""
    severity: Severity | None = None


class IncidentCreateRequest(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    kind: str = Field(..., description="firms.cluster | ucdp.delta | ais.anomaly | manual")
    severity: Severity
    coords: tuple[float, float]
    location: str = ""
    sources: list[str] = Field(default_factory=list)
    layer_hints: list[str] = Field(default_factory=list)
    initial_text: str | None = None

    @model_validator(mode="after")
    def _validate_coords(self) -> "IncidentCreateRequest":
        lat, lon = self.coords
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError(f"coords out of range: ({lat}, {lon})")
        return self


class Incident(BaseModel):
    id: str
    kind: str
    title: str
    severity: Severity
    coords: tuple[float, float]
    location: str = ""
    status: IncidentStatus = IncidentStatus.OPEN
    trigger_ts: datetime
    closed_ts: datetime | None = None
    sources: list[str] = Field(default_factory=list)
    layer_hints: list[str] = Field(default_factory=list)
    timeline: list[IncidentTimelineEvent] = Field(default_factory=list)

    @property
    def confidence(self) -> float:
        return SEVERITY_TO_CONF[self.severity]


class IncidentEnvelope(BaseModel):
    """SSE envelope — same shape as SignalEnvelope (spec §6.1)."""

    event_id: str
    ts: str
    type: str  # incident.open | incident.update | incident.close | incident.silence | incident.promote
    payload: Incident
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/backend && uv run pytest tests/test_incident_models.py -x
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/models/incident.py services/backend/tests/test_incident_models.py
git commit -m "feat(backend): incident pydantic models + severity→confidence table (S4·1)"
```

---

## Task 2 · Backend Cypher Templates

**Files:**
- Create: `services/backend/app/cypher/incident_read.py`
- Create: `services/backend/app/cypher/incident_write.py`

These are pure string constants — no behaviour to test in isolation. Tests come in Task 3 against the store. **Skip the test/impl/run cycle for this task; commit the templates only.**

- [ ] **Step 1: Write read templates**

```python
# services/backend/app/cypher/incident_read.py
"""Read Cypher templates for Incident retrieval. READ-ONLY (project rule)."""

INCIDENT_LIST_OPEN = (
    "MATCH (i:Incident) "
    "WHERE i.status IN ['open', 'promoted'] "
    "RETURN "
    "  i.id AS id, i.kind AS kind, i.title AS title, i.severity AS severity, "
    "  i.lat AS lat, i.lon AS lon, i.location AS location, i.status AS status, "
    "  toString(i.trigger_ts) AS trigger_ts, "
    "  toString(i.closed_ts) AS closed_ts, "
    "  i.sources AS sources, i.layer_hints AS layer_hints, "
    "  i.timeline_json AS timeline_json "
    "ORDER BY i.trigger_ts DESC "
    "LIMIT $limit"
)

INCIDENT_BY_ID = (
    "MATCH (i:Incident {id: $incident_id}) "
    "RETURN "
    "  i.id AS id, i.kind AS kind, i.title AS title, i.severity AS severity, "
    "  i.lat AS lat, i.lon AS lon, i.location AS location, i.status AS status, "
    "  toString(i.trigger_ts) AS trigger_ts, "
    "  toString(i.closed_ts) AS closed_ts, "
    "  i.sources AS sources, i.layer_hints AS layer_hints, "
    "  i.timeline_json AS timeline_json"
)

INCIDENT_NEXT_ORDINAL = (
    "OPTIONAL MATCH (i:Incident) "
    "RETURN coalesce(max(i.ordinal), 0) + 1 AS next_ordinal"
)
```

- [ ] **Step 2: Write write templates**

```python
# services/backend/app/cypher/incident_write.py
"""Write Cypher templates for Incident persistence. Parametrised — no LLM."""

INCIDENT_UPSERT = (
    "MERGE (i:Incident {id: $incident_id}) "
    "ON CREATE SET "
    "  i.created_at = datetime($now), "
    "  i.ordinal = $ordinal, "
    "  i.trigger_ts = datetime($trigger_ts) "
    "SET "
    "  i.kind = $kind, "
    "  i.title = $title, "
    "  i.severity = $severity, "
    "  i.lat = $lat, "
    "  i.lon = $lon, "
    "  i.location = $location, "
    "  i.status = $status, "
    "  i.closed_ts = CASE WHEN $closed_ts IS NULL THEN null ELSE datetime($closed_ts) END, "
    "  i.sources = $sources, "
    "  i.layer_hints = $layer_hints, "
    "  i.timeline_json = $timeline_json, "
    "  i.updated_at = datetime($now) "
    "RETURN "
    "  i.id AS id, i.kind AS kind, i.title AS title, i.severity AS severity, "
    "  i.lat AS lat, i.lon AS lon, i.location AS location, i.status AS status, "
    "  toString(i.trigger_ts) AS trigger_ts, "
    "  toString(i.closed_ts) AS closed_ts, "
    "  i.sources AS sources, i.layer_hints AS layer_hints, "
    "  i.timeline_json AS timeline_json"
)

INCIDENT_DELETE = "MATCH (i:Incident {id: $incident_id}) DETACH DELETE i"
```

- [ ] **Step 3: Commit**

```bash
git add services/backend/app/cypher/incident_read.py services/backend/app/cypher/incident_write.py
git commit -m "feat(backend): incident Cypher templates — read + parametrised write (S4·2)"
```

---

## Task 3 · Backend Incident Store

**Files:**
- Create: `services/backend/app/services/incident_store.py`
- Test:   `services/backend/tests/test_incident_store.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/test_incident_store.py
"""Store-level tests using a fake Neo4j driver — no live DB required."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.incident import (
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.services import incident_store


def _row(**overrides):
    base = {
        "id": "inc-001",
        "kind": "firms.cluster",
        "title": "Sinjar ridge thermal cluster",
        "severity": "high",
        "lat": 36.34,
        "lon": 41.87,
        "location": "Sinjar ridge",
        "status": "open",
        "trigger_ts": "2026-04-25T10:00:00Z",
        "closed_ts": None,
        "sources": ["firms·1"],
        "layer_hints": ["firmsHotspots"],
        "timeline_json": json.dumps([{"t_offset_s": 0.0, "kind": "trigger", "text": "t0"}]),
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_incident_assigns_id_and_persists() -> None:
    with (
        patch.object(incident_store, "read_query", new=AsyncMock(return_value=[{"next_ordinal": 7}])),
        patch.object(incident_store, "write_query", new=AsyncMock(return_value=[_row(id="inc-007")])),
    ):
        req = IncidentCreateRequest(
            title="Sinjar ridge thermal cluster",
            kind="firms.cluster",
            severity="high",
            coords=(36.34, 41.87),
            location="Sinjar ridge",
            sources=["firms·1"],
            layer_hints=["firmsHotspots"],
        )
        record = await incident_store.create_incident(req)
        assert record.id == "inc-007"
        assert record.severity == "high"
        assert record.coords == (36.34, 41.87)
        assert record.timeline[0].kind == "trigger"


@pytest.mark.asyncio
async def test_get_incident_decodes_timeline() -> None:
    with patch.object(
        incident_store,
        "read_query",
        new=AsyncMock(return_value=[_row()]),
    ):
        record = await incident_store.get_incident("inc-001")
        assert record is not None
        assert record.location == "Sinjar ridge"
        assert record.timeline == [IncidentTimelineEvent(t_offset_s=0.0, kind="trigger", text="t0")]


@pytest.mark.asyncio
async def test_close_incident_writes_status_and_closed_ts() -> None:
    captured: dict = {}

    async def fake_write(query, params):
        captured.update(params)
        return [_row(status="closed", closed_ts="2026-04-25T11:00:00Z")]

    with (
        patch.object(incident_store, "read_query", new=AsyncMock(return_value=[_row()])),
        patch.object(incident_store, "write_query", new=AsyncMock(side_effect=fake_write)),
    ):
        record = await incident_store.close_incident("inc-001", IncidentStatus.SILENCED, datetime(2026, 4, 25, 11, tzinfo=UTC))
        assert record is not None
        assert captured["status"] == "silenced"
        assert captured["closed_ts"] == "2026-04-25T11:00:00+00:00"


@pytest.mark.asyncio
async def test_append_timeline_event_grows_timeline() -> None:
    seed = _row()
    with (
        patch.object(incident_store, "read_query", new=AsyncMock(return_value=[seed])),
        patch.object(
            incident_store,
            "write_query",
            new=AsyncMock(side_effect=lambda q, p: [_row(timeline_json=p["timeline_json"])]),
        ),
    ):
        record = await incident_store.append_timeline_event(
            "inc-001",
            IncidentTimelineEvent(t_offset_s=92.0, kind="signal", text="GDELT 4 articles", severity="elevated"),
        )
        assert record is not None
        assert len(record.timeline) == 2
        assert record.timeline[-1].text == "GDELT 4 articles"
```

Run: `cd services/backend && uv run pytest tests/test_incident_store.py -x`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 2: Implement `incident_store`**

```python
# services/backend/app/services/incident_store.py
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
        except Exception:
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
```

- [ ] **Step 3: Run tests to verify**

```bash
cd services/backend && uv run pytest tests/test_incident_store.py -x
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add services/backend/app/services/incident_store.py services/backend/tests/test_incident_store.py
git commit -m "feat(backend): incident_store — Neo4j-backed CRUD via deterministic Cypher (S4·3)"
```

---

## Task 4 · Backend Incident Stream (in-memory ring + SSE fan-out)

**Files:**
- Create: `services/backend/app/services/incident_stream.py`
- Test:   `services/backend/tests/test_incident_stream.py`

The shape mirrors `signal_stream.py` so the SSE replay/dedupe contract (spec §6.1) is identical.

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/test_incident_stream.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.models.incident import Incident, IncidentStatus
from app.services.incident_stream import IncidentStream


def _incident(ordinal: int) -> Incident:
    return Incident(
        id=f"inc-{ordinal:03d}",
        kind="firms.cluster",
        title=f"x{ordinal}",
        severity="elevated",
        coords=(0.0, 0.0),
        location="-",
        status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
        sources=[],
        timeline=[],
    )


def test_publish_returns_distinct_envelopes_for_repeat_publishes() -> None:
    """Each publish() call MUST return a distinct envelope so successive
    incident.update events on the same incident reach subscribers — the
    SSE replay window is the only dedupe layer (event_id is monotonic).
    """
    stream = IncidentStream(window_seconds=60, max_size=10)
    inc = _incident(1)
    a = stream.publish("incident.open", inc)
    b = stream.publish("incident.update", inc)
    c = stream.publish("incident.update", inc)
    assert a is not None and b is not None and c is not None
    assert {a.event_id, b.event_id, c.event_id} == {a.event_id, b.event_id, c.event_id}
    assert len({a.event_id, b.event_id, c.event_id}) == 3
    assert len(stream.get_latest(10)) == 3


def test_get_replay_returns_events_after_marker() -> None:
    stream = IncidentStream(window_seconds=60, max_size=10)
    e1 = stream.publish("incident.open", _incident(1))
    e2 = stream.publish("incident.update", _incident(2))
    assert e1 is not None and e2 is not None
    mode, replay = stream.get_replay(e1.event_id)
    assert mode == "ok"
    assert [e.event_id for e in replay] == [e2.event_id]


def test_get_replay_resets_when_marker_too_old() -> None:
    stream = IncidentStream(window_seconds=60, max_size=2)
    stream.publish("incident.open", _incident(1))
    stream.publish("incident.open", _incident(2))
    stream.publish("incident.open", _incident(3))  # evicts incident-001
    mode, _ = stream.get_replay("0000000000000-000000")
    assert mode == "reset"


@pytest.mark.asyncio
async def test_subscribe_receives_live_events() -> None:
    stream = IncidentStream(window_seconds=60, max_size=10)
    queue = stream.subscribe()
    try:
        env = stream.publish("incident.open", _incident(1))
        received = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert env is not None and received.event_id == env.event_id
    finally:
        stream.unsubscribe(queue)
```

Run: `cd services/backend && uv run pytest tests/test_incident_stream.py -x` — FAIL.

- [ ] **Step 2: Implement `incident_stream`**

```python
# services/backend/app/services/incident_stream.py
"""In-memory ring buffer + live fan-out for /api/incidents/stream.

Mirrors signal_stream.py shape (ring + replay + reset). Dedup is intentionally
absent on the publish side — the `event_id` is monotonic (`<ms>-<seq>`) and
unique by construction, and the SSE generator already gates on `event_id`
ordering during replay. Re-publishing the same logical state (e.g. two
`incident.update` for the same id) MUST reach subscribers; collapsing them
would freeze the live timeline. Idempotency for the admin trigger is the
caller's concern, not the stream's.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import UTC, datetime
from typing import Literal

import structlog

from app.models.incident import Incident, IncidentEnvelope

log = structlog.get_logger(__name__)

ReplayMode = Literal["ok", "reset"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _build_event_id(ms: int, seq: int) -> str:
    return f"{ms:013d}-{seq:06d}"


def _ms_to_iso_utc(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{ms % 1000:03d}"
    return f"{base}.{millis}Z"


class IncidentStream:
    def __init__(self, window_seconds: int = 900, max_size: int = 200) -> None:
        self._window_seconds = window_seconds
        self._max_size = max_size
        self._buffer: deque[IncidentEnvelope] = deque(maxlen=max_size)
        self._seq = 0
        self._live: list[asyncio.Queue[IncidentEnvelope]] = []

    def clear(self) -> None:
        self._buffer.clear()
        self._seq = 0

    def publish(self, type_: str, incident: Incident) -> IncidentEnvelope:
        """Append an envelope and fan out to live subscribers.

        Always returns the envelope — there is no publish-side dedup; the
        `event_id` is monotonic by construction and the SSE replay window
        is the dedup boundary on the wire.
        """
        self._prune()
        ms = _now_ms()
        self._seq = (self._seq + 1) % 1_000_000
        env = IncidentEnvelope(
            event_id=_build_event_id(ms, self._seq),
            ts=_ms_to_iso_utc(ms),
            type=type_,
            payload=incident,
        )
        self._buffer.append(env)
        for queue in list(self._live):
            try:
                queue.put_nowait(env)
            except asyncio.QueueFull:
                log.warning("incident_stream_queue_full")
        return env

    def get_latest(self, limit: int) -> list[IncidentEnvelope]:
        self._prune()
        if limit <= 0:
            return []
        items = list(self._buffer)[-limit:]
        items.reverse()
        return items

    def get_replay(
        self, last_event_id: str | None
    ) -> tuple[ReplayMode, list[IncidentEnvelope]]:
        self._prune()
        if not last_event_id:
            return "ok", []
        if not self._buffer:
            return "ok", []
        oldest = self._buffer[0]
        if last_event_id < oldest.event_id:
            return "reset", []
        return "ok", [e for e in self._buffer if e.event_id > last_event_id]

    def subscribe(self) -> asyncio.Queue[IncidentEnvelope]:
        q: asyncio.Queue[IncidentEnvelope] = asyncio.Queue(maxsize=200)
        self._live.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[IncidentEnvelope]) -> None:
        try:
            self._live.remove(queue)
        except ValueError:
            pass

    def _prune(self) -> None:
        if not self._buffer:
            return
        cutoff_ms = int((datetime.now(UTC).timestamp() - self._window_seconds) * 1000)
        while self._buffer:
            oldest = self._buffer[0]
            ms_part, _, _ = oldest.event_id.partition("-")
            try:
                oldest_ms = int(ms_part)
            except ValueError:
                self._buffer.popleft()
                continue
            if oldest_ms < cutoff_ms:
                self._buffer.popleft()
            else:
                break


_singleton: IncidentStream | None = None


def get_incident_stream() -> IncidentStream:
    global _singleton
    if _singleton is None:
        _singleton = IncidentStream()
    return _singleton
```

- [ ] **Step 3: Run + commit**

```bash
cd services/backend && uv run pytest tests/test_incident_stream.py -x
git add services/backend/app/services/incident_stream.py services/backend/tests/test_incident_stream.py
git commit -m "feat(backend): incident_stream — in-mem ring + SSE fan-out (S4·4)"
```

Expected: 4 passed.

---

## Task 5 · Backend Incidents Router

**Files:**
- Create: `services/backend/app/routers/incidents.py`
- Modify: `services/backend/app/main.py` (one import + one mount)
- Test:   `services/backend/tests/test_incidents_router.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/test_incidents_router.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.incident import (
    Incident,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.services.incident_stream import get_incident_stream


def _make_incident(incident_id: str = "inc-001") -> Incident:
    return Incident(
        id=incident_id,
        kind="firms.cluster",
        title="x",
        severity="elevated",
        coords=(36.34, 41.87),
        location="Sinjar",
        status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
        sources=["firms·1"],
        layer_hints=["firmsHotspots"],
        timeline=[IncidentTimelineEvent(t_offset_s=0.0, kind="trigger", text="t0")],
    )


def test_list_incidents_returns_records() -> None:
    with patch("app.routers.incidents.incident_store.list_open_incidents",
               new=AsyncMock(return_value=[_make_incident()])):
        with TestClient(app) as client:
            resp = client.get("/api/incidents")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["id"] == "inc-001"
            assert data[0]["coords"] == [36.34, 41.87]


def test_get_incident_404_when_missing() -> None:
    with patch("app.routers.incidents.incident_store.get_incident",
               new=AsyncMock(return_value=None)):
        with TestClient(app) as client:
            resp = client.get("/api/incidents/inc-999")
            assert resp.status_code == 404


def test_admin_create_publishes_to_stream() -> None:
    stream = get_incident_stream()
    stream.clear()
    queue = stream.subscribe()
    try:
        with patch("app.routers.incidents.incident_store.create_incident",
                   new=AsyncMock(return_value=_make_incident("inc-007"))):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/incidents/_admin/trigger",
                    json={
                        "title": "x",
                        "kind": "firms.cluster",
                        "severity": "elevated",
                        "coords": [36.34, 41.87],
                        "location": "Sinjar",
                    },
                )
                assert resp.status_code == 201
                assert resp.json()["id"] == "inc-007"
                env = queue.get_nowait()
                assert env.type == "incident.open"
                assert env.payload.id == "inc-007"
    finally:
        stream.unsubscribe(queue)


def test_silence_publishes_close_event() -> None:
    stream = get_incident_stream()
    stream.clear()
    queue = stream.subscribe()
    try:
        closed = _make_incident().model_copy(
            update={"status": IncidentStatus.SILENCED, "closed_ts": datetime.now(UTC)}
        )
        with patch("app.routers.incidents.incident_store.close_incident",
                   new=AsyncMock(return_value=closed)):
            with TestClient(app) as client:
                resp = client.post("/api/incidents/inc-001/silence")
                assert resp.status_code == 200
                env = queue.get_nowait()
                assert env.type == "incident.silence"
    finally:
        stream.unsubscribe(queue)


def test_stream_route_is_not_swallowed_by_dynamic_id() -> None:
    """Regression: GET /api/incidents/stream must hit the SSE handler, NOT
    the GET /{incident_id} handler. FastAPI matches routes in declaration
    order, so /stream MUST be declared before /{incident_id}.
    """
    with TestClient(app) as client:
        # Stream the response to avoid blocking on the open SSE connection;
        # we only care that the response status + content-type are SSE,
        # not 404/503 from the dynamic-id handler.
        with client.stream("GET", "/api/incidents/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
```

Run: `cd services/backend && uv run pytest tests/test_incidents_router.py -x` — FAIL (router not mounted).

- [ ] **Step 2: Write the router**

```python
# services/backend/app/routers/incidents.py
"""REST + SSE + admin trigger for /api/incidents.

The admin trigger is a deliberate stub for v1 — real pattern detection is
deferred to services/incident-detector (spec §8). All operations publish
an envelope to IncidentStream so connected War Rooms react in real time.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse

from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentStatus,
)
from app.services import incident_store
from app.services.incident_stream import IncidentEnvelope, get_incident_stream

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])

_HEARTBEAT_SECONDS = 15.0


@router.get("", response_model=list[Incident])
async def list_incidents(limit: int = Query(default=50, ge=1, le=200)) -> list[Incident]:
    try:
        return await incident_store.list_open_incidents(limit=limit)
    except Exception as exc:
        log.warning("incidents_list_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="incidents backend unavailable") from exc


# IMPORTANT: `/stream` MUST be declared BEFORE `/{incident_id}` — FastAPI
# matches routes in declaration order, so a dynamic-id route declared first
# will swallow the literal `/stream`. Same rule for `/_admin/trigger`.
@router.get("/stream")
async def stream_incidents(
    request: Request,
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
) -> EventSourceResponse:
    last_event_id = last_event_id_header or last_event_id_query
    return EventSourceResponse(_sse_generator(request, last_event_id))


@router.post(
    "/_admin/trigger",
    response_model=Incident,
    status_code=status.HTTP_201_CREATED,
)
async def admin_trigger(payload: IncidentCreateRequest) -> Incident:
    """Admin-only stub for incident creation. Detection service deferred (spec §8)."""
    try:
        record = await incident_store.create_incident(payload)
    except Exception as exc:
        log.warning("incident_create_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="incident create failed") from exc
    get_incident_stream().publish("incident.open", record)
    return record


@router.get("/{incident_id}", response_model=Incident)
async def get_incident(incident_id: str) -> Incident:
    try:
        record = await incident_store.get_incident(incident_id)
    except Exception as exc:
        log.warning("incident_get_failed", incident_id=incident_id, error=str(exc))
        raise HTTPException(status_code=503, detail="incidents backend unavailable") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return record


@router.post("/{incident_id}/silence", response_model=Incident)
async def silence(incident_id: str) -> Incident:
    record = await incident_store.close_incident(incident_id, IncidentStatus.SILENCED)
    if record is None:
        raise HTTPException(status_code=404, detail="incident not found")
    get_incident_stream().publish("incident.silence", record)
    return record


@router.post("/{incident_id}/promote", response_model=Incident)
async def promote(incident_id: str) -> Incident:
    record = await incident_store.close_incident(incident_id, IncidentStatus.PROMOTED)
    if record is None:
        raise HTTPException(status_code=404, detail="incident not found")
    get_incident_stream().publish("incident.promote", record)
    return record


async def _sse_generator(
    request: Request | None,
    last_event_id: str | None,
) -> AsyncGenerator[dict[str, str], None]:
    stream = get_incident_stream()
    queue = stream.subscribe()
    try:
        mode, replay = stream.get_replay(last_event_id)
        if mode == "reset":
            yield {"event": "reset", "data": json.dumps({"reason": "stale-last-event-id"})}
        else:
            yield {"comment": "ready"}
        replay_ids: set[str] = set()
        for env in replay:
            yield _frame(env)
            yield _frame_wildcard(env)
            replay_ids.add(env.event_id)
        last_delivered = replay[-1].event_id if replay else last_event_id
        while True:
            if request is not None and await request.is_disconnected():
                break
            try:
                env = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                if env.event_id in replay_ids:
                    continue
                if last_delivered is not None and env.event_id <= last_delivered:
                    continue
                yield _frame(env)
                yield _frame_wildcard(env)
                last_delivered = env.event_id
            except TimeoutError:
                yield {"comment": "heartbeat"}
    finally:
        stream.unsubscribe(queue)


def _frame(env: IncidentEnvelope) -> dict[str, str]:
    return {"id": env.event_id, "event": env.type, "data": env.model_dump_json()}


def _frame_wildcard(env: IncidentEnvelope) -> dict[str, str]:
    return {"id": env.event_id, "data": env.model_dump_json()}
```

- [ ] **Step 3: Mount the router in `main.py`**

In `services/backend/app/main.py`, add `incidents` to the import block and mount it under `/api` (no `/api/v1` alias — incidents are new):

```python
from app.routers import (
    aircraft, cables, earthquakes, eonet, firms, flights, gdacs, graph,
    hotspots, incidents, intel, landing, reports, rag, satellites, signals, vessels,
)
```

And below the existing `landing` mount (line ~115):

```python
app.include_router(incidents.router, prefix="/api")
```

- [ ] **Step 4: Run + commit**

```bash
cd services/backend && uv run pytest tests/test_incidents_router.py -x
git add services/backend/app/routers/incidents.py services/backend/app/main.py services/backend/tests/test_incidents_router.py
git commit -m "feat(backend): /api/incidents — CRUD + SSE stream + admin trigger (S4·5)"
```

Expected: 5 passed (list, get-404, admin-trigger, silence, stream-route-order).

---

## Task 6 · Frontend Types + API Client

**Files:**
- Modify: `services/frontend/package.json` (add `test` script)
- Create: `services/frontend/src/types/incident.ts`
- Modify: `services/frontend/src/services/api.ts`

- [ ] **Step 0: Add the missing `test` script**

`services/frontend/package.json` currently has no `test` script — every `npm test` line in subsequent tasks would otherwise fail. Add the script so `npm test -- <pattern>` works (Vitest accepts positional pattern args after `--`).

In `services/frontend/package.json`, add a `"test"` entry to `scripts`:

```jsonc
"scripts": {
  "dev": "vite",
  "build": "tsc -b && vite build",
  "preview": "vite preview",
  "lint": "eslint src/",
  "type-check": "tsc --noEmit",
  "test": "vitest run"
}
```

Smoke-check:

```bash
cd services/frontend && npm test -- --reporter=basic
```
Expected: existing suite runs and passes (no new tests yet).

- [ ] **Step 1: Create the type module**

```typescript
// services/frontend/src/types/incident.ts
export type IncidentSeverity = "low" | "elevated" | "high" | "critical";
export type IncidentStatus = "open" | "silenced" | "promoted" | "closed";

export interface IncidentTimelineEvent {
  t_offset_s: number;
  kind: "trigger" | "signal" | "agent" | "source" | "note" | string;
  text: string;
  severity?: IncidentSeverity | null;
}

export interface Incident {
  id: string;
  kind: string;
  title: string;
  severity: IncidentSeverity;
  coords: [number, number]; // [lat, lon]
  location: string;
  status: IncidentStatus;
  trigger_ts: string;
  closed_ts: string | null;
  sources: string[];
  layer_hints: string[];
  timeline: IncidentTimelineEvent[];
}

export type IncidentEnvelopeType =
  | "incident.open"
  | "incident.update"
  | "incident.silence"
  | "incident.promote"
  | "incident.close";

export interface IncidentEnvelope {
  event_id: string;
  ts: string;
  type: IncidentEnvelopeType;
  payload: Incident;
}

export interface IncidentCreateRequest {
  title: string;
  kind: string;
  severity: IncidentSeverity;
  coords: [number, number];
  location?: string;
  sources?: string[];
  layer_hints?: string[];
  initial_text?: string;
}
```

- [ ] **Step 2: Extend `services/api.ts`**

`services/api.ts` already declares a module-private `BASE = "/api"` (services/frontend/src/services/api.ts:30). We append to the same file so `BASE` is in scope; do **not** introduce a new `API_BASE` constant.

At the **top** of `services/frontend/src/services/api.ts`, add the new type import to the existing `import type { ... } from "../types"` block as a separate line (the incident types live in their own module):

```typescript
import type { Incident, IncidentCreateRequest } from "../types/incident";
```

Then at the **bottom** of `services/frontend/src/services/api.ts`, append (do not remove anything existing):

```typescript
export const INCIDENT_STREAM_URL = `${BASE}/incidents/stream`;

export async function getIncidents(limit = 50): Promise<Incident[]> {
  const resp = await fetch(`${BASE}/incidents?limit=${limit}`);
  if (!resp.ok) throw new Error(`incidents: ${resp.status}`);
  return (await resp.json()) as Incident[];
}

export async function getIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}`);
  if (!resp.ok) throw new Error(`incident ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function triggerIncident(payload: IncidentCreateRequest): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/_admin/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(`trigger incident: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function silenceIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}/silence`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`silence ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function promoteIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}/promote`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`promote ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/package.json \
        services/frontend/src/types/incident.ts \
        services/frontend/src/services/api.ts
git commit -m "feat(frontend): incident types + api client helpers + npm test script (S4·6)"
```

---

## Task 7 · `IncidentProvider` + `useIncidents` Context

**Files:**
- Create: `services/frontend/src/state/IncidentProvider.tsx`
- Create: `services/frontend/src/hooks/useIncidents.ts`
- Test:   `services/frontend/src/hooks/__tests__/useIncidents.test.tsx`

**Why a provider + thin hook split:** AppShell mounts `<IncidentToast>` and the WarRoomPage both want to read the active incident. If `useIncidents` opened its own EventSource each time, we'd hold two duplicate SSE connections and two divergent `active`/`history` states. The provider opens *one* SSE for the whole tree; both consumers read the same React context.

The contract follows `useSignalFeed`: hydrate REST → connect SSE → reconnect with backoff → dedupe via `event_id` → handle named `reset` events by re-hydrating.

- [ ] **Step 1: Write the failing test**

```typescript
// services/frontend/src/hooks/__tests__/useIncidents.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, renderHook, act, waitFor, screen } from "@testing-library/react";

import { useIncidents } from "../useIncidents";
import { IncidentProvider } from "../../state/IncidentProvider";
import type { Incident, IncidentEnvelope } from "../../types/incident";
import * as api from "../../services/api";

class FakeES {
  static instances: FakeES[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  listeners: Record<string, Array<(ev: MessageEvent) => void>> = {};
  constructor(url: string) {
    this.url = url;
    FakeES.instances.push(this);
  }
  addEventListener(type: string, cb: (ev: MessageEvent) => void): void {
    (this.listeners[type] ??= []).push(cb);
  }
  removeEventListener(): void {}
  close(): void {}
  emit(type: string, data: object, eventId = "1"): void {
    const ev = { data: JSON.stringify(data), lastEventId: eventId } as MessageEvent;
    if (type === "message" && this.onmessage) this.onmessage(ev);
    for (const cb of this.listeners[type] ?? []) cb(ev);
  }
}

const incidentFixture: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "Sinjar ridge thermal cluster",
  severity: "high",
  coords: [36.34, 41.87],
  location: "Sinjar ridge",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: ["firms·1"],
  layer_hints: ["firmsHotspots"],
  timeline: [{ t_offset_s: 0.0, kind: "trigger", text: "t0" }],
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <IncidentProvider>{children}</IncidentProvider>
);

beforeEach(() => {
  FakeES.instances = [];
  (globalThis as unknown as { EventSource: typeof FakeES }).EventSource = FakeES;
  vi.spyOn(api, "getIncidents").mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("IncidentProvider + useIncidents", () => {
  it("opens exactly one SSE connection regardless of consumer count", async () => {
    function Probe() {
      useIncidents();
      return null;
    }
    render(
      <IncidentProvider>
        <Probe />
        <Probe />
        <Probe />
      </IncidentProvider>,
    );
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
  });

  it("hydrates from REST then transitions to live on SSE open", async () => {
    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));
    await waitFor(() => expect(result.current.status).toBe("live"));
  });

  it("places incident.open into active + history", async () => {
    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));

    const env: IncidentEnvelope = {
      event_id: "0001712841723482-000001",
      ts: "2026-04-25T10:00:00.000Z",
      type: "incident.open",
      payload: incidentFixture,
    };
    act(() => FakeES.instances[0]!.emit("incident.open", env, env.event_id));
    await waitFor(() => expect(result.current.active?.id).toBe("inc-001"));
    expect(result.current.history.map((i) => i.id)).toEqual(["inc-001"]);
  });

  it("removes incident from active on incident.silence", async () => {
    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));

    const open: IncidentEnvelope = {
      event_id: "0001712841723482-000001",
      ts: "2026-04-25T10:00:00.000Z",
      type: "incident.open",
      payload: incidentFixture,
    };
    act(() => FakeES.instances[0]!.emit("incident.open", open, open.event_id));
    await waitFor(() => expect(result.current.active?.id).toBe("inc-001"));

    const silence: IncidentEnvelope = {
      event_id: "0001712841723482-000002",
      ts: "2026-04-25T10:01:00.000Z",
      type: "incident.silence",
      payload: { ...incidentFixture, status: "silenced" },
    };
    act(() => FakeES.instances[0]!.emit("incident.silence", silence, silence.event_id));
    await waitFor(() => expect(result.current.active).toBeNull());
  });

  it("re-hydrates from REST when a reset event arrives", async () => {
    const fresh: Incident = { ...incidentFixture, id: "inc-099" };
    const getSpy = vi.spyOn(api, "getIncidents").mockResolvedValue([fresh]);

    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));

    // reset clears local state and re-fetches.
    act(() => FakeES.instances[0]!.emit("reset", { reason: "stale-last-event-id" }, "0"));
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.active?.id).toBe("inc-099"));
  });

  it("falls back to a no-op result when consumed outside the provider", () => {
    const { result } = renderHook(() => useIncidents());
    expect(result.current.status).toBe("idle");
    expect(result.current.active).toBeNull();
  });
});
```

Run: `cd services/frontend && npm test -- useIncidents` — FAIL.

- [ ] **Step 2: Implement the provider + thin hook**

```typescript
// services/frontend/src/state/IncidentProvider.tsx
/**
 * IncidentProvider — single SSE subscription for /api/incidents/stream.
 *
 * Mirrors useSignalFeed semantics (hydrate REST → connect SSE → reconnect
 * with backoff → dedupe via event_id → handle named `reset` events). All
 * consumers read from one shared context so multiple widgets (toast,
 * pulsing tab dot, WarRoomPage) don't open duplicate connections.
 */
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  INCIDENT_STREAM_URL,
  getIncidents,
} from "../services/api";
import type {
  Incident,
  IncidentEnvelope,
  IncidentEnvelopeType,
} from "../types/incident";

export type IncidentsStatus = "idle" | "live" | "reconnecting" | "down";

export interface IncidentContextValue {
  status: IncidentsStatus;
  active: Incident | null;
  history: Incident[];
  latestEnvelope: IncidentEnvelope | null;
}

const HISTORY_CAP = 10;
const DEDUPE_CAP = 200;
const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];
const STREAM_TYPES: IncidentEnvelopeType[] = [
  "incident.open",
  "incident.update",
  "incident.silence",
  "incident.promote",
  "incident.close",
];

const DEFAULT_VALUE: IncidentContextValue = {
  status: "idle",
  active: null,
  history: [],
  latestEnvelope: null,
};

export const IncidentContext = createContext<IncidentContextValue>(DEFAULT_VALUE);

function buildUrl(lastId: string | null): string {
  if (!lastId) return INCIDENT_STREAM_URL;
  const sep = INCIDENT_STREAM_URL.includes("?") ? "&" : "?";
  return `${INCIDENT_STREAM_URL}${sep}last_event_id=${encodeURIComponent(lastId)}`;
}

export function IncidentProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<IncidentsStatus>("idle");
  const [active, setActive] = useState<Incident | null>(null);
  const [history, setHistory] = useState<Incident[]>([]);
  const [latestEnvelope, setLatestEnvelope] = useState<IncidentEnvelope | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const seenOrderRef = useRef<string[]>([]);
  const lastIdRef = useRef<string | null>(null);
  const attemptRef = useRef(0);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    attemptRef.current = 0;
    setStatus("idle");

    function remember(id: string): boolean {
      if (seenRef.current.has(id)) return false;
      seenRef.current.add(id);
      seenOrderRef.current.push(id);
      if (seenOrderRef.current.length > DEDUPE_CAP) {
        const oldest = seenOrderRef.current.shift();
        if (oldest !== undefined) seenRef.current.delete(oldest);
      }
      return true;
    }

    function applyEnvelope(env: IncidentEnvelope) {
      const incident = env.payload;
      if (env.type === "incident.open" || env.type === "incident.update") {
        setActive(incident);
      } else {
        setActive((prev) => (prev?.id === incident.id ? null : prev));
      }
      setHistory((prev) => {
        const filtered = prev.filter((i) => i.id !== incident.id);
        return [incident, ...filtered].slice(0, HISTORY_CAP);
      });
      setLatestEnvelope(env);
    }

    function handleData(raw: string, fallbackId: string) {
      let env: IncidentEnvelope;
      try {
        env = JSON.parse(raw) as IncidentEnvelope;
      } catch {
        return;
      }
      const id = env.event_id || fallbackId;
      if (!id || !remember(id)) return;
      lastIdRef.current =
        lastIdRef.current && id <= lastIdRef.current ? lastIdRef.current : id;
      applyEnvelope(env);
    }

    async function rehydrate(reason: string) {
      seenRef.current = new Set();
      seenOrderRef.current = [];
      lastIdRef.current = null;
      try {
        const fresh = await getIncidents();
        if (cancelled) return;
        const open = fresh.find((i) => i.status === "open") ?? null;
        setActive(open);
        setHistory(fresh.slice(0, HISTORY_CAP));
        setLatestEnvelope(null);
      } catch {
        // Soft-fail: keep prior local state on refetch error.
        // Reason is captured for log telemetry only — never alert the user.
        void reason;
      }
    }

    async function hydrate() {
      try {
        const open = await getIncidents();
        if (cancelled) return;
        const newest = open[0] ?? null;
        if (newest && newest.status === "open") setActive(newest);
        setHistory(open.slice(0, HISTORY_CAP));
      } catch {
        // soft-fail: stream will populate
      }
      if (!cancelled) connect();
    }

    function connect() {
      if (cancelled) return;
      const Ctor =
        (globalThis as unknown as { EventSource?: new (u: string) => EventSource })
          .EventSource;
      if (!Ctor) {
        setStatus("down");
        return;
      }
      const es = new Ctor(buildUrl(lastIdRef.current));
      esRef.current = es;

      es.onopen = () => {
        if (cancelled) return;
        attemptRef.current = 0;
        setStatus("live");
      };
      es.onmessage = (ev) => {
        if (cancelled) return;
        handleData(ev.data, ev.lastEventId ?? "");
      };
      for (const type of STREAM_TYPES) {
        es.addEventListener(type, ((ev: Event) => {
          if (cancelled) return;
          const msg = ev as MessageEvent<string>;
          handleData(msg.data, (msg.lastEventId ?? "") as string);
        }) as EventListener);
      }
      // Spec §6.1: a `reset` event means our Last-Event-ID fell off the
      // server ring. Drop local dedupe + last-id state and re-fetch.
      es.addEventListener("reset", (() => {
        if (cancelled) return;
        void rehydrate("server-reset");
      }) as EventListener);
      es.onerror = () => {
        if (cancelled) return;
        try { es.close(); } catch { /* ignore */ }
        if (esRef.current === es) esRef.current = null;
        setStatus("reconnecting");
        if (reconnectRef.current !== null) {
          clearTimeout(reconnectRef.current);
          reconnectRef.current = null;
        }
        const delay = BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)];
        attemptRef.current += 1;
        reconnectRef.current = setTimeout(() => {
          reconnectRef.current = null;
          if (!cancelled) connect();
        }, delay);
      };
    }

    void hydrate();

    return () => {
      cancelled = true;
      if (reconnectRef.current !== null) {
        clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
      if (esRef.current !== null) {
        try { esRef.current.close(); } catch { /* ignore */ }
        esRef.current = null;
      }
    };
  }, []);

  return (
    <IncidentContext.Provider
      value={{ status, active, history, latestEnvelope }}
    >
      {children}
    </IncidentContext.Provider>
  );
}
```

```typescript
// services/frontend/src/hooks/useIncidents.ts
/**
 * useIncidents — context consumer for IncidentProvider.
 *
 * Returns the shared incident state. When mounted outside an
 * IncidentProvider, returns the inert default value (no SSE work) so
 * tests and isolated component renders behave deterministically.
 */
import { useContext } from "react";
import {
  IncidentContext,
  type IncidentContextValue,
} from "../state/IncidentProvider";

export type { IncidentsStatus } from "../state/IncidentProvider";

export function useIncidents(): IncidentContextValue {
  return useContext(IncidentContext);
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- useIncidents
git add services/frontend/src/state/IncidentProvider.tsx \
        services/frontend/src/hooks/useIncidents.ts \
        services/frontend/src/hooks/__tests__/useIncidents.test.tsx
git commit -m "feat(frontend): IncidentProvider + thin useIncidents — single SSE for whole tree (S4·7)"
```

Expected: 6 passed.

---

## Task 8 · `useTPlus` Hook (T+ Clock)

**Files:**
- Create: `services/frontend/src/hooks/useTPlus.ts`
- Test:   `services/frontend/src/hooks/__tests__/useTPlus.test.ts`

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/hooks/__tests__/useTPlus.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { formatTPlus, useTPlus } from "../useTPlus";

describe("formatTPlus", () => {
  it("renders T+hh:mm:ss for sub-day deltas", () => {
    expect(formatTPlus(0)).toBe("T+00:00:00");
    expect(formatTPlus(2 * 3600 + 14 * 60 + 8)).toBe("T+02:14:08");
  });

  it("renders Td.hh:mm for ≥24h deltas", () => {
    expect(formatTPlus(26 * 3600 + 5 * 60)).toBe("T+1d.02:05");
  });

  it("clamps negatives to T+00:00:00", () => {
    expect(formatTPlus(-10)).toBe("T+00:00:00");
  });
});

describe("useTPlus", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("ticks every second", () => {
    const start = new Date("2026-04-25T10:00:00Z");
    vi.setSystemTime(start);
    const { result } = renderHook(() => useTPlus(start.toISOString()));
    expect(result.current).toBe("T+00:00:00");
    act(() => { vi.advanceTimersByTime(2000); });
    expect(result.current).toBe("T+00:00:02");
  });
});
```

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/hooks/useTPlus.ts
import { useEffect, useState } from "react";

export function formatTPlus(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const days = Math.floor(safe / 86_400);
  const rem = safe - days * 86_400;
  const hh = Math.floor(rem / 3600);
  const mm = Math.floor((rem - hh * 3600) / 60);
  const ss = rem - hh * 3600 - mm * 60;
  const pad = (n: number) => (n < 10 ? `0${n}` : String(n));
  if (days > 0) return `T+${days}d.${pad(hh)}:${pad(mm)}`;
  return `T+${pad(hh)}:${pad(mm)}:${pad(ss)}`;
}

export function useTPlus(triggerIso: string | null): string {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  if (!triggerIso) return formatTPlus(0);
  const triggerMs = Date.parse(triggerIso);
  if (Number.isNaN(triggerMs)) return formatTPlus(0);
  return formatTPlus((now - triggerMs) / 1000);
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- useTPlus
git add services/frontend/src/hooks/useTPlus.ts services/frontend/src/hooks/__tests__/useTPlus.test.ts
git commit -m "feat(frontend): useTPlus — incident-relative T+ clock (S4·8)"
```

Expected: 4 passed.

---

## Task 9 · `IncidentBar` Primitive

**Files:**
- Create: `services/frontend/src/components/hlidskjalf/IncidentBar.tsx`
- Test:   `services/frontend/src/components/hlidskjalf/IncidentBar.test.tsx`

Spec §4.4.1 — sentinel-tinted gradient bar, only visible when an incident is active.

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/components/hlidskjalf/IncidentBar.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Incident } from "../../types/incident";
import { IncidentBar } from "./IncidentBar";

const baseIncident: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "Kurdistan · Thermal Escalation",
  severity: "high",
  coords: [36.34, 41.87],
  location: "Sinjar ridge",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: ["firms·1"],
  layer_hints: ["firmsHotspots"],
  timeline: [],
};

describe("IncidentBar", () => {
  it("renders title + LIVE tag + coords", () => {
    render(<IncidentBar incident={baseIncident} />);
    expect(screen.getByText(/INCIDENT · LIVE/i)).toBeInTheDocument();
    expect(screen.getByText(/Kurdistan/)).toBeInTheDocument();
    expect(screen.getByText(/36\.340N · 41\.870E/)).toBeInTheDocument();
  });

  it("renders T+ clock with sentinel tone", () => {
    render(<IncidentBar incident={baseIncident} />);
    const clock = screen.getByTestId("incident-tplus");
    expect(clock.textContent).toMatch(/^T\+/);
  });
});
```

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/components/hlidskjalf/IncidentBar.tsx
/**
 * IncidentBar — spec §4.4.1.
 *
 * Visible only when an incident is active. Sentinel-tinted gradient
 * background, LIVE tag, title (Instrument Serif italic), coords (Mono Stone),
 * T+ clock (Mono Sentinel) — visually loud enough to never be confused with
 * the dim Ash UTC clock in the TopBar.
 */
import type { CSSProperties } from "react";

import type { Incident } from "../../types/incident";
import { useTPlus } from "../../hooks/useTPlus";

export interface IncidentBarProps {
  incident: Incident;
  style?: CSSProperties;
}

const barStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "1.5rem",
  height: "44px",
  padding: "0 1.25rem",
  borderBottom: "1px solid var(--granite)",
  background:
    "linear-gradient(90deg, rgba(184,90,42,0.16) 0%, rgba(184,90,42,0.04) 60%, rgba(11,10,8,0) 100%)",
};

const tagStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "9px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--sentinel)",
  border: "1px solid var(--sentinel)",
  padding: "2px 6px",
};

const titleStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", "Times New Roman", serif',
  fontStyle: "italic",
  fontSize: "16px",
  color: "var(--parchment)",
  margin: 0,
};

const metaStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "10px",
  letterSpacing: "0.04em",
  color: "var(--stone)",
};

const clockStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, monospace',
  fontSize: "13px",
  letterSpacing: "0.06em",
  color: "var(--sentinel)",
  marginLeft: "auto",
};

function fmtCoord(value: number, axis: "lat" | "lon"): string {
  const hemi = axis === "lat" ? (value >= 0 ? "N" : "S") : value >= 0 ? "E" : "W";
  return `${Math.abs(value).toFixed(3)}${hemi}`;
}

export function IncidentBar({ incident, style }: IncidentBarProps) {
  const tplus = useTPlus(incident.trigger_ts);
  return (
    <header
      role="status"
      aria-label="Active incident"
      data-part="incident-bar"
      data-severity={incident.severity}
      style={{ ...barStyle, ...style }}
    >
      <span style={tagStyle}>INCIDENT · LIVE</span>
      <h1 style={titleStyle}>{incident.title}</h1>
      <span style={metaStyle}>
        {fmtCoord(incident.coords[0], "lat")} · {fmtCoord(incident.coords[1], "lon")}
        {"  "}· conf {(severityToConf(incident.severity)).toFixed(2)}
      </span>
      <span data-testid="incident-tplus" style={clockStyle}>
        {tplus}
      </span>
    </header>
  );
}

function severityToConf(s: Incident["severity"]): number {
  switch (s) {
    case "low": return 0.55;
    case "elevated": return 0.70;
    case "high": return 0.85;
    case "critical": return 0.95;
  }
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- IncidentBar
git add services/frontend/src/components/hlidskjalf/IncidentBar.tsx services/frontend/src/components/hlidskjalf/IncidentBar.test.tsx
git commit -m "feat(frontend): IncidentBar primitive — sentinel gradient + T+ clock (S4·9)"
```

Expected: 2 passed.

---

## Task 10 · `IncidentToast` + AppShell Wiring + TopBar Pulse

**Files:**
- Create: `services/frontend/src/components/hlidskjalf/IncidentToast.tsx`
- Test:   `services/frontend/src/components/hlidskjalf/IncidentToast.test.tsx`
- Modify: `services/frontend/src/app/AppShell.tsx`
- Modify: `services/frontend/src/components/hlidskjalf/TopBar.tsx`

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/components/hlidskjalf/IncidentToast.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { IncidentToast } from "./IncidentToast";
import type { Incident } from "../../types/incident";

const inc: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "Kurdistan · Thermal Escalation",
  severity: "high",
  coords: [36.34, 41.87],
  location: "Sinjar ridge",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: ["firms·1"],
  layer_hints: ["firmsHotspots"],
  timeline: [],
};

describe("IncidentToast", () => {
  it("renders nothing when incident is null", () => {
    const { container } = render(
      <MemoryRouter>
        <IncidentToast incident={null} onDismiss={() => {}} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows title + Open War Room link when incident present", () => {
    render(
      <MemoryRouter>
        <IncidentToast incident={inc} onDismiss={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Kurdistan/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /open war room/i });
    expect(link).toHaveAttribute("href", "/warroom/inc-001");
  });

  it("auto-dismisses after the configured ttl", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(
      <MemoryRouter>
        <IncidentToast incident={inc} onDismiss={onDismiss} ttlMs={500} />
      </MemoryRouter>,
    );
    vi.advanceTimersByTime(600);
    expect(onDismiss).toHaveBeenCalled();
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Implementation — `IncidentToast.tsx`**

```typescript
// services/frontend/src/components/hlidskjalf/IncidentToast.tsx
/**
 * IncidentToast — spec §4.4.3 notification pattern.
 *
 * Top-right sentinel-tinted toast with title, coords, and `▸ Open War Room`.
 * No automatic navigation — user opts in. TTL 12 s by default.
 */
import { useEffect, type CSSProperties } from "react";
import { Link } from "react-router-dom";

import type { Incident } from "../../types/incident";

export interface IncidentToastProps {
  incident: Incident | null;
  onDismiss: () => void;
  ttlMs?: number;
}

const containerStyle: CSSProperties = {
  position: "fixed",
  top: "60px",
  right: "16px",
  zIndex: 1000,
  width: "320px",
  background: "rgba(18,17,14,0.92)",
  border: "1px solid var(--sentinel)",
  borderTop: "2px solid var(--sentinel)",
  padding: "0.75rem 1rem",
  backdropFilter: "blur(10px)",
};

const eyebrowStyle: CSSProperties = {
  fontFamily: '"Martian Mono", monospace',
  fontSize: "9px",
  letterSpacing: "0.22em",
  color: "var(--sentinel)",
  textTransform: "uppercase",
};

const titleStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "15px",
  color: "var(--parchment)",
  margin: "0.25rem 0",
  lineHeight: 1.2,
};

const metaStyle: CSSProperties = {
  fontFamily: '"Martian Mono", monospace',
  fontSize: "10px",
  color: "var(--stone)",
  marginBottom: "0.5rem",
};

const linkStyle: CSSProperties = {
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "11px",
  textTransform: "uppercase",
  letterSpacing: "0.2em",
  color: "var(--sentinel)",
  textDecoration: "none",
};

export function IncidentToast({ incident, onDismiss, ttlMs = 12_000 }: IncidentToastProps) {
  useEffect(() => {
    if (!incident) return;
    const id = window.setTimeout(onDismiss, ttlMs);
    return () => window.clearTimeout(id);
  }, [incident, onDismiss, ttlMs]);

  if (!incident) return null;

  return (
    <aside role="status" aria-live="polite" data-part="incident-toast" style={containerStyle}>
      <div style={eyebrowStyle}>incident · live</div>
      <h2 style={titleStyle}>{incident.title}</h2>
      <div style={metaStyle}>
        {incident.coords[0].toFixed(2)}N · {incident.coords[1].toFixed(2)}E
      </div>
      <Link
        to={`/warroom/${incident.id}`}
        style={linkStyle}
        onClick={onDismiss}
      >
        ▸ Open War Room
      </Link>
    </aside>
  );
}
```

- [ ] **Step 3: Wire into `AppShell` + TopBar pulse**

Replace `services/frontend/src/app/AppShell.tsx` with:

```typescript
import { useState } from "react";
import { Outlet } from "react-router-dom";
import { TopBar } from "../components/hlidskjalf/TopBar";
import { IncidentToast } from "../components/hlidskjalf/IncidentToast";
import { IncidentProvider } from "../state/IncidentProvider";
import { useIncidents } from "../hooks/useIncidents";

/**
 * IncidentLayer — separate component so the SSE-bound state (read by
 * useIncidents) lives BELOW <IncidentProvider>. AppShell itself stays
 * outside the provider so it never reads stale context.
 */
function IncidentLayer({ children }: { children: React.ReactNode }) {
  const { active } = useIncidents();
  const [dismissedId, setDismissedId] = useState<string | null>(null);
  const toastIncident = active && active.id !== dismissedId ? active : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <TopBar warRoomActive={Boolean(active)} />
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          position: "relative",
        }}
      >
        {children}
      </main>
      <IncidentToast
        incident={toastIncident}
        onDismiss={() => setDismissedId(active?.id ?? null)}
      />
    </div>
  );
}

export function AppShell() {
  return (
    <IncidentProvider>
      <IncidentLayer>
        <Outlet />
      </IncidentLayer>
    </IncidentProvider>
  );
}
```

In `services/frontend/src/components/hlidskjalf/TopBar.tsx`:

1. Change the `TopBar` signature to accept an optional `warRoomActive?: boolean`.
2. Add a `pulsingDotStyle` that uses CSS animation `@keyframes incidentPulse` (define inline at top of file via a module-scoped string or — preferred — a class in `services/frontend/src/index.css`).
3. When `warRoomActive` is true AND the tab is not the active route, render the sentinel dot with `data-tab-dot="pulsing"` and the pulsing class so existing tests still find a sentinel dot via `data-tab-dot`.

Add this CSS block to `services/frontend/src/index.css`:

```css
@keyframes hlidIncidentPulse {
  0%, 100% { opacity: 0.4; }
  50%      { opacity: 1.0; }
}
.hlid-pulse {
  animation: hlidIncidentPulse 1.4s ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .hlid-pulse { animation: none; opacity: 1.0; }
}
```

Modify the War Room tab branch in `TopBar.tsx`:

```tsx
) : isWarRoom ? (
  <span
    data-tab-dot={warRoomActive ? "pulsing" : "sentinel"}
    className={warRoomActive ? "hlid-pulse" : undefined}
    style={{
      ...sentinelDotStyle,
      opacity: warRoomActive ? 1 : 0.65,
    }}
    aria-hidden="true"
  />
) : null}
```

And add the prop to the function signature:

```tsx
export function TopBar({ warRoomActive = false }: { warRoomActive?: boolean }) {
```

> **Existing TopBar tests** in `OverlayPanel.test.tsx` and any TopBar tests must keep passing — the prop has a default, so call sites without it still work.

- [ ] **Step 4: Run all frontend tests**

```bash
cd services/frontend && npm test -- IncidentToast TopBar
cd services/frontend && npm test
```
Expected: full suite still green; new toast tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/hlidskjalf/IncidentToast.tsx \
        services/frontend/src/components/hlidskjalf/IncidentToast.test.tsx \
        services/frontend/src/app/AppShell.tsx \
        services/frontend/src/components/hlidskjalf/TopBar.tsx \
        services/frontend/src/index.css
git commit -m "feat(frontend): incident toast + pulsing war-room tab-dot (S4·10)"
```

---

## Task 11 · `AgentStreamLine` Primitive

**Files:**
- Create: `services/frontend/src/components/hlidskjalf/AgentStreamLine.tsx`
- Test:   `services/frontend/src/components/hlidskjalf/AgentStreamLine.test.tsx`

Spec §4.4.2 — `[T+hh:mm.ss] tool/→ <detail>`.

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/components/hlidskjalf/AgentStreamLine.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentStreamLine } from "./AgentStreamLine";

describe("AgentStreamLine", () => {
  it("renders timestamp, tool, and detail in mono", () => {
    render(<AgentStreamLine tplus="T+02:14:08" tool="qdrant.search" detail="12 hits · 0.71" />);
    expect(screen.getByText("T+02:14:08")).toBeInTheDocument();
    expect(screen.getByText("qdrant.search")).toBeInTheDocument();
    expect(screen.getByText(/12 hits/)).toBeInTheDocument();
  });

  it("colour-codes by tone", () => {
    const { container } = render(
      <AgentStreamLine tplus="T+00:00:01" tool="x" detail="y" tone="amber" />,
    );
    expect(container.firstChild).toHaveAttribute("data-tone", "amber");
  });
});
```

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/components/hlidskjalf/AgentStreamLine.tsx
import type { CSSProperties } from "react";

export type AgentStreamTone = "amber" | "sage" | "sentinel" | "stone";

export interface AgentStreamLineProps {
  tplus: string;
  tool: string;
  detail: string;
  tone?: AgentStreamTone;
}

const TONE_VAR: Record<AgentStreamTone, string> = {
  amber: "var(--amber)",
  sage: "var(--sage)",
  sentinel: "var(--sentinel)",
  stone: "var(--stone)",
};

const baseStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "78px 1fr",
  gap: "0.75rem",
  alignItems: "baseline",
  padding: "2px 0",
  fontFamily: '"Martian Mono", monospace',
  fontSize: "10px",
  letterSpacing: "0.04em",
  color: "var(--stone)",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

export function AgentStreamLine({
  tplus,
  tool,
  detail,
  tone = "stone",
}: AgentStreamLineProps) {
  return (
    <div data-part="agent-stream-line" data-tone={tone} style={baseStyle}>
      <span style={{ color: "var(--ash)" }}>{tplus}</span>
      <span>
        <span style={{ color: TONE_VAR[tone] }}>{tool}</span>
        <span style={{ color: "var(--ash)" }}> /→ </span>
        <span>{detail}</span>
      </span>
    </div>
  );
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- AgentStreamLine
git add services/frontend/src/components/hlidskjalf/AgentStreamLine.tsx services/frontend/src/components/hlidskjalf/AgentStreamLine.test.tsx
git commit -m "feat(frontend): AgentStreamLine primitive — mono tool-call display (S4·11)"
```

Expected: 2 passed.

---

## Task 12 · `LeaderCallout` Primitive (design-i adaptation)

**Files:**
- Create: `services/frontend/src/components/hlidskjalf/LeaderCallout.tsx`
- Test:   `services/frontend/src/components/hlidskjalf/LeaderCallout.test.tsx`

Renders a hair-line from a card edge to a target dot — used by Theatre to overlay entity callouts on the globe. The visual idea is borrowed from reference `i` but stripped of cyan/glow.

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/components/hlidskjalf/LeaderCallout.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LeaderCallout } from "./LeaderCallout";

describe("LeaderCallout", () => {
  it("renders eyebrow + value + optional sub", () => {
    render(
      <LeaderCallout
        eyebrow="Healthcare"
        value="23,560"
        sub="Bed availability"
        leader={{ from: "right", deltaPx: 80 }}
      />,
    );
    expect(screen.getByText("Healthcare")).toBeInTheDocument();
    expect(screen.getByText("23,560")).toBeInTheDocument();
    expect(screen.getByText("Bed availability")).toBeInTheDocument();
  });

  it("draws a leader line svg", () => {
    const { container } = render(
      <LeaderCallout
        eyebrow="x"
        value="1"
        leader={{ from: "left", deltaPx: 60 }}
      />,
    );
    expect(container.querySelector("svg[data-part='leader']")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/components/hlidskjalf/LeaderCallout.tsx
/**
 * LeaderCallout — floating Basalt card with a hair-line "leader" pointing to
 * an off-card anchor (e.g. an entity dot on the globe). Visual cue borrowed
 * from the design-`i` Pandemic Prediction System reference and re-coloured
 * for Hlíðskjalf (no cyan, no rounded corners, no glow).
 */
import type { CSSProperties, ReactNode } from "react";

export type LeaderDirection = "left" | "right" | "up" | "down";
export type LeaderTone = "amber" | "sentinel" | "sage" | "stone";

export interface LeaderCalloutProps {
  eyebrow: string;
  value: ReactNode;
  sub?: string;
  leader: { from: LeaderDirection; deltaPx: number };
  tone?: LeaderTone;
  style?: CSSProperties;
}

const cardStyle: CSSProperties = {
  position: "relative",
  background: "rgba(26,24,20,0.84)",
  border: "1px solid var(--granite)",
  padding: "0.5rem 0.75rem",
  minWidth: "120px",
  backdropFilter: "blur(6px)",
};

const eyebrowStyle: CSSProperties = {
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "9px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color: "var(--ash)",
};

const valueStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "20px",
  color: "var(--parchment)",
  lineHeight: 1.1,
  marginTop: "2px",
};

const subStyle: CSSProperties = {
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "10px",
  color: "var(--stone)",
  marginTop: "2px",
};

const TONE_VAR: Record<LeaderTone, string> = {
  amber: "var(--amber)",
  sentinel: "var(--sentinel)",
  sage: "var(--sage)",
  stone: "var(--stone)",
};

export function LeaderCallout({
  eyebrow,
  value,
  sub,
  leader,
  tone = "amber",
  style,
}: LeaderCalloutProps) {
  const { from, deltaPx } = leader;
  // Build an absolutely-positioned 1px hairline + terminal dot.
  // The svg is placed adjacent to the card on the `from` side and extends
  // outward by `deltaPx`. Card itself stays in its parent's flow.
  const isHorizontal = from === "left" || from === "right";
  const svgWidth = isHorizontal ? deltaPx : 12;
  const svgHeight = isHorizontal ? 12 : deltaPx;
  const x1 = from === "right" ? 0 : svgWidth;
  const y1 = isHorizontal ? svgHeight / 2 : (from === "down" ? 0 : svgHeight);
  const x2 = from === "right" ? svgWidth : 0;
  const y2 = isHorizontal ? svgHeight / 2 : (from === "down" ? svgHeight : 0);

  const positionStyle: CSSProperties =
    from === "right"
      ? { left: "100%", top: "50%", transform: "translateY(-50%)" }
      : from === "left"
      ? { right: "100%", top: "50%", transform: "translateY(-50%)" }
      : from === "down"
      ? { left: "50%", top: "100%", transform: "translateX(-50%)" }
      : { left: "50%", bottom: "100%", transform: "translateX(-50%)" };

  return (
    <div data-part="leader-callout" style={{ ...cardStyle, ...style }}>
      <div style={eyebrowStyle}>○ {eyebrow}</div>
      <div style={valueStyle}>{value}</div>
      {sub ? <div style={subStyle}>{sub}</div> : null}
      <svg
        data-part="leader"
        width={svgWidth}
        height={svgHeight}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        style={{ position: "absolute", pointerEvents: "none", ...positionStyle }}
        aria-hidden="true"
      >
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--granite)" strokeWidth={1} />
        <circle cx={x2} cy={y2} r={2.5} fill={TONE_VAR[tone]} />
      </svg>
    </div>
  );
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- LeaderCallout
git add services/frontend/src/components/hlidskjalf/LeaderCallout.tsx services/frontend/src/components/hlidskjalf/LeaderCallout.test.tsx
git commit -m "feat(frontend): LeaderCallout primitive — hair-line entity callout (S4·12)"
```

Expected: 2 passed.

---

## Task 13 · `MuninCrystal` Primitive (design-i adaptation)

**Files:**
- Create: `services/frontend/src/components/hlidskjalf/MuninCrystal.tsx`
- Test:   `services/frontend/src/components/hlidskjalf/MuninCrystal.test.tsx`

A small inline SVG: three stacked rhombi in Amber stroke on transparent fill, with one rhombus gently brighter (foreground). Used in §III as the visual anchor of the agent panel — bridges the Orrery's geometric vocabulary into the Munin context.

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/components/hlidskjalf/MuninCrystal.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MuninCrystal } from "./MuninCrystal";

describe("MuninCrystal", () => {
  it("renders three rhombi", () => {
    const { container } = render(<MuninCrystal size={64} />);
    expect(container.querySelectorAll("svg [data-rhombus]")).toHaveLength(3);
  });

  it("respects size prop", () => {
    const { container } = render(<MuninCrystal size={120} />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "120");
  });
});
```

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/components/hlidskjalf/MuninCrystal.tsx
/**
 * MuninCrystal — inline SVG echo of the design-`i` "isometric stack" motif.
 *
 * Three stroked rhombi stacked vertically; the centre one is slightly
 * brighter (foreground). Pure SVG, no animation, no rounded corners.
 */
import type { CSSProperties } from "react";

export interface MuninCrystalProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export function MuninCrystal({ size = 64, className, style }: MuninCrystalProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="-50 -50 100 100"
      data-part="munin-crystal"
      aria-hidden="true"
      className={className}
      style={style}
    >
      {/* Top rhombus (background) */}
      <polygon
        data-rhombus="top"
        points="0,-32 24,-20 0,-8 -24,-20"
        fill="none"
        stroke="var(--amber)"
        strokeOpacity={0.45}
        strokeWidth={1}
      />
      {/* Middle rhombus (foreground / brightest) */}
      <polygon
        data-rhombus="mid"
        points="0,-12 30,4 0,20 -30,4"
        fill="rgba(196,129,58,0.10)"
        stroke="var(--amber)"
        strokeOpacity={0.95}
        strokeWidth={1.25}
      />
      {/* Bottom rhombus (background) */}
      <polygon
        data-rhombus="bot"
        points="0,18 24,30 0,42 -24,30"
        fill="none"
        stroke="var(--amber)"
        strokeOpacity={0.45}
        strokeWidth={1}
      />
    </svg>
  );
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- MuninCrystal
git add services/frontend/src/components/hlidskjalf/MuninCrystal.tsx services/frontend/src/components/hlidskjalf/MuninCrystal.test.tsx
git commit -m "feat(frontend): MuninCrystal primitive — isometric agent emblem (S4·13)"
```

Expected: 2 passed.

---

## Task 14 · `TimelineQuadrant`

**Files:**
- Create: `services/frontend/src/components/warroom/TimelineQuadrant.tsx`
- Test:   `services/frontend/src/components/warroom/TimelineQuadrant.test.tsx`

Spec §4.4.2 — chronological event list. T-time + dot + Instrument-Serif italic body; baseline reference (oldest) is the trigger.

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/components/warroom/TimelineQuadrant.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TimelineQuadrant } from "./TimelineQuadrant";
import type { Incident } from "../../types/incident";

const inc: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "x",
  severity: "high",
  coords: [0, 0],
  location: "-",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: [],
  layer_hints: [],
  timeline: [
    { t_offset_s: 0, kind: "trigger", text: "FIRMS threshold" },
    { t_offset_s: 68, kind: "signal", text: "UCDP severity HIGH", severity: "high" },
    { t_offset_s: 134, kind: "agent", text: "qdrant.search → 12 hits" },
  ],
};

describe("TimelineQuadrant", () => {
  it("renders newest-first list with trigger as baseline", () => {
    render(<TimelineQuadrant incident={inc} />);
    const items = screen.getAllByTestId("timeline-row");
    expect(items[0].textContent).toMatch(/qdrant\.search/);
    expect(items[items.length - 1].textContent).toMatch(/Trigger/i);
  });

  it("formats T-offsets as T+mm:ss", () => {
    render(<TimelineQuadrant incident={inc} />);
    expect(screen.getByText("T+01:08")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/components/warroom/TimelineQuadrant.tsx
import type { CSSProperties } from "react";

import type { Incident, IncidentTimelineEvent } from "../../types/incident";
import { SectionHeading } from "../hlidskjalf/SectionHeading";

const KIND_TONE: Record<string, string> = {
  trigger: "var(--sentinel)",
  signal: "var(--amber)",
  agent: "var(--sage)",
  source: "var(--stone)",
  note: "var(--ash)",
};

function formatOffset(s: number): string {
  const safe = Math.max(0, Math.floor(s));
  const mm = Math.floor(safe / 60);
  const ss = safe - mm * 60;
  return `T+${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

const rowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "62px 12px 1fr",
  gap: "0.5rem",
  alignItems: "baseline",
  padding: "4px 0",
  borderBottom: "1px solid var(--granite)",
};

const tStyle: CSSProperties = {
  fontFamily: '"Martian Mono", monospace',
  fontSize: "10px",
  color: "var(--stone)",
};

const dotStyle = (color: string): CSSProperties => ({
  width: 6,
  height: 6,
  borderRadius: "50%",
  background: color,
  alignSelf: "center",
});

const textStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "13px",
  color: "var(--bone)",
};

export interface TimelineQuadrantProps {
  incident: Incident;
}

export function TimelineQuadrant({ incident }: TimelineQuadrantProps) {
  const sorted: IncidentTimelineEvent[] = [...incident.timeline].sort(
    (a, b) => b.t_offset_s - a.t_offset_s,
  );
  return (
    <section data-quadrant="timeline" style={{ padding: "1rem", overflow: "auto" }}>
      <SectionHeading number="II" label="Timeline" hair />
      <div role="list" style={{ marginTop: "0.5rem" }}>
        {sorted.map((event, idx) => {
          const isBaseline = event.kind === "trigger";
          return (
            <div
              key={`${event.t_offset_s}-${idx}`}
              role="listitem"
              data-testid="timeline-row"
              style={rowStyle}
            >
              <span style={tStyle}>{formatOffset(event.t_offset_s)}</span>
              <span style={dotStyle(KIND_TONE[event.kind] ?? KIND_TONE.note)} aria-hidden="true" />
              <span style={{ ...textStyle, color: isBaseline ? "var(--ash)" : "var(--bone)" }}>
                {isBaseline ? `Trigger · ${event.text}` : event.text}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- TimelineQuadrant
git add services/frontend/src/components/warroom/TimelineQuadrant.tsx services/frontend/src/components/warroom/TimelineQuadrant.test.tsx
git commit -m "feat(frontend): TimelineQuadrant — chronological incident events (S4·14)"
```

Expected: 2 passed.

---

## Task 15 · `MuninStreamQuadrant`

**Files:**
- Create: `services/frontend/src/components/warroom/MuninStreamQuadrant.tsx`
- Test:   `services/frontend/src/components/warroom/MuninStreamQuadrant.test.tsx`

Spec §4.4.2 — Munin tool-call stream + working hypothesis. v1 wires to existing `useIntel` (or its successor) keyed on `report_id = "incident-<id>"`. The MuninCrystal anchors the panel left; tool-call lines render right.

- [ ] **Step 1: Test (smoke — full agent integration tested in Task 17)**

```typescript
// services/frontend/src/components/warroom/MuninStreamQuadrant.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MuninStreamQuadrant } from "./MuninStreamQuadrant";

describe("MuninStreamQuadrant", () => {
  it("shows the working hypothesis when provided", () => {
    render(
      <MuninStreamQuadrant
        toolCalls={[
          { tplus: "T+00:01:08", tool: "qdrant.search", detail: "12 hits · 0.71" },
        ]}
        hypothesis="Cluster signature consistent with airstrike."
        onAsk={() => {}}
      />,
    );
    expect(screen.getByText(/Cluster signature/)).toBeInTheDocument();
    expect(screen.getByText("qdrant.search")).toBeInTheDocument();
  });

  it("invokes onAsk on submit", async () => {
    const onAsk = vi.fn();
    const { user } = renderWithUser(
      <MuninStreamQuadrant toolCalls={[]} hypothesis="" onAsk={onAsk} />,
    );
    await user.type(screen.getByPlaceholderText(/ask munin/i), "what changed?");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onAsk).toHaveBeenCalledWith("what changed?");
  });
});

// helper at top of file:
import { vi } from "vitest";
import userEvent from "@testing-library/user-event";
function renderWithUser(ui: React.ReactNode) {
  const user = userEvent.setup();
  return { user, ...render(ui) };
}
```

> If `@testing-library/user-event` is not installed: replace the second test with a `fireEvent.keyDown` that simulates `Meta+Enter` directly.

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/components/warroom/MuninStreamQuadrant.tsx
import { useState, type CSSProperties, type FormEvent } from "react";

import { SectionHeading } from "../hlidskjalf/SectionHeading";
import { AgentStreamLine, type AgentStreamLineProps } from "../hlidskjalf/AgentStreamLine";
import { MuninCrystal } from "../hlidskjalf/MuninCrystal";

export interface MuninToolCall {
  tplus: string;
  tool: string;
  detail: string;
  tone?: AgentStreamLineProps["tone"];
}

export interface MuninStreamQuadrantProps {
  toolCalls: MuninToolCall[];
  hypothesis: string;
  onAsk: (prompt: string) => void;
  busy?: boolean;
}

const layoutStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "84px 1fr",
  gap: "0.75rem",
  padding: "1rem",
  height: "100%",
  minHeight: 0,
  overflow: "hidden",
};

const streamStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  minHeight: 0,
  height: "100%",
};

const callsStyle: CSSProperties = {
  flex: 1,
  overflowY: "auto",
  marginTop: "0.5rem",
  paddingRight: "4px",
};

const hypothesisStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "12px",
  color: "var(--bone)",
  borderTop: "1px solid var(--granite)",
  paddingTop: "0.5rem",
  marginTop: "0.5rem",
};

const inputStyle: CSSProperties = {
  marginTop: "0.5rem",
  width: "100%",
  background: "transparent",
  border: "1px solid var(--granite)",
  color: "var(--parchment)",
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "12px",
  padding: "0.5rem 0.75rem",
  outline: "none",
};

export function MuninStreamQuadrant({
  toolCalls,
  hypothesis,
  onAsk,
  busy = false,
}: MuninStreamQuadrantProps) {
  const [draft, setDraft] = useState("");

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const value = draft.trim();
    if (!value || busy) return;
    onAsk(value);
    setDraft("");
  }

  function handleKey(ev: React.KeyboardEvent<HTMLInputElement>) {
    if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
      ev.preventDefault();
      const value = draft.trim();
      if (!value || busy) return;
      onAsk(value);
      setDraft("");
    }
  }

  return (
    <section data-quadrant="munin" style={layoutStyle}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: "1.5rem" }}>
        <MuninCrystal size={72} />
        <span
          style={{
            fontFamily: '"Hanken Grotesk", sans-serif',
            fontSize: "9px",
            letterSpacing: "0.22em",
            color: "var(--ash)",
            textTransform: "uppercase",
            marginTop: "0.5rem",
          }}
        >
          munin
        </span>
      </div>
      <div style={streamStyle}>
        <SectionHeading number="III" label="Munin · stream" hair />
        <div style={callsStyle}>
          {toolCalls.map((c, idx) => (
            <AgentStreamLine key={idx} tplus={c.tplus} tool={c.tool} detail={c.detail} tone={c.tone} />
          ))}
          {toolCalls.length === 0 ? (
            <div
              style={{
                fontFamily: '"Martian Mono", monospace',
                fontSize: "10px",
                color: "var(--ash)",
              }}
            >
              munin · idle
            </div>
          ) : null}
        </div>
        <div data-part="hypothesis" style={hypothesisStyle}>
          {hypothesis || "§ working hypothesis · pending first signal"}
        </div>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKey}
            placeholder="▸ ask Munin about this incident…  ⌘↩"
            style={inputStyle}
            disabled={busy}
          />
        </form>
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- MuninStreamQuadrant
git add services/frontend/src/components/warroom/MuninStreamQuadrant.tsx services/frontend/src/components/warroom/MuninStreamQuadrant.test.tsx
git commit -m "feat(frontend): MuninStreamQuadrant — agent stream + hypothesis + ask (S4·15)"
```

Expected: 2 passed (or 1 if user-event fallback path used).

---

## Task 16 · `RawSourcesQuadrant`

**Files:**
- Create: `services/frontend/src/components/warroom/RawSourcesQuadrant.tsx`
- Test:   `services/frontend/src/components/warroom/RawSourcesQuadrant.test.tsx`

Spec §4.4.2 — sources as Basalt cards in a 2×2 grid + action row (Promote / Silence / Ask).

- [ ] **Step 1: Test**

```typescript
// services/frontend/src/components/warroom/RawSourcesQuadrant.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RawSourcesQuadrant } from "./RawSourcesQuadrant";
import type { Incident } from "../../types/incident";

const inc: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "x",
  severity: "high",
  coords: [0, 0],
  location: "-",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: ["firms·14 det.", "ucdp·#44821", "gdelt·4 art.", "ais·anomaly"],
  layer_hints: [],
  timeline: [],
};

describe("RawSourcesQuadrant", () => {
  it("renders one card per source up to 4", () => {
    render(<RawSourcesQuadrant incident={inc} onPromote={vi.fn()} onSilence={vi.fn()} onAsk={vi.fn()} />);
    expect(screen.getAllByTestId("source-card")).toHaveLength(4);
  });

  it("calls onPromote when the promote action is clicked", () => {
    const onPromote = vi.fn();
    render(<RawSourcesQuadrant incident={inc} onPromote={onPromote} onSilence={vi.fn()} onAsk={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /promote to dossier/i }));
    expect(onPromote).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Implementation**

```typescript
// services/frontend/src/components/warroom/RawSourcesQuadrant.tsx
import type { CSSProperties } from "react";

import type { Incident } from "../../types/incident";
import { SectionHeading } from "../hlidskjalf/SectionHeading";

const SOURCE_TONE: Record<string, string> = {
  firms: "var(--sentinel)",
  ucdp: "var(--amber)",
  gdelt: "var(--sage)",
  ais: "var(--stone)",
  default: "var(--stone)",
};

function toneFor(label: string): string {
  const head = label.split(/[·\s]/, 1)[0]?.toLowerCase() ?? "default";
  return SOURCE_TONE[head] ?? SOURCE_TONE.default;
}

const gridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: "0.5rem",
  marginTop: "0.5rem",
};

const cardStyle: CSSProperties = {
  background: "var(--basalt)",
  border: "1px solid var(--granite)",
  padding: "0.5rem 0.75rem",
  minHeight: "62px",
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
};

const tagStyle = (color: string): CSSProperties => ({
  fontFamily: '"Martian Mono", monospace',
  fontSize: "9px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  color,
});

const titleStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "12px",
  color: "var(--bone)",
};

const actionRowStyle: CSSProperties = {
  display: "flex",
  gap: "1rem",
  marginTop: "0.75rem",
  paddingTop: "0.5rem",
  borderTop: "1px solid var(--granite)",
};

const actionButtonStyle = (color: string): CSSProperties => ({
  background: "transparent",
  border: "none",
  color,
  fontFamily: '"Hanken Grotesk", sans-serif',
  fontSize: "10px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  cursor: "pointer",
  padding: 0,
});

export interface RawSourcesQuadrantProps {
  incident: Incident;
  onPromote: () => void;
  onSilence: () => void;
  onAsk: () => void;
}

export function RawSourcesQuadrant({
  incident,
  onPromote,
  onSilence,
  onAsk,
}: RawSourcesQuadrantProps) {
  const sources = incident.sources.slice(0, 4);
  return (
    <section data-quadrant="raw" style={{ padding: "1rem", display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <SectionHeading number="IV" label="Raw · sources" hair />
      <div style={gridStyle}>
        {sources.map((source) => {
          const tone = toneFor(source);
          const [head, ...rest] = source.split(/·\s*/);
          return (
            <article key={source} data-testid="source-card" style={cardStyle}>
              <div style={tagStyle(tone)}>{head}</div>
              <div style={titleStyle}>{rest.join(" · ") || "—"}</div>
            </article>
          );
        })}
      </div>
      <div style={actionRowStyle}>
        <button
          type="button"
          onClick={onPromote}
          style={{ ...actionButtonStyle("var(--sentinel)"), textDecoration: "underline", textUnderlineOffset: 4 }}
        >
          ▸ Promote to dossier
        </button>
        <button type="button" onClick={onSilence} style={actionButtonStyle("var(--stone)")}>
          Silence alert
        </button>
        <button type="button" onClick={onAsk} style={actionButtonStyle("var(--amber)")}>
          Ask Munin
        </button>
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Run + commit**

```bash
cd services/frontend && npm test -- RawSourcesQuadrant
git add services/frontend/src/components/warroom/RawSourcesQuadrant.tsx services/frontend/src/components/warroom/RawSourcesQuadrant.test.tsx
git commit -m "feat(frontend): RawSourcesQuadrant — basalt source cards + action row (S4·16)"
```

Expected: 2 passed.

---

## Task 17 · `TheatreQuadrant`

**Files:**
- Create: `services/frontend/src/components/warroom/TheatreQuadrant.tsx`

Re-uses `<GlobeViewer>` and the existing layer components (FIRMS / EONET / etc.) but mounts a fresh viewer instance scoped to this quadrant. On incident change, `flyTo` the bbox = `incident.coords ± 0.6°`. Renders 1–3 `LeaderCallout` overlays positioned in the quadrant's safe zone (top-right, bottom-left), each pointing toward the screen-projected location of the incident dot.

For v1 keep the layer set hard-wired to the incident's `layer_hints` (e.g. `firmsHotspots`, `gdacs`, `eonet`). Layer-projection-to-screen-pixels is non-trivial; v1 callouts use **fixed corner positions** (top-right of quadrant) with leader lines projecting *toward the center* of the viewport rather than computing live screen coords on every camera tick. A follow-up can wire `viewer.scene.cartesianToCanvasCoordinates` for pixel-accurate leaders.

No tests for this task — Cesium is hard to render in JSDOM. Manual visual check in Task 19.

- [ ] **Step 1: Implementation**

```typescript
// services/frontend/src/components/warroom/TheatreQuadrant.tsx
import { useCallback, useEffect, useState, type CSSProperties } from "react";
import * as Cesium from "cesium";

import { GlobeViewer } from "../globe/GlobeViewer";
import { FIRMSLayer } from "../layers/FIRMSLayer";
import { EONETLayer } from "../layers/EONETLayer";
import { GDACSLayer } from "../layers/GDACSLayer";
import { LeaderCallout } from "../hlidskjalf/LeaderCallout";
import { SectionHeading } from "../hlidskjalf/SectionHeading";
import { useFIRMSHotspots } from "../../hooks/useFIRMSHotspots";
import { useEONETEvents } from "../../hooks/useEONETEvents";
import { useGDACSEvents } from "../../hooks/useGDACSEvents";
import type { Incident } from "../../types/incident";

export interface TheatreQuadrantProps {
  incident: Incident | null;
  cesiumToken: string;
}

export function TheatreQuadrant({ incident, cesiumToken }: TheatreQuadrantProps) {
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const handleViewerReady = useCallback((created: Cesium.Viewer) => setViewer(created), []);

  const showFIRMS = Boolean(incident?.layer_hints.includes("firmsHotspots"));
  const showEONET = Boolean(incident?.layer_hints.includes("eonet"));
  const showGDACS = Boolean(incident?.layer_hints.includes("gdacs"));

  const { hotspots: firms } = useFIRMSHotspots(showFIRMS);
  const { events: eonet } = useEONETEvents(showEONET);
  const { events: gdacs } = useGDACSEvents(showGDACS);

  // Fly to incident.
  useEffect(() => {
    if (!viewer || !incident) return;
    const [lat, lon] = incident.coords;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, 850_000),
      duration: 1.4,
    });
  }, [viewer, incident]);

  if (!incident) {
    return (
      <section data-quadrant="theatre" style={emptyStyle}>
        <SectionHeading number="I" label="Theatre" hair />
        <div style={emptyMessageStyle}>
          <span>§ no active incident · standing watch</span>
        </div>
      </section>
    );
  }

  return (
    <section data-quadrant="theatre" style={{ position: "relative", overflow: "hidden", height: "100%" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <GlobeViewer
          onViewerReady={handleViewerReady}
          cesiumToken={cesiumToken}
          activeShader="none"
          showCountryBorders
          showCityBuildings={false}
        />
      </div>
      <FIRMSLayer viewer={viewer} hotspots={firms} visible={showFIRMS} onSelect={() => {}} />
      <EONETLayer viewer={viewer} events={eonet} visible={showEONET} onSelect={() => {}} />
      <GDACSLayer viewer={viewer} events={gdacs} visible={showGDACS} onSelect={() => {}} />

      {/* Heading floats in the top-left corner */}
      <div style={{ position: "absolute", top: 12, left: 12, zIndex: 5 }}>
        <SectionHeading number="I" label={`Theatre · ${incident.location || "—"}`} hair />
      </div>

      {/* Leader callouts (v1: fixed corner placement) */}
      <div style={{ position: "absolute", top: 60, right: 16, zIndex: 5 }}>
        <LeaderCallout
          eyebrow={incident.kind.replace(".", " · ")}
          value={incident.severity.toUpperCase()}
          sub={`${incident.coords[0].toFixed(2)}N · ${incident.coords[1].toFixed(2)}E`}
          leader={{ from: "left", deltaPx: 90 }}
          tone="sentinel"
        />
      </div>
      <div style={{ position: "absolute", bottom: 16, left: 16, zIndex: 5 }}>
        <LeaderCallout
          eyebrow="Sources"
          value={String(incident.sources.length)}
          sub="raw feeds engaged"
          leader={{ from: "right", deltaPx: 90 }}
          tone="amber"
        />
      </div>
    </section>
  );
}

const emptyStyle: CSSProperties = {
  position: "relative",
  display: "flex",
  flexDirection: "column",
  padding: "1rem",
  height: "100%",
  background:
    "radial-gradient(circle at 50% 50%, rgba(196,129,58,0.06) 0%, rgba(11,10,8,0) 60%)",
};

const emptyMessageStyle: CSSProperties = {
  flex: 1,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "italic",
  fontSize: "16px",
  color: "var(--ash)",
};
```

- [ ] **Step 2: Commit**

```bash
git add services/frontend/src/components/warroom/TheatreQuadrant.tsx
git commit -m "feat(frontend): TheatreQuadrant — Cesium incident view + leader callouts (S4·17)"
```

---

## Task 18 · `WarRoomPage` Assembly

**Files:**
- Modify: `services/frontend/src/pages/WarRoomPage.tsx` (replace stub)
- Create: `services/frontend/src/components/warroom/warRoomLayout.css`
- Test:   `services/frontend/src/pages/WarRoomPage.test.tsx`

The page reads `:incidentId` from the URL when present; otherwise it uses `useIncidents().active`. When neither is present, the empty Theatre + the rest of the chrome still render.

- [ ] **Step 1: Layout CSS**

```css
/* services/frontend/src/components/warroom/warRoomLayout.css */
.warroom-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 1px;
  background: var(--granite);
  flex: 1;
  min-height: 0;
}
.warroom-cell {
  background: var(--obsidian);
  min-height: 0;
  overflow: hidden;
}
.warroom-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: "Instrument Serif", serif;
  font-style: italic;
  color: var(--ash);
}
```

- [ ] **Step 2: Test**

```typescript
// services/frontend/src/pages/WarRoomPage.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { WarRoomPage } from "./WarRoomPage";

vi.mock("../hooks/useIncidents", () => ({
  useIncidents: () => ({
    status: "live",
    active: null,
    history: [],
    latestEnvelope: null,
  }),
}));

vi.mock("../services/api", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return {
    ...actual,
    getConfig: vi.fn().mockResolvedValue({ cesium_ion_token: "" }),
    getIncident: vi.fn().mockResolvedValue(null),
    queryIntel: vi.fn().mockReturnValue(() => {}),
    silenceIncident: vi.fn().mockResolvedValue(null),
    promoteIncident: vi.fn().mockResolvedValue(null),
  };
});

describe("WarRoomPage", () => {
  it("renders the empty Theatre + four quadrant frames when no incident", async () => {
    render(
      <MemoryRouter initialEntries={["/warroom"]}>
        <Routes>
          <Route path="/warroom" element={<WarRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/no active incident/)).toBeInTheDocument();
    expect(screen.getByText(/Timeline/)).toBeInTheDocument();
    expect(screen.getByText(/Munin · stream/)).toBeInTheDocument();
    expect(screen.getByText(/Raw · sources/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Implementation**

```typescript
// services/frontend/src/pages/WarRoomPage.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { IncidentBar } from "../components/hlidskjalf/IncidentBar";
import { TheatreQuadrant } from "../components/warroom/TheatreQuadrant";
import { TimelineQuadrant } from "../components/warroom/TimelineQuadrant";
import {
  MuninStreamQuadrant,
  type MuninToolCall,
} from "../components/warroom/MuninStreamQuadrant";
import { RawSourcesQuadrant } from "../components/warroom/RawSourcesQuadrant";
import { useIncidents } from "../hooks/useIncidents";
import {
  getConfig,
  getIncident,
  promoteIncident,
  queryIntel,
  silenceIncident,
} from "../services/api";
import type { Incident } from "../types/incident";

import "../components/warroom/warRoomLayout.css";

export function WarRoomPage() {
  const params = useParams<{ incidentId?: string }>();
  const navigate = useNavigate();
  const { active } = useIncidents();
  const [routedIncident, setRoutedIncident] = useState<Incident | null>(null);
  const [token, setToken] = useState<string>("");
  const [toolCalls, setToolCalls] = useState<MuninToolCall[]>([]);
  const [hypothesis, setHypothesis] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const abortRef = useRef<(() => void) | null>(null);

  // Resolve which incident this page should display.
  useEffect(() => {
    let cancelled = false;
    if (!params.incidentId) {
      setRoutedIncident(null);
      return;
    }
    void getIncident(params.incidentId)
      .then((rec) => {
        if (!cancelled) setRoutedIncident(rec);
      })
      .catch(() => {
        if (!cancelled) setRoutedIncident(null);
      });
    return () => {
      cancelled = true;
    };
  }, [params.incidentId]);

  const incident = routedIncident ?? active;

  // Cesium token (one-shot fetch; component-level cache is fine for v1).
  useEffect(() => {
    void getConfig()
      .then((cfg) => setToken(cfg.cesium_ion_token ?? ""))
      .catch(() => setToken(""));
  }, []);

  // Reset Munin surface when the incident changes; abort any in-flight query.
  useEffect(() => {
    abortRef.current?.();
    abortRef.current = null;
    setToolCalls([]);
    setHypothesis("");
    setBusy(false);
  }, [incident?.id]);

  const handlePromote = useCallback(async () => {
    if (!incident) return;
    await promoteIncident(incident.id);
    navigate(`/briefing?from=incident&id=${encodeURIComponent(incident.id)}`);
  }, [incident, navigate]);

  const handleSilence = useCallback(async () => {
    if (!incident) return;
    await silenceIncident(incident.id);
  }, [incident]);

  const handleAsk = useCallback(
    (prompt: string) => {
      if (!incident || busy) return;
      // Reflect the user ask immediately so the §III surface feels live.
      setToolCalls((prev) => [
        ...prev,
        {
          tplus: nowTplus(incident),
          tool: "munin.ask",
          detail: prompt.slice(0, 80),
          tone: "amber",
        },
      ]);
      setHypothesis(`Pending: «${prompt}»`);
      setBusy(true);

      const region = `${incident.coords[0].toFixed(3)},${incident.coords[1].toFixed(3)}`;
      const abort = queryIntel(
        {
          query: `[incident ${incident.id} · ${incident.title}] ${prompt}`,
          region,
          report_id: `incident-${incident.id}`,
        },
        // onStatus → push tool-call breadcrumb
        (status) => {
          setToolCalls((prev) => [
            ...prev,
            {
              tplus: nowTplus(incident),
              tool: status.agent || "agent",
              detail: status.status ?? "running",
              tone: "sage",
            },
          ]);
        },
        // onAnalysis → final synthesis becomes the working hypothesis.
        // IntelAnalysis fields (services/backend/app/models/intel.py):
        // - `analysis`   — the synthesised body (always present)
        // - `threat_assessment` — short label, optional
        (analysis) => {
          const body = analysis.analysis?.trim() ?? "";
          const label = analysis.threat_assessment?.trim() ?? "";
          const composed = label ? `[${label}] ${body}` : body;
          setHypothesis(composed || "Munin returned no synthesis.");
        },
        // onError → surface the failure as a sentinel-toned breadcrumb
        (error) => {
          setToolCalls((prev) => [
            ...prev,
            {
              tplus: nowTplus(incident),
              tool: "munin.error",
              detail: error.slice(0, 80),
              tone: "sentinel",
            },
          ]);
          setBusy(false);
          abortRef.current = null;
        },
        // onDone
        () => {
          setBusy(false);
          abortRef.current = null;
        },
      );
      abortRef.current = abort;
    },
    [incident, busy],
  );

  // Cancel any in-flight query on unmount.
  useEffect(() => {
    return () => {
      abortRef.current?.();
      abortRef.current = null;
    };
  }, []);

  const incidentBar = useMemo(
    () => (incident ? <IncidentBar incident={incident} /> : null),
    [incident],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }} data-page="warroom">
      {incidentBar}
      <div className="warroom-grid">
        <div className="warroom-cell">
          <TheatreQuadrant incident={incident} cesiumToken={token} />
        </div>
        <div className="warroom-cell">
          {incident ? (
            <TimelineQuadrant incident={incident} />
          ) : (
            <div className="warroom-empty">§ Timeline · empty</div>
          )}
        </div>
        <div className="warroom-cell">
          <MuninStreamQuadrant
            toolCalls={toolCalls}
            hypothesis={hypothesis}
            onAsk={handleAsk}
            busy={busy}
          />
        </div>
        <div className="warroom-cell">
          {incident ? (
            <RawSourcesQuadrant
              incident={incident}
              onPromote={handlePromote}
              onSilence={handleSilence}
              onAsk={() => handleAsk("Brief me on this incident")}
            />
          ) : (
            <div className="warroom-empty">§ Raw · no sources</div>
          )}
        </div>
      </div>
    </div>
  );
}

function nowTplus(incident: Incident | null): string {
  if (!incident) return "T+00:00:00";
  const seconds = Math.max(
    0,
    Math.floor((Date.now() - Date.parse(incident.trigger_ts)) / 1000),
  );
  const hh = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const mm = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return `T+${hh}:${mm}:${ss}`;
}
```

- [ ] **Step 4: Run all frontend tests**

```bash
cd services/frontend && npm test
```
Expected: full suite green, including the new WarRoomPage smoke test.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/pages/WarRoomPage.tsx \
        services/frontend/src/pages/WarRoomPage.test.tsx \
        services/frontend/src/components/warroom/warRoomLayout.css
git commit -m "feat(frontend): WarRoomPage assembly — incident bar + 4-quadrant grid (S4·18)"
```

---

## Task 19 · End-to-End Smoke + Visual Check

- [ ] **Step 1: Run full backend suite**

```bash
cd services/backend && uv run pytest
cd services/backend && uv run ruff check app/
```
Expected: all green, no ruff findings.

- [ ] **Step 2: Run full frontend suite + lint + type-check**

```bash
cd services/frontend && npm test
cd services/frontend && npm run lint
cd services/frontend && npm run type-check
```
Expected: all green.

- [ ] **Step 3: Manual smoke**

With backend already running (`osint-backend-1` is up per session start):

1. Trigger an incident via the admin endpoint:

```bash
curl -X POST http://localhost:8080/api/incidents/_admin/trigger \
  -H 'Content-Type: application/json' \
  -d '{
    "title":"Sinjar ridge thermal cluster",
    "kind":"firms.cluster",
    "severity":"high",
    "coords":[36.34,41.87],
    "location":"Sinjar ridge",
    "sources":["firms·14 det.","ucdp·#44821","gdelt·4 art.","ais·anomaly"],
    "layer_hints":["firmsHotspots"],
    "initial_text":"FIRMS threshold exceeded · n=17"
  }'
```

2. With `npm run dev` running on `:5173`, observe:
  - Toast appears top-right within ~2 s with title and `▸ Open War Room` link.
  - WAR ROOM tab dot in TopBar starts pulsing.
  - Click `▸ Open War Room` → `/warroom/inc-XXX` renders the incident bar (sentinel gradient + T+ clock ticking) and the four quadrants.
  - Theatre flies to the coords; FIRMS layer is on; LeaderCallouts visible.
  - Click "Silence alert" in §IV → bar disappears, tab dot stops pulsing.

3. **Capture two screenshots** — one with active incident, one empty state — and attach to the PR description. (Spec §9 success criterion #1 is qualitative — bypassed for plan execution but required at PR time.)

- [ ] **Step 4: Final commit (no code, just plan-doc tracking)**

```bash
git add docs/superpowers/plans/2026-04-25-odin-s4-war-room.md
git commit -m "docs(plan): mark S4 War Room plan as executed"
```

---

## Self-Review

**Spec coverage check:**
- §4.4.1 Incident-Bar — Task 9 ✓
- §4.4.2 Theatre — Task 17 ✓
- §4.4.2 Timeline — Task 14 ✓
- §4.4.2 Munin Stream + working hypothesis — Task 15 ✓
- §4.4.2 Raw Sources + actions — Task 16 ✓
- §4.4.3 Trigger via admin stub — Task 5 ✓
- §4.4.3 Toast notification (all views) — Task 10 ✓
- §4.4.3 Pulsing War Room dot — Task 10 ✓
- §4.4.3 T+ clock from trigger — Task 8 ✓
- §6 Realtime contract (replay + **reset re-hydrate**) — Tasks 4 + 5 + 7 ✓
- §6 SSE for Munin via existing `/api/intel/query` (WS deferred — see Scope Cuts) — Task 18 ✓
- §8 Promote-to-Dossier (full pre-fill) — partial / Task 18 + Scope Cuts

**Type consistency check:**
- `Incident.coords` is `[lat, lon]` everywhere (model, type, callouts).
- `IncidentEnvelope.type` strings match between backend (Tasks 4–5) and frontend (Task 6 type).
- `ReplayMode` semantics match between backend SignalStream and IncidentStream.
- `IntelAnalysis` fields used in Task 18 (`analysis`, `threat_assessment`) match `services/backend/app/models/intel.py`.

**Routing safety check (post-review patch):**
- FastAPI matches by declaration order. Task 5 explicitly declares
  `GET /stream` and `POST /_admin/trigger` BEFORE the dynamic
  `/{incident_id}` routes, with a regression test that asserts
  `GET /api/incidents/stream` returns `text/event-stream` (not 404 from
  the dynamic-id handler).

**State coherence check (post-review patch):**
- `IncidentProvider` opens the SSE once for the whole tree; `useIncidents`
  is a thin context consumer. AppShell wraps everything with
  `<IncidentProvider>` so the toast, the pulsing tab dot, and the
  WarRoomPage all read the same `active`/`history` state.
- Stream-side dedup is gone — the `event_id` is monotonic and the SSE
  replay window handles the wire-level dedup. Successive
  `incident.update` envelopes for the same incident always reach
  subscribers (regression-tested in Task 4).

**No-placeholder check:**
- Every step has either real code, a real command, or a single explicit decision (e.g. "if user-event is not installed, fall back to fireEvent" in Task 15).
- Task 6 introduces the missing `npm test` script as Step 0; all
  subsequent `npm test -- <pattern>` commands work as written.
