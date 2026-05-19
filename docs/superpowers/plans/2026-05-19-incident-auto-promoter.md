# Incident Auto-Promoter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert qualifying signals from `/api/signals/stream` into `Incident` records automatically, with four pluggable detectors (FIRMS, Severity, Telegram, GDELT), a single in-memory `ClusterStore`, a quiet-window sweeper, and explicit promote/silence wiring from the existing router.

**Architecture:** Single FastAPI lifespan task watches `SignalStream`. Detectors hold per-bucket pre-trigger deques and emit `ClusterHit` only when actionable. `ClusterStore` decides create-vs-update under phased locking, holds `_cooldowns` for silenced clusters, and fans out `on_cluster_terminated` callbacks so detectors reset their accumulation state. The Sweeper closes stale open clusters every 60 s and expires cooldowns. `incident_store.create_incident` stays unchanged — ignition incidents get a single trigger timeline entry; subsequent signals append via `apply_signal_update`.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, structlog, pytest + pytest-asyncio (mode=auto), Neo4j (only via existing Cypher templates).

**Spec reference:** `docs/superpowers/specs/2026-05-19-incident-auto-promoter-design.md` (commit `4d0b28f` or newer).

---

## File Structure

**New (source):**
```
services/backend/app/services/incident_promoter/
├── __init__.py                       # public exports
├── config.py                         # PromoterConfig (env-driven)
├── cluster_store.py                  # ClusterState + ClusterStore
├── promoter.py                       # Promoter (lifespan task) + Sweeper coroutine
└── detectors/
    ├── __init__.py
    ├── base.py                       # Detector Protocol + ClusterHit + build helpers
    ├── firms.py                      # FIRMSGeoClusterDetector
    ├── severity.py                   # SeverityBurstDetector
    ├── telegram.py                   # TelegramTopicDetector (shingles v1)
    └── gdelt.py                      # GDELTToneSpikeDetector (skeleton, default-off)
```

**New (tests):**
```
services/backend/tests/incident_promoter/
├── __init__.py
├── conftest.py                       # FakeClock, FakeIncidentStore, FakeIncidentEventStream,
│                                     # signal_envelope_factory
├── test_config.py
├── test_cluster_store.py
├── test_promoter.py                  # _subscribe/_rehydrate/_drain composability
├── test_router_wiring.py             # /promote and /silence call cluster_store
└── detectors/
    ├── __init__.py
    ├── test_firms.py
    ├── test_severity.py
    ├── test_telegram.py
    └── test_gdelt.py

services/backend/tests/integration/
├── __init__.py
└── test_promoter_pipeline.py         # 6 integration scenarios (§9.2 of spec)

services/backend/tests/e2e/
├── __init__.py
└── test_promoter_e2e.py
```

**Modified:**
- `services/backend/app/main.py` — lifespan boots Promoter, attaches `cluster_store` to `app.state`.
- `services/backend/app/services/incident_store.py` — adds `apply_signal_update`, `list_owned_for_rehydrate`; makes `close_incident` idempotent.
- `services/backend/app/routers/incidents.py` — `promote_incident` + `silence_incident` call `cluster_store.mark_promoted` / `mark_silenced`; adds `GET /_admin/promoter` route **before** `/{incident_id}`.
- `services/backend/tests/conftest.py` — set `app.state.cluster_store = None` (default) so unrelated router tests keep passing.
- `.env.example` (repo root or `services/backend/.env.example` — whichever already exists) — new `ODIN_PROMOTER_*` keys.

---

## Pre-flight (1 step, do once before Phase 1)

- [ ] **Step 1: Verify backend tests are green on `main` parity.**

Run:
```bash
cd services/backend && uv run pytest -q
```
Expected: all existing tests pass. If not, fix or note unrelated failures so they're not blamed on this plan later.

---

## Phase 1 — Foundation (Skeleton & Contract)

Goal: package layout, config, type definitions, ClusterStore skeleton, no-op Promoter behind the master flag. End of phase: backend boots; if `ODIN_PROMOTER_ENABLED=false` (default in tests), behavior is unchanged.

### Task 1.1: Scaffold `incident_promoter` package

**Files:**
- Create: `services/backend/app/services/incident_promoter/__init__.py`
- Create: `services/backend/app/services/incident_promoter/detectors/__init__.py`
- Create: `services/backend/tests/incident_promoter/__init__.py`
- Create: `services/backend/tests/incident_promoter/detectors/__init__.py`
- Create: `services/backend/tests/integration/__init__.py`
- Create: `services/backend/tests/e2e/__init__.py`

- [ ] **Step 1: Create empty `__init__.py` files for all six packages above.**

Each file is exactly:
```python
"""Auto-promoter package."""
```

- [ ] **Step 2: Verify imports work.**

Run:
```bash
cd services/backend && uv run python -c "import app.services.incident_promoter; import app.services.incident_promoter.detectors"
```
Expected: no output, exit 0.

- [ ] **Step 3: Commit.**
```bash
git add services/backend/app/services/incident_promoter services/backend/tests/incident_promoter services/backend/tests/integration services/backend/tests/e2e
git commit -m "feat(promoter): scaffold incident_promoter package layout"
```

---

### Task 1.2: `PromoterConfig`

**Files:**
- Create: `services/backend/app/services/incident_promoter/config.py`
- Create: `services/backend/tests/incident_promoter/test_config.py`

- [ ] **Step 1: Write the failing test.**

`services/backend/tests/incident_promoter/test_config.py`:
```python
"""Unit tests for PromoterConfig env loading."""
from app.services.incident_promoter.config import PromoterConfig


def test_defaults_match_spec(monkeypatch):
    for key in list(monkeypatch.__class__.__init__.__defaults__ or []):
        pass  # no-op; just to keep monkeypatch in scope
    # Clear any env that might bleed in from the shell.
    for key in [
        "ODIN_PROMOTER_ENABLED",
        "ODIN_PROMOTER_FIRMS_ENABLED",
        "ODIN_PROMOTER_FIRMS_MIN_HITS",
        "ODIN_PROMOTER_SEVERITY_ENABLED",
        "ODIN_PROMOTER_GDELT_ENABLED",
        "ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED",
        "ODIN_PROMOTER_QUIET_WINDOW_SEC",
    ]:
        monkeypatch.delenv(key, raising=False)
    cfg = PromoterConfig.from_env()
    assert cfg.enabled is True
    assert cfg.firms_enabled is True
    assert cfg.firms_min_hits == 3
    assert cfg.firms_window_sec == 86_400
    assert cfg.firms_bucket_deg == 0.1
    assert cfg.severity_enabled is False  # default-off in v1
    assert cfg.gdelt_enabled is False  # default-off in v1
    assert cfg.telegram_enabled is True
    assert cfg.telegram_embeddings_enabled is False
    assert cfg.telegram_jaccard_threshold == 0.55
    assert cfg.quiet_window_sec == 900
    assert cfg.sweeper_tick_sec == 60
    assert cfg.silence_cooldown_sec == 3600


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_FIRMS_MIN_HITS", "7")
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    monkeypatch.setenv("ODIN_PROMOTER_QUIET_WINDOW_SEC", "120")
    cfg = PromoterConfig.from_env()
    assert cfg.firms_min_hits == 7
    assert cfg.severity_enabled is True
    assert cfg.quiet_window_sec == 120


def test_enabled_detector_ids(monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    monkeypatch.setenv("ODIN_PROMOTER_GDELT_ENABLED", "false")
    cfg = PromoterConfig.from_env()
    assert set(cfg.enabled_detector_ids()) == {"firms", "severity", "telegram"}
```

- [ ] **Step 2: Run the test and confirm it fails.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.incident_promoter.config'`.

- [ ] **Step 3: Implement `PromoterConfig` (pydantic-settings, matches `app/config.py` style).**

`services/backend/app/services/incident_promoter/config.py`:
```python
"""Env-driven config for the auto-promoter.

All values come from environment variables (prefix ``ODIN_PROMOTER_``). The
config is read once at lifespan-start via :meth:`PromoterConfig.from_env`;
the resulting instance is immutable for the lifetime of the Promoter task.
Uses ``pydantic_settings.BaseSettings`` to match ``app.config.Settings``.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class PromoterConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ODIN_PROMOTER_",
        extra="ignore",
        frozen=True,
    )

    enabled: bool = True
    firms_enabled: bool = True
    firms_min_hits: int = 3
    firms_window_sec: int = 86_400
    firms_bucket_deg: float = 0.1
    severity_enabled: bool = False
    severity_min_hits: int = 5
    severity_window_sec: int = 900
    telegram_enabled: bool = True
    telegram_min_hits: int = 3
    telegram_window_sec: int = 1800
    telegram_jaccard_threshold: float = 0.55
    telegram_jaccard_threshold_domain: float = 0.45
    telegram_embeddings_enabled: bool = False
    gdelt_enabled: bool = False
    gdelt_min_hits: int = 3
    gdelt_window_sec: int = 3600
    quiet_window_sec: int = 900
    sweeper_tick_sec: int = 60
    silence_cooldown_sec: int = 3600

    @classmethod
    def from_env(cls) -> "PromoterConfig":
        """Convenience alias for call sites that want to read env explicitly."""
        return cls()

    def enabled_detector_ids(self) -> list[str]:
        ids: list[str] = []
        if self.firms_enabled:
            ids.append("firms")
        if self.severity_enabled:
            ids.append("severity")
        if self.telegram_enabled:
            ids.append("telegram")
        if self.gdelt_enabled:
            ids.append("gdelt")
        return ids
```

Note: `pydantic_settings` ships as a transitive of `pydantic-settings` (already in the backend deps — used by `app/config.py`). No new dependency required.

- [ ] **Step 4: Run the tests and confirm they pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_config.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/config.py services/backend/tests/incident_promoter/test_config.py
git commit -m "feat(promoter): add env-driven PromoterConfig"
```

---

### Task 1.3: `Detector` protocol, `ClusterHit`, build helpers

**Files:**
- Create: `services/backend/app/services/incident_promoter/detectors/base.py`
- Create: `services/backend/tests/incident_promoter/detectors/test_base.py`

- [ ] **Step 1: Write the failing test.**

`services/backend/tests/incident_promoter/detectors/test_base.py`:
```python
"""Unit tests for detector base types and timeline build helpers."""
from app.models.incident import IncidentTimelineEvent
from app.services.incident_promoter.detectors.base import (
    ClusterHit,
    build_ignition_timeline_event,
    build_update_timeline_event,
)


def _hit(**overrides) -> ClusterHit:
    defaults: dict = {
        "cluster_key": "firms:geo:48.0:37.8",
        "detector_id": "firms",
        "incident_kind": "firms.cluster",
        "title": "FIRMS cluster ignited · 3 detections in firms:geo:48.0:37.8",
        "severity": "high",
        "coords": (48.0, 37.8),
        "location": "Test bucket",
        "sources_to_merge": ["FIRMS · VIIRS_SNPP_NRT"],
        "layer_hints_to_merge": ["firms", "events", "auto_promoter:v1",
                                 "cluster:firms:geo:48.0:37.8"],
        "timeline_event": IncidentTimelineEvent(
            t_offset_s=0.0, kind="trigger", text="seed", severity="high"
        ),
        "contributing_signal_ids": ["a", "b", "c"],
    }
    defaults.update(overrides)
    return ClusterHit(**defaults)


def test_cluster_hit_is_frozen():
    h = _hit()
    import dataclasses
    assert dataclasses.is_dataclass(h)
    try:
        h.title = "mutated"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ClusterHit must be frozen")


def test_build_ignition_timeline_event_uses_hit_title_and_severity():
    h = _hit()
    ev = build_ignition_timeline_event(h)
    assert ev.t_offset_s == 0.0
    assert ev.kind == "trigger"
    assert ev.text == h.title
    assert ev.severity == h.severity


def test_build_update_timeline_event_uses_hit_title_and_offset():
    h = _hit()
    ev = build_update_timeline_event(h, t_offset_s=180.0)
    assert ev.t_offset_s == 180.0
    assert ev.kind == "observation"
    assert ev.text == h.title
    assert ev.severity == h.severity
```

- [ ] **Step 2: Run the test and confirm it fails.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_base.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.incident_promoter.detectors.base'`.

- [ ] **Step 3: Implement `base.py`.**

`services/backend/app/services/incident_promoter/detectors/base.py`:
```python
"""Detector protocol and shared dataclasses.

Detectors observe :class:`SignalEnvelope`s and emit a :class:`ClusterHit`
only when an action is required on the ``ClusterStore`` (an ignition or
an update against an already-ignited cluster). All threshold logic lives
inside detectors; the store decides only "create vs. update vs. drop".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models.incident import IncidentTimelineEvent
from app.models.signals import SignalEnvelope


@dataclass(frozen=True)
class ClusterHit:
    """Actionable detector output. See §4.1 of the design spec."""

    cluster_key: str
    detector_id: str
    incident_kind: str
    title: str
    severity: str  # Severity literal
    coords: tuple[float, float] | None
    location: str
    sources_to_merge: list[str]
    layer_hints_to_merge: list[str]
    timeline_event: IncidentTimelineEvent
    contributing_signal_ids: list[str]


class Detector(Protocol):
    """Behavioural protocol for all detectors.

    Concrete detectors keep per-bucket state internally and never mutate
    ``ClusterStore`` or Neo4j. ``detect`` returns ``None`` for signals that
    do not yet qualify (pre-trigger accumulation) or that fall inside a
    suppression cooldown for their cluster key.
    """

    id: str
    enabled: bool

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None: ...

    def on_cluster_terminated(
        self,
        cluster_key: str,
        suppress_until: datetime | None = None,
    ) -> None: ...


def build_ignition_timeline_event(hit: ClusterHit) -> IncidentTimelineEvent:
    """Trigger event for ``create_incident`` — exactly one entry."""
    return IncidentTimelineEvent(
        t_offset_s=0.0,
        kind="trigger",
        text=hit.title,
        severity=hit.severity,  # type: ignore[arg-type]
    )


def build_update_timeline_event(
    hit: ClusterHit, *, t_offset_s: float
) -> IncidentTimelineEvent:
    """One timeline entry appended via ``apply_signal_update``."""
    return IncidentTimelineEvent(
        t_offset_s=t_offset_s,
        kind="observation",
        text=hit.title,
        severity=hit.severity,  # type: ignore[arg-type]
    )
```

- [ ] **Step 4: Run the test and confirm it passes.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_base.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/base.py services/backend/tests/incident_promoter/detectors/test_base.py
git commit -m "feat(promoter): add Detector protocol, ClusterHit, timeline build helpers"
```

---

### Task 1.4: Test fixtures — FakeClock, FakeIncidentStore, FakeIncidentEventStream

**Files:**
- Create: `services/backend/tests/incident_promoter/conftest.py`

- [ ] **Step 1: Implement the fixtures.**

`services/backend/tests/incident_promoter/conftest.py`:
```python
"""Shared fixtures for incident_promoter tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.models.incident import (
    Incident,
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.models.signals import SignalEnvelope, SignalPayload


class FakeClock:
    """Mutable clock for deterministic tests. Call ``advance`` to move time."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)

    def set(self, ts: datetime) -> None:
        self._now = ts


class FakeIncidentStore:
    """In-process incident store with the methods used by the Promoter."""

    def __init__(self) -> None:
        self._by_id: dict[str, Incident] = {}

    async def create_incident(self, req: IncidentCreateRequest) -> Incident:
        incident_id = f"inc-{uuid4().hex[:8]}"
        initial = IncidentTimelineEvent(
            t_offset_s=0.0,
            kind="trigger",
            text=req.initial_text or f"trigger · {req.kind}",
            severity=req.severity,
        )
        record = Incident(
            id=incident_id,
            kind=req.kind,
            title=req.title,
            severity=req.severity,
            coords=req.coords,
            location=req.location,
            status=IncidentStatus.OPEN,
            trigger_ts=datetime.now(UTC),
            sources=list(req.sources),
            layer_hints=list(req.layer_hints),
            timeline=[initial],
        )
        self._by_id[incident_id] = record
        return record

    async def apply_signal_update(
        self,
        incident_id: str,
        *,
        timeline_event: IncidentTimelineEvent,
        severity: str,
        sources_to_merge: list[str],
        layer_hints_to_merge: list[str],
    ) -> Incident | None:
        current = self._by_id.get(incident_id)
        if current is None:
            return None
        merged_sources = list(dict.fromkeys([*current.sources, *sources_to_merge]))
        merged_hints = list(dict.fromkeys([*current.layer_hints, *layer_hints_to_merge]))
        next_record = current.model_copy(
            update={
                "timeline": [*current.timeline, timeline_event],
                "severity": severity,  # type: ignore[arg-type]
                "sources": merged_sources,
                "layer_hints": merged_hints,
            }
        )
        self._by_id[incident_id] = next_record
        return next_record

    async def close_incident(
        self,
        incident_id: str,
        status: IncidentStatus,
        when: datetime | None = None,
    ) -> Incident | None:
        current = self._by_id.get(incident_id)
        if current is None:
            return None
        if current.status != IncidentStatus.OPEN:
            return current  # idempotent
        next_record = current.model_copy(
            update={"status": status, "closed_ts": when or datetime.now(UTC)}
        )
        self._by_id[incident_id] = next_record
        return next_record

    async def list_owned_for_rehydrate(self) -> list[Incident]:
        return [
            i
            for i in self._by_id.values()
            if i.status in (IncidentStatus.OPEN, IncidentStatus.PROMOTED)
            and "auto_promoter:v1" in i.layer_hints
        ]

    # Test helpers — direct read access
    def get(self, incident_id: str) -> Incident | None:
        return self._by_id.get(incident_id)

    def all(self) -> list[Incident]:
        return list(self._by_id.values())


class FakeIncidentEventStream:
    """Collecting stub for the SSE event stream."""

    def __init__(self) -> None:
        self.published: list[tuple[str, Incident]] = []

    def publish(self, type_: str, incident: Incident) -> None:
        self.published.append((type_, incident))

    def types(self) -> list[str]:
        return [t for t, _ in self.published]


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_incident_store() -> FakeIncidentStore:
    return FakeIncidentStore()


@pytest.fixture
def fake_incident_event_stream() -> FakeIncidentEventStream:
    return FakeIncidentEventStream()


@pytest.fixture
def signal_envelope_factory():
    counter = {"i": 0}

    def make(
        *,
        source: str = "firms",
        title: str = "Thermal anomaly detected",
        severity: str = "low",
        url: str = "",
        ts: datetime | None = None,
        codebook_type: str = "other.unclassified",
        extras: dict[str, Any] | None = None,
    ) -> SignalEnvelope:
        counter["i"] += 1
        ms = int((ts or datetime.now(UTC)).timestamp() * 1000)
        seq = counter["i"]
        event_id = f"{ms:013d}-{seq:06d}"
        record_id = f"{ms}-{seq}"
        payload_kwargs = {
            "title": title,
            "severity": severity,
            "source": source,
            "url": url,
            "redis_id": record_id,
        }
        if extras:
            payload_kwargs.update(extras)
        return SignalEnvelope(
            event_id=event_id,
            ts=(ts or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            type=codebook_type,
            payload=SignalPayload(**payload_kwargs),
        )

    return make
```

- [ ] **Step 2: Run a smoke import to make sure fixtures load.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/ -v --collect-only 2>&1 | head -20
```
Expected: collection succeeds (no `ImportError`, no `pytest` warnings about unknown fixtures).

- [ ] **Step 3: Commit.**
```bash
git add services/backend/tests/incident_promoter/conftest.py
git commit -m "test(promoter): add fake clock/store/stream + signal envelope factory"
```

---
### Task 1.5: `ClusterState` + `ClusterStore` skeleton (data only)

This task defines the in-memory state but **not** behavior; `handle()`, `mark_promoted`, `mark_silenced`, and the sweeper logic are added in Phase 4 once the FIRMS detector exists to drive them.

**Files:**
- Create: `services/backend/app/services/incident_promoter/cluster_store.py`

- [ ] **Step 1: Write a structural smoke test.**

Append to `services/backend/tests/incident_promoter/test_cluster_store.py` (create file):
```python
"""Structural tests for ClusterStore (data + listener registration only)."""
from datetime import UTC, datetime, timedelta

from app.services.incident_promoter.cluster_store import (
    ClusterState,
    ClusterStore,
)


def test_cluster_store_starts_empty(fake_clock):
    store = ClusterStore(clock=fake_clock)
    assert store.active_clusters() == []
    assert store.cooldowns() == {}
    assert store.is_empty() is True


def test_add_termination_listener_collects_callbacks(fake_clock):
    store = ClusterStore(clock=fake_clock)
    received: list[tuple[str, object]] = []

    def listener(key: str, suppress_until=None):
        received.append((key, suppress_until))

    store.add_termination_listener(listener)
    # listener is registered but not invoked yet
    assert received == []
    assert len(store._termination_listeners) == 1  # noqa: SLF001 — internal check


def test_cluster_state_is_dataclass_with_required_fields():
    s = ClusterState(
        cluster_key="firms:geo:48.0:37.8",
        incident_id="inc-1",
        detector_id="firms",
        severity="high",
        coords=(48.0, 37.8),
        hit_count=3,
        last_signal_ts=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
        created_ts=datetime(2026, 5, 19, 11, 50, tzinfo=UTC),
        contributing_signal_ids=["a", "b", "c"],
        incident_status="open",
    )
    assert s.hit_count == 3
    # cooldown is tracked in ClusterStore._cooldowns, NOT here
    assert not hasattr(s, "silenced_until")
```

- [ ] **Step 2: Run and confirm failure (module missing).**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_cluster_store.py -v
```

- [ ] **Step 3: Implement the skeleton.**

`services/backend/app/services/incident_promoter/cluster_store.py`:
```python
"""In-memory cluster lifecycle store for the auto-promoter.

Phase 1 deliverable: data structures and listener registration only.
``handle()``, ``mark_promoted``, ``mark_silenced``, and the sweeper hooks
are added in Phase 4 alongside the FIRMS detector that drives them.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

ClusterIncidentStatus = Literal["open", "promoted"]
TerminationListener = Callable[..., None]
"""Signature: ``listener(cluster_key: str, suppress_until: datetime | None = None) -> None``."""


@dataclass
class ClusterState:
    cluster_key: str
    incident_id: str
    detector_id: str
    severity: str
    coords: tuple[float, float]
    hit_count: int
    last_signal_ts: datetime
    created_ts: datetime
    contributing_signal_ids: list[str] = field(default_factory=list)
    incident_status: ClusterIncidentStatus = "open"


class ClusterStore:
    """In-memory cluster lifecycle. All mutations are guarded by an asyncio lock."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._by_key: dict[str, ClusterState] = {}
        self._by_incident_id: dict[str, str] = {}
        self._reserving: set[str] = set()
        self._cooldowns: dict[str, datetime] = {}
        self._termination_listeners: list[TerminationListener] = []
        self._lock = asyncio.Lock()

    # -- registration ----------------------------------------------------

    def add_termination_listener(self, listener: TerminationListener) -> None:
        """Detectors register here at Promoter init (before any signal arrives)."""
        self._termination_listeners.append(listener)

    # -- read-only snapshots ---------------------------------------------

    def is_empty(self) -> bool:
        return not self._by_key and not self._cooldowns and not self._reserving

    def active_clusters(self) -> list[ClusterState]:
        """Snapshot copy — safe to read without the lock for inspector / debug."""
        return list(self._by_key.values())

    def cooldowns(self) -> dict[str, datetime]:
        return dict(self._cooldowns)

    def get_by_incident_id(self, incident_id: str) -> ClusterState | None:
        cluster_key = self._by_incident_id.get(incident_id)
        if cluster_key is None:
            return None
        return self._by_key.get(cluster_key)
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_cluster_store.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/cluster_store.py services/backend/tests/incident_promoter/test_cluster_store.py
git commit -m "feat(promoter): add ClusterState + ClusterStore skeleton"
```

---

### Task 1.6: `Promoter` shell (no-op `run`, lifecycle hooks only)

**Files:**
- Create: `services/backend/app/services/incident_promoter/promoter.py`

- [ ] **Step 1: Write the failing test.**

`services/backend/tests/incident_promoter/test_promoter.py`:
```python
"""Promoter shell — startup/shutdown and config gating."""
import asyncio

import pytest

from app.services.incident_promoter.cluster_store import ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.promoter import Promoter


@pytest.fixture
def disabled_config() -> PromoterConfig:
    return PromoterConfig.from_env().__class__(
        **{**PromoterConfig.from_env().__dict__, "enabled": False}
    )


async def test_promoter_request_stop_is_idempotent(fake_clock, disabled_config,
                                                   fake_incident_store,
                                                   fake_incident_event_stream):
    promoter = Promoter(
        signal_stream=None,                       # not used while disabled
        cluster_store=ClusterStore(clock=fake_clock),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=disabled_config,
        clock=fake_clock,
        detectors=[],
    )
    promoter.request_stop()
    promoter.request_stop()    # no exception
    assert promoter.is_stop_requested() is True


async def test_promoter_run_exits_promptly_when_disabled(fake_clock, disabled_config,
                                                        fake_incident_store,
                                                        fake_incident_event_stream):
    promoter = Promoter(
        signal_stream=None,
        cluster_store=ClusterStore(clock=fake_clock),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=disabled_config,
        clock=fake_clock,
        detectors=[],
    )
    # When disabled, run() should return without subscribing or draining.
    await asyncio.wait_for(promoter.run(), timeout=0.5)
```

- [ ] **Step 2: Run and confirm failure (module missing).**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_promoter.py -v
```

- [ ] **Step 3: Implement the shell.**

`services/backend/app/services/incident_promoter/promoter.py`:
```python
"""Auto-promoter — FastAPI lifespan task.

Phase 1 deliverable: lifecycle scaffolding only (run / stop / sweeper-loop
placeholders). The drain loop and sweeper logic are wired up in Phase 4.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime

import structlog

from app.services.incident_promoter.cluster_store import ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import Detector

logger = structlog.get_logger(__name__)


class Promoter:
    """Single owner of the signal→incident pipeline."""

    def __init__(
        self,
        *,
        signal_stream,                         # SignalStream | None
        cluster_store: ClusterStore,
        incident_store,                        # object with create/apply/close/list_owned
        incident_event_stream,                 # object with publish(type_, incident)
        config: PromoterConfig,
        clock: Callable[[], datetime],
        detectors: Sequence[Detector],
    ) -> None:
        self._signal_stream = signal_stream
        self._cluster_store = cluster_store
        self._incident_store = incident_store
        self._incident_event_stream = incident_event_stream
        self._config = config
        self._clock = clock
        self._detectors: list[Detector] = list(detectors)
        self._stop_event = asyncio.Event()
        self._subscribed_queue: asyncio.Queue | None = None

    # -- lifecycle -------------------------------------------------------

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def _has_runtime_deps(self) -> bool:
        """True only when both the signal stream and incident store are wired.

        Lifespan calls this before scheduling ``run`` / ``sweeper_loop``;
        ``run`` and ``sweeper_loop`` themselves re-check and bail with a
        warning so a misconfigured caller can't trigger a busy spin.
        """
        return self._signal_stream is not None and self._incident_store is not None

    async def run(self) -> None:
        """Phase 1 placeholder — no-op when disabled, real logic in Phase 4."""
        if not self._config.enabled:
            logger.info("promoter_disabled_skipping_run")
            return
        if not self._has_runtime_deps():
            logger.warning(
                "promoter_run_missing_runtime_deps_skipping",
                has_signal_stream=self._signal_stream is not None,
                has_incident_store=self._incident_store is not None,
            )
            return
        # Phase 4 implementation will:
        #   await self._subscribe()
        #   await self._rehydrate()
        #   await self._drain_loop()
        logger.warning("promoter_run_not_implemented_phase1")

    async def sweeper_loop(self) -> None:
        """Phase 1 placeholder — real implementation in Phase 4."""
        if not self._config.enabled:
            return
        if not self._has_runtime_deps():
            return
        logger.warning("promoter_sweeper_not_implemented_phase1")
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_promoter.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/promoter.py services/backend/tests/incident_promoter/test_promoter.py
git commit -m "feat(promoter): add Promoter shell (config-gated no-op)"
```

---

### Task 1.7: Lifespan wiring + global `conftest.py` patch

**Files:**
- Modify: `services/backend/app/main.py`
- Modify: `services/backend/tests/conftest.py`

- [ ] **Step 1: Update global `conftest.py` so router tests keep working.**

Edit `services/backend/tests/conftest.py` to set `cluster_store = None` on app.state alongside the existing dummies:
```python
"""Shared test fixtures and app state setup."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import app


@pytest.fixture(autouse=True)
def set_app_state() -> None:
    """Set dummy app state so routers that access request.app.state don't raise AttributeError."""
    app.state.proxy = MagicMock()
    app.state.cache = AsyncMock()
    app.state.cluster_store = None  # router code uses getattr(..., None); explicit for clarity
```

- [ ] **Step 2: Wire the lifespan.**

In `services/backend/app/main.py`, locate the `@asynccontextmanager async def lifespan(app)` function (around line 60 per the project layout). Inside it, after the existing signal-stream consumer task is created and **before** the `yield`, insert:

```python
    # --- Auto-promoter (Phase 1 wiring — shell only) ---
    from datetime import UTC, datetime as _dt
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.promoter import Promoter

    _promoter_clock = lambda: _dt.now(UTC)
    _promoter_cfg = PromoterConfig.from_env()
    _cluster_store = ClusterStore(clock=_promoter_clock)
    app.state.cluster_store = _cluster_store
    app.state.promoter_config = _promoter_cfg

    _promoter = Promoter(
        signal_stream=None,  # Phase 4 wires the real SignalStream
        cluster_store=_cluster_store,
        incident_store=None,  # Phase 4 wires incident_store module
        incident_event_stream=None,  # Phase 4 wires get_incident_stream()
        config=_promoter_cfg,
        clock=_promoter_clock,
        detectors=[],  # Phase 3+ adds detectors
    )
    # Phase 1 deliberately does NOT start the promoter/sweeper tasks. The
    # Promoter shell would otherwise busy-loop because signal_stream is None
    # and _drain_one() returns immediately. Real task creation lives in
    # Task 4.7, after Phase 4 wires the SignalStream and detector(s).
    _promoter_task: asyncio.Task | None = None
    _sweeper_task: asyncio.Task | None = None
```

And in the `finally:` block of the same lifespan, before the existing teardown statements:
```python
        _promoter.request_stop()
        for _t in (_promoter_task, _sweeper_task):
            if _t is None:
                continue
            _t.cancel()
            import contextlib as _ctx
            with _ctx.suppress(asyncio.CancelledError, Exception):
                await _t
```

(If `asyncio` and `contextlib` are not yet imported at the top of `main.py`, add them.)

- [ ] **Step 3: Verify backend boots and tests still pass.**
```bash
cd services/backend && uv run pytest -q
```
Expected: all tests pass (existing tests + 8 new in `tests/incident_promoter/`).

Quick boot smoke:
```bash
cd services/backend && uv run python -c "from app.main import app; print('ok')"
```
Expected: `ok` printed, exit 0.

- [ ] **Step 4: Commit.**
```bash
git add services/backend/app/main.py services/backend/tests/conftest.py
git commit -m "feat(promoter): wire ClusterStore + Promoter shell into lifespan"
```

---
## Phase 2 — `incident_store` changes

Goal: add the two new methods the Promoter needs and make `close_incident` idempotent. End of phase: all existing incident-store tests still pass; three new tests pass.

### Task 2.1: Make `close_incident` idempotent

**Files:**
- Modify: `services/backend/app/services/incident_store.py` (function around lines 152–167)
- Modify: `services/backend/tests/test_incident_store.py`

- [ ] **Step 1: Write the failing test (idempotency).**

Append to `services/backend/tests/test_incident_store.py`:
```python
async def test_close_incident_is_idempotent_on_terminal_status(
    neo4j_test_session,  # existing fixture
):
    from app.models.incident import IncidentCreateRequest, IncidentStatus
    from app.services import incident_store

    req = IncidentCreateRequest(
        title="Idempotency probe",
        kind="manual",
        severity="elevated",
        coords=(10.0, 10.0),
        layer_hints=["auto_promoter:v1", "cluster:test:idempotency"],
    )
    created = await incident_store.create_incident(req)
    closed = await incident_store.close_incident(created.id, IncidentStatus.CLOSED)
    assert closed is not None and closed.status == IncidentStatus.CLOSED
    first_closed_ts = closed.closed_ts

    # second close is a no-op — same record, same closed_ts
    again = await incident_store.close_incident(created.id, IncidentStatus.CLOSED)
    assert again is not None
    assert again.status == IncidentStatus.CLOSED
    assert again.closed_ts == first_closed_ts


async def test_close_incident_does_not_overwrite_promoted_status(neo4j_test_session):
    from app.models.incident import IncidentCreateRequest, IncidentStatus
    from app.services import incident_store

    req = IncidentCreateRequest(
        title="Promoted then closed",
        kind="manual",
        severity="elevated",
        coords=(10.0, 10.0),
        layer_hints=["auto_promoter:v1", "cluster:test:promoted"],
    )
    created = await incident_store.create_incident(req)
    promoted = await incident_store.close_incident(created.id, IncidentStatus.PROMOTED)
    assert promoted is not None and promoted.status == IncidentStatus.PROMOTED

    # Sweeper would call close(... CLOSED) on a non-open record — must be a no-op.
    result = await incident_store.close_incident(created.id, IncidentStatus.CLOSED)
    assert result is not None
    assert result.status == IncidentStatus.PROMOTED  # unchanged
```

> If `neo4j_test_session` does not exist as a fixture, replicate the setup used by the existing tests in this file (mock or live Neo4j as established).

- [ ] **Step 2: Run and confirm failure.**
```bash
cd services/backend && uv run pytest tests/test_incident_store.py::test_close_incident_is_idempotent_on_terminal_status tests/test_incident_store.py::test_close_incident_does_not_overwrite_promoted_status -v
```
Expected: failure (current implementation overwrites status on every call).

- [ ] **Step 3: Implement idempotency.**

In `services/backend/app/services/incident_store.py`, replace the body of `close_incident`:
```python
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
    rows = await write_query(INCIDENT_UPSERT, _upsert_params(next_record, ordinal))
    if not rows:
        return None
    return _row_to_incident(rows[0])
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/test_incident_store.py -v
```
Expected: all incident-store tests pass (existing + 2 new).

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_store.py services/backend/tests/test_incident_store.py
git commit -m "feat(incident-store): make close_incident idempotent on terminal status"
```

---

### Task 2.2: Add `apply_signal_update`

**Files:**
- Modify: `services/backend/app/services/incident_store.py`
- Modify: `services/backend/tests/test_incident_store.py`

- [ ] **Step 1: Write the failing test.**

Append to `services/backend/tests/test_incident_store.py`:
```python
async def test_apply_signal_update_appends_timeline_and_merges_severity_and_sources(
    neo4j_test_session,
):
    from app.models.incident import (
        IncidentCreateRequest,
        IncidentTimelineEvent,
    )
    from app.services import incident_store

    req = IncidentCreateRequest(
        title="FIRMS cluster ignited · 3 detections in firms:geo:48.0:37.8",
        kind="firms.cluster",
        severity="elevated",
        coords=(48.0, 37.8),
        sources=["FIRMS · VIIRS_SNPP_NRT"],
        layer_hints=["firms", "events", "auto_promoter:v1",
                     "cluster:firms:geo:48.0:37.8"],
        initial_text="FIRMS cluster ignited · 3 detections in firms:geo:48.0:37.8",
    )
    created = await incident_store.create_incident(req)
    assert created.severity == "elevated"
    assert len(created.timeline) == 1

    event = IncidentTimelineEvent(
        t_offset_s=120.0,
        kind="observation",
        text="FIRMS hit · t+2m",
        severity="high",
    )
    updated = await incident_store.apply_signal_update(
        created.id,
        timeline_event=event,
        severity="high",  # escalation
        sources_to_merge=["FIRMS · VIIRS_SNPP_NRT", "Telegram · OSINTdefender"],
        layer_hints_to_merge=["firms", "telegram"],
    )
    assert updated is not None
    assert updated.severity == "high"
    assert len(updated.timeline) == 2
    assert updated.timeline[-1].text == "FIRMS hit · t+2m"
    # merge is deduplicating
    assert updated.sources.count("FIRMS · VIIRS_SNPP_NRT") == 1
    assert "Telegram · OSINTdefender" in updated.sources
    assert "telegram" in updated.layer_hints


async def test_apply_signal_update_missing_incident_returns_none(neo4j_test_session):
    from app.models.incident import IncidentTimelineEvent
    from app.services import incident_store

    result = await incident_store.apply_signal_update(
        "inc-does-not-exist",
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="observation"),
        severity="low",
        sources_to_merge=[],
        layer_hints_to_merge=[],
    )
    assert result is None
```

- [ ] **Step 2: Run and confirm failure (missing function).**
```bash
cd services/backend && uv run pytest tests/test_incident_store.py::test_apply_signal_update_appends_timeline_and_merges_severity_and_sources -v
```

- [ ] **Step 3: Implement `apply_signal_update`.**

Append to `services/backend/app/services/incident_store.py` after `append_timeline_event`:
```python
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
    rows = await write_query(INCIDENT_UPSERT, _upsert_params(next_record, ordinal))
    if not rows:
        return None
    return _row_to_incident(rows[0])
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/test_incident_store.py -v
```
Expected: all incident-store tests pass.

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_store.py services/backend/tests/test_incident_store.py
git commit -m "feat(incident-store): add atomic apply_signal_update"
```

---

### Task 2.3: Add `list_owned_for_rehydrate`

**Files:**
- Modify: `services/backend/app/services/incident_store.py`
- Modify: `services/backend/tests/test_incident_store.py`

- [ ] **Step 1: Write the failing test.**

Append:
```python
async def test_list_owned_for_rehydrate_filters_by_marker_and_status(neo4j_test_session):
    from app.models.incident import IncidentCreateRequest, IncidentStatus
    from app.services import incident_store

    owned_open = await incident_store.create_incident(
        IncidentCreateRequest(
            title="Owned open",
            kind="firms.cluster",
            severity="high",
            coords=(1.0, 1.0),
            layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:1.0:1.0"],
        )
    )
    owned_promoted_id = (
        await incident_store.create_incident(
            IncidentCreateRequest(
                title="Owned then promoted",
                kind="firms.cluster",
                severity="high",
                coords=(2.0, 2.0),
                layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:2.0:2.0"],
            )
        )
    ).id
    await incident_store.close_incident(owned_promoted_id, IncidentStatus.PROMOTED)

    manual_open = await incident_store.create_incident(
        IncidentCreateRequest(
            title="Manual",
            kind="manual",
            severity="elevated",
            coords=(3.0, 3.0),
            layer_hints=["manual"],
        )
    )

    rehydrate = await incident_store.list_owned_for_rehydrate()
    ids = {i.id for i in rehydrate}
    assert owned_open.id in ids
    assert owned_promoted_id in ids
    assert manual_open.id not in ids  # no auto_promoter:v1 marker
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement.**

Append to `services/backend/app/services/incident_store.py`:
```python
async def list_owned_for_rehydrate() -> list[Incident]:
    """Return open/promoted incidents owned by the auto-promoter.

    Uses the existing ``INCIDENT_LIST_OPEN`` Cypher then filters in Python by
    the ``auto_promoter:v1`` marker in ``layer_hints``. Status filter also
    admits ``PROMOTED`` so the Promoter can rehydrate clusters that the
    analyst owned at restart time.
    """
    # We need both OPEN and PROMOTED, but list_open_incidents() returns only
    # OPEN. Use a small ad-hoc query that mirrors INCIDENT_LIST_OPEN but
    # without the status filter, then filter both axes in Python.
    rows = await read_query(
        "MATCH (i:Incident) "
        "WHERE i.status IN ['open', 'promoted'] "
        "RETURN i.id AS id, i.kind AS kind, i.title AS title, "
        "       i.severity AS severity, i.lat AS lat, i.lon AS lon, "
        "       i.location AS location, i.status AS status, "
        "       toString(i.trigger_ts) AS trigger_ts, "
        "       toString(i.closed_ts) AS closed_ts, "
        "       i.sources AS sources, i.layer_hints AS layer_hints, "
        "       i.timeline_json AS timeline_json "
        "ORDER BY i.ordinal DESC LIMIT 500"
    )
    owned: list[Incident] = []
    for row in rows:
        if "auto_promoter:v1" not in (row.get("layer_hints") or []):
            continue
        owned.append(_row_to_incident(row))
    return owned
```

> If `read_query` is not already imported at the top of the file, add it from `app.services.neo4j_client`.

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/test_incident_store.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_store.py services/backend/tests/test_incident_store.py
git commit -m "feat(incident-store): add list_owned_for_rehydrate for auto-promoter"
```

---
## Phase 3 — FIRMS Geo-Cluster Detector

Goal: a working detector with full unit-test coverage of pre-trigger, ignition, update, termination reset, and silence suppression. ClusterStore.handle() doesn't exist yet — this phase tests the detector in isolation.

### Task 3.1: FIRMS URL coord parser + bucket key

**Files:**
- Create: `services/backend/app/services/incident_promoter/detectors/firms.py`
- Create: `services/backend/tests/incident_promoter/detectors/test_firms.py`

- [ ] **Step 1: Write the failing tests (helpers only).**

`services/backend/tests/incident_promoter/detectors/test_firms.py`:
```python
"""Unit tests for FIRMSGeoClusterDetector helpers."""
import pytest

from app.services.incident_promoter.detectors.firms import (
    _bucket_key,
    _parse_firms_coords,
)


def test_parse_firms_coords_happy():
    url = "https://firms.modaps.eosdis.nasa.gov/map/#d:2026-05-19;@35.0903,51.6177,10z"
    assert _parse_firms_coords(url) == (35.0903, 51.6177)


def test_parse_firms_coords_negative():
    url = "https://firms.example/#d:2026-05-19;@-22.5,-44.1,8z"
    assert _parse_firms_coords(url) == (-22.5, -44.1)


@pytest.mark.parametrize("url", ["", "no-pattern-here", "@bad,format", None])
def test_parse_firms_coords_returns_none_on_malformed(url):
    assert _parse_firms_coords(url) is None


def test_bucket_key_rounds_to_one_decimal():
    assert _bucket_key(48.012, 37.823, deg=0.1) == "firms:geo:48.0:37.8"


def test_bucket_key_handles_negative_lon():
    assert _bucket_key(48.0, -37.86, deg=0.1) == "firms:geo:48.0:-37.9"
```

- [ ] **Step 2: Run and confirm failure.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_firms.py -v
```

- [ ] **Step 3: Implement the helpers (no detector class yet — just the two functions the tests reach).**

`services/backend/app/services/incident_promoter/detectors/firms.py`:
```python
"""FIRMS Geo-Cluster Detector.

Watches FIRMS signals (``payload.source == "firms"``), buckets them by
rounded lat/lon, and ignites a cluster once ``firms_min_hits`` detections
accumulate inside the configured window.
"""
from __future__ import annotations

import re

_COORD_RE = re.compile(
    r"@(?P<lat>-?\d+(?:\.\d+)?),(?P<lon>-?\d+(?:\.\d+)?),"
)


def _parse_firms_coords(url: str | None) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` extracted from a FIRMS map URL, or ``None``."""
    if not url:
        return None
    match = _COORD_RE.search(url)
    if not match:
        return None
    try:
        return float(match.group("lat")), float(match.group("lon"))
    except ValueError:
        return None


def _bucket_key(lat: float, lon: float, *, deg: float) -> str:
    """Snap coords to a ``deg``-degree grid for cluster membership.

    Rounding uses ``round(x, 1)`` when ``deg == 0.1``; this matches the
    "~11 km cell" sizing described in the spec. For other ``deg`` values
    we fall back to integer-multiple rounding.
    """
    if deg == 0.1:
        lat_b = round(lat, 1)
        lon_b = round(lon, 1)
    else:
        lat_b = round(lat / deg) * deg
        lon_b = round(lon / deg) * deg
        # avoid -0.0 in keys
        lat_b = lat_b + 0.0
        lon_b = lon_b + 0.0
    return f"firms:geo:{lat_b:g}:{lon_b:g}"
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_firms.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/firms.py services/backend/tests/incident_promoter/detectors/test_firms.py
git commit -m "feat(promoter): add FIRMS URL parser and bucket-key helper"
```

---

### Task 3.2: FIRMS detector — pre-trigger accumulation (returns `None`)

**Files:**
- Modify: `services/backend/app/services/incident_promoter/detectors/firms.py`
- Modify: `services/backend/tests/incident_promoter/detectors/test_firms.py`

- [ ] **Step 1: Write the failing test.**

Append to `test_firms.py`:
```python
def _firms_envelope(signal_envelope_factory, lat=35.09, lon=51.62, **kw):
    url = kw.pop(
        "url",
        f"https://firms.modaps.eosdis.nasa.gov/map/#d:2026-05-19;@{lat},{lon},10z",
    )
    return signal_envelope_factory(source="firms", url=url, **kw)


def test_firms_detector_returns_none_before_threshold(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)

    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    # 2 signals accumulated, no emit yet
    assert det._buckets["firms:geo:35.1:51.6"].signals  # noqa: SLF001


def test_firms_detector_ignores_non_firms_source(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    env = signal_envelope_factory(
        source="rss",
        url="https://example.com/some-rss-item",
    )
    assert det.detect(env) is None
    assert not det._buckets  # noqa: SLF001


def test_firms_detector_ignores_malformed_url(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    env = signal_envelope_factory(source="firms", url="no-coords-here")
    assert det.detect(env) is None
    assert not det._buckets  # noqa: SLF001
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement the detector class with accumulation only.**

Append to `firms.py`:
```python
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import ClusterHit


@dataclass
class _BucketWindow:
    signals: deque = field(default_factory=deque)  # entries: (ts: datetime, event_id: str)
    ignited: bool = False


class FIRMSGeoClusterDetector:
    """Geo-cluster detector for FIRMS thermal detections."""

    id = "firms"

    def __init__(
        self,
        *,
        config: PromoterConfig,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._clock = clock
        self._buckets: dict[str, _BucketWindow] = {}
        self._suppressed_until: dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._config.firms_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        if (envelope.payload.source or "").lower() != "firms":
            return None
        coords = _parse_firms_coords(envelope.payload.url)
        if coords is None:
            return None
        cluster_key = _bucket_key(*coords, deg=self._config.firms_bucket_deg)
        # Phase 3.2: pure accumulation, no emit yet — emit logic in Task 3.3.
        bucket = self._buckets.setdefault(cluster_key, _BucketWindow())
        self._prune(bucket)
        bucket.signals.append((self._clock(), envelope.event_id))
        return None

    def _prune(self, bucket: _BucketWindow) -> None:
        cutoff = self._clock() - timedelta(seconds=self._config.firms_window_sec)
        while bucket.signals and bucket.signals[0][0] < cutoff:
            bucket.signals.popleft()
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_firms.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/firms.py services/backend/tests/incident_promoter/detectors/test_firms.py
git commit -m "feat(promoter): FIRMS detector pre-trigger accumulation"
```

---

### Task 3.3: FIRMS ignition emit (≥3 hits → `ClusterHit` with summary text)

**Files:**
- Modify: `firms.py` + `test_firms.py`

- [ ] **Step 1: Write the failing test.**

Append:
```python
def test_firms_detector_ignites_at_min_hits_with_summary_text(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()  # firms_min_hits=3 by default
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)

    env1 = _firms_envelope(signal_envelope_factory)
    env2 = _firms_envelope(signal_envelope_factory)
    env3 = _firms_envelope(signal_envelope_factory)

    assert det.detect(env1) is None
    assert det.detect(env2) is None
    hit = det.detect(env3)
    assert hit is not None
    assert hit.detector_id == "firms"
    assert hit.cluster_key == "firms:geo:35.1:51.6"
    assert hit.severity == "high"
    assert hit.coords == (35.09, 51.62)
    assert hit.incident_kind == "firms.cluster"
    assert "auto_promoter:v1" in hit.layer_hints_to_merge
    assert any(h.startswith("cluster:") for h in hit.layer_hints_to_merge)
    # Ignition summary text — single timeline entry referencing the count
    assert "3 detection" in hit.title.lower()
    assert hit.timeline_event.kind == "trigger"
    assert hit.timeline_event.text == hit.title
    assert len(hit.contributing_signal_ids) == 3
    assert hit.contributing_signal_ids[-1] == env3.event_id
    # Detector marks the bucket as ignited so the next signal is an update
    assert det._buckets[hit.cluster_key].ignited is True  # noqa: SLF001
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Replace the `detect` body in `firms.py`.**

```python
    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        if (envelope.payload.source or "").lower() != "firms":
            return None
        coords = _parse_firms_coords(envelope.payload.url)
        if coords is None:
            return None
        cluster_key = _bucket_key(*coords, deg=self._config.firms_bucket_deg)

        # Suppression first — Task 3.5 adds the body.
        suppress_until = self._suppressed_until.get(cluster_key)
        if suppress_until is not None:
            if self._clock() < suppress_until:
                return None
            self._suppressed_until.pop(cluster_key, None)

        bucket = self._buckets.setdefault(cluster_key, _BucketWindow())
        self._prune(bucket)
        bucket.signals.append((self._clock(), envelope.event_id))

        if bucket.ignited:
            return self._build_update_hit(envelope, cluster_key, coords)

        if len(bucket.signals) >= self._config.firms_min_hits:
            bucket.ignited = True
            return self._build_ignition_hit(envelope, cluster_key, coords, bucket)

        return None

    # -- builders -------------------------------------------------------

    def _build_ignition_hit(
        self,
        envelope: SignalEnvelope,
        cluster_key: str,
        coords: tuple[float, float],
        bucket: _BucketWindow,
    ) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_ignition_timeline_event,
        )

        count = len(bucket.signals)
        title = f"FIRMS cluster ignited · {count} detections in {cluster_key}"
        ids = [eid for _ts, eid in bucket.signals]
        hit = ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="firms.cluster",
            title=title,
            severity=self._initial_severity(),
            coords=coords,
            location="",
            sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
            layer_hints_to_merge=[
                "firms",
                "events",
                "auto_promoter:v1",
                f"cluster:{cluster_key}",
            ],
            timeline_event=build_ignition_timeline_event(
                # Build event from a temporary surrogate; we need title+severity.
                ClusterHit(
                    cluster_key=cluster_key,
                    detector_id=self.id,
                    incident_kind="firms.cluster",
                    title=title,
                    severity=self._initial_severity(),
                    coords=coords,
                    location="",
                    sources_to_merge=[],
                    layer_hints_to_merge=[],
                    timeline_event=None,  # type: ignore[arg-type]
                    contributing_signal_ids=[],
                )
            ),
            contributing_signal_ids=ids,
        )
        return hit

    def _build_update_hit(
        self,
        envelope: SignalEnvelope,
        cluster_key: str,
        coords: tuple[float, float],
    ) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_update_timeline_event,
        )

        title = f"FIRMS hit · {cluster_key}"
        # t_offset is filled in by ClusterStore relative to the incident's trigger_ts;
        # detector emits 0.0 as a sentinel that the store will overwrite.
        surrogate = ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="firms.cluster",
            title=title,
            severity="high",  # never escalates downward
            coords=coords,
            location="",
            sources_to_merge=[],
            layer_hints_to_merge=[],
            timeline_event=None,  # type: ignore[arg-type]
            contributing_signal_ids=[],
        )
        return ClusterHit(
            cluster_key=cluster_key,
            detector_id=self.id,
            incident_kind="firms.cluster",
            title=title,
            severity="high",
            coords=coords,
            location="",
            sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
            layer_hints_to_merge=[
                "firms",
                "events",
                "auto_promoter:v1",
                f"cluster:{cluster_key}",
            ],
            timeline_event=build_update_timeline_event(surrogate, t_offset_s=0.0),
            contributing_signal_ids=[envelope.event_id],
        )

    def _initial_severity(self) -> str:
        # FIRMS: high on open, escalates to critical at hit_count >= 10 — escalation
        # is applied in ClusterStore.apply_signal_update, not here.
        return "high"
```

> The double-surrogate construction is intentional: `build_*_timeline_event` reads `title` and `severity` from a `ClusterHit`, but the real `ClusterHit` needs the timeline event. A small surrogate avoids defining a third public helper. If a future detector author finds this awkward, refactor `build_*_timeline_event` to accept `(title, severity)` directly — but not in this plan.

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_firms.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/firms.py services/backend/tests/incident_promoter/detectors/test_firms.py
git commit -m "feat(promoter): FIRMS ignition emit with summary timeline"
```

---

### Task 3.4: FIRMS post-ignition update emit

**Files:**
- Modify: `test_firms.py`

The detect-body added in Task 3.3 already handles updates; this task just covers it with a focused test.

- [ ] **Step 1: Write the test.**

Append:
```python
def test_firms_detector_emits_update_after_ignition(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    for _ in range(3):
        det.detect(_firms_envelope(signal_envelope_factory))

    env4 = _firms_envelope(signal_envelope_factory)
    fake_clock.advance(60)
    hit = det.detect(env4)
    assert hit is not None
    assert hit.timeline_event.kind == "observation"
    assert hit.contributing_signal_ids == [env4.event_id]
    assert hit.severity == "high"  # detector itself never de-escalates
```

- [ ] **Step 2: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_firms.py::test_firms_detector_emits_update_after_ignition -v
```

- [ ] **Step 3: Commit.**
```bash
git add services/backend/tests/incident_promoter/detectors/test_firms.py
git commit -m "test(promoter): cover FIRMS post-ignition update emit"
```

---

### Task 3.5: FIRMS `on_cluster_terminated` — natural reset + silence suppression

**Files:**
- Modify: `firms.py` + `test_firms.py`

- [ ] **Step 1: Write the failing tests.**

Append:
```python
def test_firms_on_cluster_terminated_natural_reset_restarts_accumulation(
    signal_envelope_factory, fake_clock
):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    for _ in range(3):
        det.detect(_firms_envelope(signal_envelope_factory))
    # natural termination — no suppression
    det.on_cluster_terminated("firms:geo:35.1:51.6")

    # state cleared
    assert "firms:geo:35.1:51.6" not in det._buckets  # noqa: SLF001
    assert "firms:geo:35.1:51.6" not in det._suppressed_until  # noqa: SLF001

    # next 2 signals are pre-trigger again
    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    # 3rd ignites freshly
    assert det.detect(_firms_envelope(signal_envelope_factory)) is not None


def test_firms_on_cluster_terminated_with_suppress_until_blocks_accumulation(
    signal_envelope_factory, fake_clock
):
    from datetime import timedelta
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    cfg = PromoterConfig.from_env()
    det = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    for _ in range(3):
        det.detect(_firms_envelope(signal_envelope_factory))

    suppress_until = fake_clock() + timedelta(seconds=cfg.silence_cooldown_sec)
    det.on_cluster_terminated("firms:geo:35.1:51.6", suppress_until=suppress_until)
    # state cleared + cooldown recorded
    assert "firms:geo:35.1:51.6" not in det._buckets  # noqa: SLF001
    assert det._suppressed_until["firms:geo:35.1:51.6"] == suppress_until  # noqa: SLF001

    # during cooldown, signals are dropped and NOT accumulated
    for _ in range(5):
        assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    assert "firms:geo:35.1:51.6" not in det._buckets  # noqa: SLF001

    # advance past cooldown — first signal accumulates, doesn't ignite alone
    fake_clock.advance(cfg.silence_cooldown_sec + 1)
    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    assert det.detect(_firms_envelope(signal_envelope_factory)) is None
    # 3rd ignites
    assert det.detect(_firms_envelope(signal_envelope_factory)) is not None


def test_firms_on_cluster_terminated_unknown_key_is_noop(fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector

    det = FIRMSGeoClusterDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det.on_cluster_terminated("firms:geo:99.9:99.9")    # no exception
```

- [ ] **Step 2: Run and confirm failure (method missing).**

- [ ] **Step 3: Implement `on_cluster_terminated`.**

Append to `FIRMSGeoClusterDetector`:
```python
    def on_cluster_terminated(
        self,
        cluster_key: str,
        suppress_until: datetime | None = None,
    ) -> None:
        # Only respond to keys we own.
        if not cluster_key.startswith("firms:geo:"):
            return
        self._buckets.pop(cluster_key, None)
        if suppress_until is None:
            self._suppressed_until.pop(cluster_key, None)
        else:
            self._suppressed_until[cluster_key] = suppress_until
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_firms.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/firms.py services/backend/tests/incident_promoter/detectors/test_firms.py
git commit -m "feat(promoter): FIRMS on_cluster_terminated reset + suppress_until"
```

---
## Phase 4 — ClusterStore lifecycle, Sweeper, Promoter wiring, integration

Goal: bring the Promoter to life end-to-end with the FIRMS detector. After this phase, a FIRMS signal stream genuinely produces incidents.

### Task 4.1: `ClusterStore.handle()` — create path

**Files:**
- Modify: `services/backend/app/services/incident_promoter/cluster_store.py`
- Modify: `services/backend/tests/incident_promoter/test_cluster_store.py`

- [ ] **Step 1: Write the failing test.**

Append to `test_cluster_store.py`:
```python
async def test_handle_create_path(fake_clock, fake_incident_store, fake_incident_event_stream):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    hit = ClusterHit(
        cluster_key="firms:geo:48.0:37.8",
        detector_id="firms",
        incident_kind="firms.cluster",
        title="FIRMS cluster ignited · 3 detections in firms:geo:48.0:37.8",
        severity="high",
        coords=(48.0, 37.8),
        location="",
        sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
        layer_hints_to_merge=["firms", "auto_promoter:v1", "cluster:firms:geo:48.0:37.8"],
        timeline_event=IncidentTimelineEvent(
            t_offset_s=0.0, kind="trigger", text="seed", severity="high"
        ),
        contributing_signal_ids=["a", "b", "c"],
    )
    await store.handle(
        hit,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
    )
    assert fake_incident_event_stream.types() == ["incident.open"]
    state = store.get_by_cluster_key("firms:geo:48.0:37.8")
    assert state is not None
    assert state.incident_status == "open"
    # hit_count == len(contributing_signal_ids) at ignition (spec §5.1)
    assert state.hit_count == 3
    assert "firms:geo:48.0:37.8" not in store._reserving  # noqa: SLF001
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement `handle` create path + `get_by_cluster_key`.**

Append to `ClusterStore`:
```python
    def get_by_cluster_key(self, cluster_key: str) -> ClusterState | None:
        return self._by_key.get(cluster_key)

    async def handle(
        self,
        hit,                                # ClusterHit — quoted to avoid circular import
        *,
        incident_store,
        incident_event_stream,
    ) -> None:
        """Phase-1 of phased locking: decide and reserve, then I/O, then finalize."""
        from app.models.incident import IncidentCreateRequest
        from app.services.incident_promoter.detectors.base import ClusterHit  # noqa: F401

        now = self._clock()

        # Phase 1: decide + reserve under lock
        async with self._lock:
            cooldown_until = self._cooldowns.get(hit.cluster_key)
            if cooldown_until is not None:
                if now < cooldown_until:
                    logger.info(
                        "promoter_cluster_silenced",
                        cluster_key=hit.cluster_key,
                        cooldown_seconds=int((cooldown_until - now).total_seconds()),
                    )
                    return
                self._cooldowns.pop(hit.cluster_key, None)

            existing = self._by_key.get(hit.cluster_key)
            if existing is None:
                if hit.cluster_key in self._reserving:
                    logger.info("promoter_race_dropped", cluster_key=hit.cluster_key)
                    return
                self._reserving.add(hit.cluster_key)
                action = "create"
            elif existing.incident_status == "promoted":
                existing.last_signal_ts = now
                logger.info(
                    "promoter_promoted_absorb",
                    cluster_key=hit.cluster_key,
                    incident_id=existing.incident_id,
                )
                return
            else:
                action = "update"

        # Phase 2: I/O outside lock
        if action == "create":
            coords, extra_hints = self._resolve_create_coords(hit)
            # `hit_count` is the count of *contributing signals* (per spec §5.1).
            # Ignition packs all accumulated event_ids into contributing_signal_ids,
            # so a 3-detection FIRMS ignition opens with hit_count=3.
            initial_count = max(1, len(hit.contributing_signal_ids))
            initial_severity = _max_severity(
                hit.severity, _apply_escalation_rule(hit.detector_id, initial_count)
            )
            request = IncidentCreateRequest(
                title=hit.title,
                kind=hit.incident_kind,
                severity=initial_severity,  # type: ignore[arg-type]
                coords=coords,
                location=hit.location,
                sources=list(hit.sources_to_merge),
                layer_hints=list(dict.fromkeys([*hit.layer_hints_to_merge, *extra_hints])),
                initial_text=hit.title,
            )
            try:
                incident = await incident_store.create_incident(request)
            except Exception as exc:  # noqa: BLE001 — resilience
                async with self._lock:
                    self._reserving.discard(hit.cluster_key)
                logger.warning(
                    "promoter_create_failed", cluster_key=hit.cluster_key, error=str(exc)
                )
                return

            # Phase 3: finalize
            async with self._lock:
                self._by_key[hit.cluster_key] = ClusterState(
                    cluster_key=hit.cluster_key,
                    incident_id=incident.id,
                    detector_id=hit.detector_id,
                    severity=initial_severity,
                    coords=coords,
                    hit_count=initial_count,
                    last_signal_ts=now,
                    created_ts=now,
                    contributing_signal_ids=list(hit.contributing_signal_ids[-50:]),
                    incident_status="open",
                )
                self._by_incident_id[incident.id] = hit.cluster_key
                self._reserving.discard(hit.cluster_key)
            incident_event_stream.publish("incident.open", incident)
            logger.info(
                "promoter_cluster_opened",
                cluster_key=hit.cluster_key,
                detector_id=hit.detector_id,
                incident_id=incident.id,
                severity=initial_severity,
            )

    def _resolve_create_coords(
        self, hit
    ) -> tuple[tuple[float, float], list[str]]:
        """Pick representative coords for the new incident.

        - hit.coords is not None → use it; no extra layer hints.
        - hit.coords is None → fall back to (0.0, 0.0) and append "map:no_pin".
        """
        if hit.coords is not None:
            return hit.coords, []
        return (0.0, 0.0), ["map:no_pin"]
```

- [ ] **Step 4: Run and confirm pass.**

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/cluster_store.py services/backend/tests/incident_promoter/test_cluster_store.py
git commit -m "feat(promoter): ClusterStore.handle() create path with phased locking"
```

---

### Task 4.2: `ClusterStore.handle()` — update path, race drop, promoted absorb, cooldown gate

**Files:**
- Modify: `cluster_store.py` + `test_cluster_store.py`

- [ ] **Step 1: Write the failing tests.**

Append:
```python
async def test_handle_update_path_appends_timeline_and_publishes_update(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)

    def _make_hit(eid: str, sev: str = "high") -> ClusterHit:
        return ClusterHit(
            cluster_key="firms:geo:1.0:1.0",
            detector_id="firms",
            incident_kind="firms.cluster",
            title=f"FIRMS hit {eid}",
            severity=sev,
            coords=(1.0, 1.0),
            location="",
            sources_to_merge=["FIRMS · VIIRS_SNPP_NRT"],
            layer_hints_to_merge=["firms", "auto_promoter:v1", "cluster:firms:geo:1.0:1.0"],
            timeline_event=IncidentTimelineEvent(
                t_offset_s=0.0, kind="observation", text=eid, severity=sev
            ),
            contributing_signal_ids=[eid],
        )

    # first hit: create
    await store.handle(
        _make_hit("a"),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
    )
    # second hit: update
    fake_clock.advance(60)
    await store.handle(
        _make_hit("b"),
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
    )

    assert fake_incident_event_stream.types() == ["incident.open", "incident.update"]
    state = store.get_by_cluster_key("firms:geo:1.0:1.0")
    assert state.hit_count == 2
    incident = fake_incident_event_stream.published[-1][1]
    assert len(incident.timeline) == 2  # 1 trigger + 1 observation


async def test_handle_escalation_curves_per_detector(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    """Spec §4.3 escalation: telegram elevated→high@5, high→critical@10."""
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "telegram:topic:escalate"

    def _hit(eid: str) -> ClusterHit:
        return ClusterHit(
            cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
            title=f"Telegram hit {eid}", severity="elevated",
            coords=None, location="",
            sources_to_merge=["Telegram · test"],
            layer_hints_to_merge=["telegram", "auto_promoter:v1", f"cluster:{key}"],
            timeline_event=IncidentTimelineEvent(
                t_offset_s=0.0, kind="observation", text=eid, severity="elevated"
            ),
            contributing_signal_ids=[eid],
        )

    # Ignition packing 3 signals → hit_count=3, severity floor "elevated"
    igniter = ClusterHit(
        cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
        title="Telegram cluster · 3 matching posts", severity="elevated",
        coords=None, location="",
        sources_to_merge=["Telegram · test"],
        layer_hints_to_merge=["telegram", "auto_promoter:v1", f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["a", "b", "c"],
    )
    await store.handle(igniter, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key(key)
    assert state.hit_count == 3 and state.severity == "elevated"

    # Drive hit_count to 5 → escalate to high
    for i, eid in enumerate(["d", "e"]):
        fake_clock.advance(60)
        await store.handle(_hit(eid), incident_store=fake_incident_store,
                           incident_event_stream=fake_incident_event_stream)
    assert state.hit_count == 5
    assert state.severity == "high"

    # Drive hit_count to 10 → escalate to critical
    for eid in ["f", "g", "h", "i", "j"]:
        fake_clock.advance(60)
        await store.handle(_hit(eid), incident_store=fake_incident_store,
                           incident_event_stream=fake_incident_event_stream)
    assert state.hit_count == 10
    assert state.severity == "critical"


async def test_handle_promoted_state_silently_absorbs(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "firms:geo:2.0:2.0"
    hit = ClusterHit(
        cluster_key=key, detector_id="firms", incident_kind="firms.cluster",
        title="seed", severity="high", coords=(2.0, 2.0), location="",
        sources_to_merge=[], layer_hints_to_merge=["auto_promoter:v1", f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key(key)
    # simulate promote
    state.incident_status = "promoted"
    pre = fake_clock()
    fake_clock.advance(30)

    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    # No new SSE frame
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert state.hit_count == 1            # unchanged
    assert state.last_signal_ts > pre      # internal only


async def test_handle_cooldown_drops_hit(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "telegram:topic:abc123"
    store._cooldowns[key] = fake_clock() + timedelta(hours=1)  # noqa: SLF001

    hit = ClusterHit(
        cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
        title="seed", severity="elevated", coords=None, location="",
        sources_to_merge=[], layer_hints_to_merge=[f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=[],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == []
    assert store.get_by_cluster_key(key) is None
    assert key in store.cooldowns()


async def test_handle_cooldown_expired_creates_normally(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit

    store = ClusterStore(clock=fake_clock)
    key = "telegram:topic:abc123"
    store._cooldowns[key] = fake_clock() + timedelta(seconds=10)  # noqa: SLF001
    fake_clock.advance(20)  # cooldown expired

    hit = ClusterHit(
        cluster_key=key, detector_id="telegram", incident_kind="telegram.burst",
        title="fresh", severity="elevated", coords=None, location="",
        sources_to_merge=[], layer_hints_to_merge=[f"cluster:{key}"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=[],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert key not in store.cooldowns()
```

- [ ] **Step 2: Run and confirm failures.**

- [ ] **Step 3: Implement the update branch inside `handle`.**

Replace the `# Phase 2: I/O outside lock` section in `cluster_store.py` to also handle `action == "update"`:

```python
        # Phase 2: I/O outside lock
        if action == "create":
            coords, extra_hints = self._resolve_create_coords(hit)
            request = IncidentCreateRequest(
                title=hit.title,
                kind=hit.incident_kind,
                severity=hit.severity,  # type: ignore[arg-type]
                coords=coords,
                location=hit.location,
                sources=list(hit.sources_to_merge),
                layer_hints=list(dict.fromkeys([*hit.layer_hints_to_merge, *extra_hints])),
                initial_text=hit.title,
            )
            try:
                incident = await incident_store.create_incident(request)
            except Exception as exc:  # noqa: BLE001
                async with self._lock:
                    self._reserving.discard(hit.cluster_key)
                logger.warning(
                    "promoter_create_failed", cluster_key=hit.cluster_key, error=str(exc)
                )
                return

            async with self._lock:
                self._by_key[hit.cluster_key] = ClusterState(
                    cluster_key=hit.cluster_key,
                    incident_id=incident.id,
                    detector_id=hit.detector_id,
                    severity=hit.severity,
                    coords=coords,
                    hit_count=1,
                    last_signal_ts=now,
                    created_ts=now,
                    contributing_signal_ids=list(hit.contributing_signal_ids[-50:]),
                    incident_status="open",
                )
                self._by_incident_id[incident.id] = hit.cluster_key
                self._reserving.discard(hit.cluster_key)
            incident_event_stream.publish("incident.open", incident)
            logger.info(
                "promoter_cluster_opened",
                cluster_key=hit.cluster_key,
                detector_id=hit.detector_id,
                incident_id=incident.id,
                severity=hit.severity,
            )
            return

        # action == "update"
        # Recompute the timeline event with the correct t_offset_s relative to created_ts.
        offset = (now - existing.created_ts).total_seconds()
        from app.models.incident import IncidentTimelineEvent  # local import to avoid cycles
        update_event = IncidentTimelineEvent(
            t_offset_s=max(0.0, offset),
            kind=hit.timeline_event.kind,
            text=hit.timeline_event.text,
            severity=hit.timeline_event.severity,
        )
        # Count this hit's contributing signals (==1 for normal updates) and
        # let the per-detector escalation curve speak. The detector itself
        # may also already emit a higher hit.severity (e.g. GDELT tone>=9),
        # so we take the max of all three (existing / hit / rule-based).
        next_count = existing.hit_count + max(1, len(hit.contributing_signal_ids))
        rule_based = _apply_escalation_rule(existing.detector_id, next_count)
        new_severity = _max_severity(_max_severity(existing.severity, hit.severity), rule_based)
        try:
            incident = await incident_store.apply_signal_update(
                existing.incident_id,
                timeline_event=update_event,
                severity=new_severity,
                sources_to_merge=hit.sources_to_merge,
                layer_hints_to_merge=hit.layer_hints_to_merge,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "promoter_update_failed",
                cluster_key=hit.cluster_key,
                incident_id=existing.incident_id,
                error=str(exc),
            )
            return
        if incident is None:
            return
        async with self._lock:
            existing.hit_count = next_count
            existing.last_signal_ts = now
            existing.severity = new_severity
            existing.contributing_signal_ids = (
                existing.contributing_signal_ids + list(hit.contributing_signal_ids)
            )[-50:]
        incident_event_stream.publish("incident.update", incident)
        logger.info(
            "promoter_cluster_updated",
            cluster_key=hit.cluster_key,
            incident_id=incident.id,
            hit_count=existing.hit_count,
            severity=new_severity,
        )
```

And add at module bottom:
```python
_SEVERITY_RANK: dict[str, int] = {
    "low": 0,
    "elevated": 1,
    "high": 2,
    "critical": 3,
}


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK[a] >= _SEVERITY_RANK[b] else b


# Per-detector escalation curves (spec §4.3). Entries are ordered
# high-threshold-first; the first matching threshold wins.
_ESCALATION_RULES: dict[str, list[tuple[int, str]]] = {
    "firms":    [(10, "critical"), (0, "high")],
    "severity": [(10, "critical"), (0, "high")],
    "telegram": [(10, "critical"), (5, "high"), (0, "elevated")],
    "gdelt":    [(15, "critical"), (10, "high"), (0, "elevated")],
}


def _apply_escalation_rule(detector_id: str, hit_count: int) -> str:
    """Return the rule-based severity floor for a (detector_id, hit_count)."""
    rules = _ESCALATION_RULES.get(detector_id, [(0, "low")])
    for threshold, sev in rules:                          # already sorted high→low
        if hit_count >= threshold:
            return sev
    return "low"
```

- [ ] **Step 4: Run and confirm all four tests pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_cluster_store.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/cluster_store.py services/backend/tests/incident_promoter/test_cluster_store.py
git commit -m "feat(promoter): ClusterStore update path + cooldown gate + promoted absorb"
```

---

### Task 4.3: `mark_promoted` and `mark_silenced`

**Files:**
- Modify: `cluster_store.py` + `test_cluster_store.py`

- [ ] **Step 1: Write the failing tests.**

Append:
```python
async def test_mark_promoted_sets_status_and_is_noop_for_unknown(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit
    from app.models.incident import IncidentTimelineEvent

    store = ClusterStore(clock=fake_clock)
    hit = ClusterHit(
        cluster_key="firms:geo:3.0:3.0", detector_id="firms",
        incident_kind="firms.cluster", title="seed", severity="high",
        coords=(3.0, 3.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:3.0:3.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key("firms:geo:3.0:3.0")
    incident_id = state.incident_id

    await store.mark_promoted(incident_id)
    assert store.get_by_cluster_key("firms:geo:3.0:3.0").incident_status == "promoted"

    await store.mark_promoted("inc-not-here")  # no exception


async def test_mark_silenced_drops_state_records_cooldown_fires_listeners(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.detectors.base import ClusterHit
    from app.models.incident import IncidentTimelineEvent

    received: list[tuple[str, object]] = []
    store = ClusterStore(clock=fake_clock)
    store.add_termination_listener(lambda k, suppress_until=None: received.append((k, suppress_until)))

    hit = ClusterHit(
        cluster_key="telegram:topic:abc", detector_id="telegram",
        incident_kind="telegram.burst", title="seed", severity="elevated",
        coords=None, location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:telegram:topic:abc"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    await store.handle(hit, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    state = store.get_by_cluster_key("telegram:topic:abc")
    until = fake_clock() + timedelta(hours=1)

    await store.mark_silenced(state.incident_id, until=until)

    assert store.get_by_cluster_key("telegram:topic:abc") is None
    assert store.cooldowns()["telegram:topic:abc"] == until
    assert received == [("telegram:topic:abc", until)]
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement.**

Append to `ClusterStore`:
```python
    async def mark_promoted(self, incident_id: str) -> None:
        async with self._lock:
            cluster_key = self._by_incident_id.get(incident_id)
            if cluster_key is None:
                return
            state = self._by_key.get(cluster_key)
            if state is None:
                return
            state.incident_status = "promoted"
        logger.info("promoter_mark_promoted", cluster_key=cluster_key, incident_id=incident_id)

    async def mark_silenced(self, incident_id: str, *, until: datetime) -> None:
        async with self._lock:
            cluster_key = self._by_incident_id.get(incident_id)
            if cluster_key is None:
                return
            self._by_key.pop(cluster_key, None)
            self._by_incident_id.pop(incident_id, None)
            self._cooldowns[cluster_key] = until
        # Fan-out outside the lock — listeners are local + cheap.
        self._fire_terminated(cluster_key, suppress_until=until)
        logger.info(
            "promoter_mark_silenced",
            cluster_key=cluster_key,
            incident_id=incident_id,
            cooldown_seconds=int((until - self._clock()).total_seconds()),
        )

    def _fire_terminated(
        self, cluster_key: str, *, suppress_until: datetime | None = None
    ) -> None:
        for listener in list(self._termination_listeners):
            try:
                listener(cluster_key, suppress_until=suppress_until)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "promoter_terminate_callback_failed", cluster_key=cluster_key
                )
```

- [ ] **Step 4: Run and confirm pass.**

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/cluster_store.py services/backend/tests/incident_promoter/test_cluster_store.py
git commit -m "feat(promoter): mark_promoted + mark_silenced with termination fan-out"
```

---

### Task 4.4: Sweeper — close stale open, drop stale promoted, expire cooldowns

**Files:**
- Modify: `cluster_store.py` + (Sweeper lives on `Promoter`, see Task 4.5) — for this task we add a pure helper `ClusterStore.sweep()` that returns the action set, so the Sweeper coroutine is testable without an asyncio loop.

Actually, to keep it clean: put the sweep logic on `Promoter`, but keep a `ClusterStore.snapshot_for_sweep(now)` helper that returns the stale + expired-cooldown keys. Tests target both layers.

- [ ] **Step 1: Write the failing test.**

Append to `test_cluster_store.py`:
```python
def test_snapshot_for_sweep_classifies_stale_open_promoted_and_expired_cooldowns(
    fake_clock,
):
    from datetime import timedelta
    from app.services.incident_promoter.cluster_store import ClusterState, ClusterStore

    store = ClusterStore(clock=fake_clock)
    now = fake_clock()
    quiet = 900  # 15 min

    # stale open
    store._by_key["k_open"] = ClusterState(  # noqa: SLF001
        cluster_key="k_open", incident_id="inc-a", detector_id="firms",
        severity="high", coords=(0.0, 0.0), hit_count=3,
        last_signal_ts=now - timedelta(seconds=quiet + 60),
        created_ts=now - timedelta(seconds=quiet + 200),
        incident_status="open",
    )
    store._by_incident_id["inc-a"] = "k_open"  # noqa: SLF001

    # stale promoted
    store._by_key["k_prom"] = ClusterState(  # noqa: SLF001
        cluster_key="k_prom", incident_id="inc-b", detector_id="firms",
        severity="high", coords=(0.0, 0.0), hit_count=3,
        last_signal_ts=now - timedelta(seconds=quiet + 30),
        created_ts=now - timedelta(seconds=quiet + 200),
        incident_status="promoted",
    )
    store._by_incident_id["inc-b"] = "k_prom"  # noqa: SLF001

    # fresh
    store._by_key["k_fresh"] = ClusterState(  # noqa: SLF001
        cluster_key="k_fresh", incident_id="inc-c", detector_id="firms",
        severity="high", coords=(0.0, 0.0), hit_count=1,
        last_signal_ts=now - timedelta(seconds=10),
        created_ts=now - timedelta(seconds=10),
        incident_status="open",
    )
    store._by_incident_id["inc-c"] = "k_fresh"  # noqa: SLF001

    # expired + live cooldowns
    store._cooldowns["cool_expired"] = now - timedelta(seconds=1)  # noqa: SLF001
    store._cooldowns["cool_live"] = now + timedelta(seconds=60)  # noqa: SLF001

    snap = store.snapshot_for_sweep(quiet_window_sec=quiet, now=now)
    assert {s.cluster_key for s in snap.stale_open} == {"k_open"}
    assert {s.cluster_key for s in snap.stale_promoted} == {"k_prom"}
    assert set(snap.expired_cooldown_keys) == {"cool_expired"}
```

- [ ] **Step 2: Run and confirm failure (method missing).**

- [ ] **Step 3: Implement `snapshot_for_sweep` + `pop_after_sweep`.**

Append to `cluster_store.py`:
```python
@dataclass
class SweepSnapshot:
    stale_open: list[ClusterState]
    stale_promoted: list[ClusterState]
    expired_cooldown_keys: list[str]
```

Inside `ClusterStore`:
```python
    def snapshot_for_sweep(
        self, *, quiet_window_sec: int, now: datetime
    ) -> SweepSnapshot:
        cutoff = now - timedelta(seconds=quiet_window_sec)
        stale_open: list[ClusterState] = []
        stale_promoted: list[ClusterState] = []
        for state in self._by_key.values():
            if state.last_signal_ts > cutoff:
                continue
            if state.incident_status == "promoted":
                stale_promoted.append(state)
            else:
                stale_open.append(state)
        expired = [k for k, t in self._cooldowns.items() if t <= now]
        return SweepSnapshot(stale_open, stale_promoted, expired)

    async def drop_cluster(self, cluster_key: str) -> None:
        async with self._lock:
            state = self._by_key.pop(cluster_key, None)
            if state is not None:
                self._by_incident_id.pop(state.incident_id, None)
        if state is not None:
            self._fire_terminated(cluster_key)

    def pop_expired_cooldowns(self, expired: list[str]) -> None:
        for k in expired:
            self._cooldowns.pop(k, None)
```

(Add `from datetime import timedelta` at the top of `cluster_store.py` if not already imported.)

- [ ] **Step 4: Run and confirm pass.**

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/cluster_store.py services/backend/tests/incident_promoter/test_cluster_store.py
git commit -m "feat(promoter): ClusterStore snapshot_for_sweep + drop_cluster + cooldown expiry"
```

---

### Task 4.5: `Promoter.run` / `_subscribe` / `_rehydrate` / `_drain_loop` + Sweeper

**Files:**
- Modify: `promoter.py` + `test_promoter.py`

- [ ] **Step 1: Write the failing tests.**

Append to `test_promoter.py`:
```python
async def test_drain_one_processes_a_single_envelope(
    fake_clock, fake_incident_store, fake_incident_event_stream, signal_envelope_factory
):
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    cluster_store = ClusterStore(clock=fake_clock)
    detector = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    cluster_store.add_termination_listener(detector.on_cluster_terminated)

    class _FakeSignalStream:
        def __init__(self):
            self.queue = __import__("asyncio").Queue()
        def subscribe(self):
            return self.queue
        def unsubscribe(self, q): pass

    signal_stream = _FakeSignalStream()

    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=cluster_store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001

    url = "https://firms.example/#@10.0,20.0,10z"
    for _ in range(3):
        await signal_stream.queue.put(
            signal_envelope_factory(source="firms", url=url)
        )
    # drain 3 envelopes: 2 None, 1 ignition
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001

    assert fake_incident_event_stream.types() == ["incident.open"]


async def test_rehydrate_then_subscribe_avoids_double_create(
    fake_clock, fake_incident_store, fake_incident_event_stream, signal_envelope_factory
):
    """Spec §9.2 #6 — buffer fills during rehydrate; first signal updates, not creates."""
    from app.models.incident import (
        Incident, IncidentCreateRequest, IncidentStatus,
    )
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    # Pre-seed an owned open incident at the FIRMS bucket we'll hit
    seeded = await fake_incident_store.create_incident(
        IncidentCreateRequest(
            title="FIRMS cluster ignited · 3 detections in firms:geo:10.0:20.0",
            kind="firms.cluster",
            severity="high",
            coords=(10.0, 20.0),
            layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:10.0:20.0"],
            initial_text="seed",
        )
    )

    cluster_store = ClusterStore(clock=fake_clock)
    detector = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    cluster_store.add_termination_listener(detector.on_cluster_terminated)

    class _FakeSignalStream:
        def __init__(self):
            self.queue = __import__("asyncio").Queue()
        def subscribe(self):
            return self.queue
        def unsubscribe(self, q): pass

    signal_stream = _FakeSignalStream()
    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=cluster_store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001
    # Enqueue a matching FIRMS envelope BEFORE rehydrate completes
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@10.0,20.0,10z")
    )
    await promoter._rehydrate()  # noqa: SLF001
    # The pre-seeded incident is in the store; queued envelope is post-ignition update
    # The detector hasn't accumulated 3 yet → still None. So no event is emitted.
    await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == []
    # Now drive accumulation to ignition — but detector treats this as a fresh bucket,
    # so it takes 2 more signals before emitting an ignition for the SAME cluster_key.
    # Once it does, ClusterStore sees an existing cluster (rehydrated) → UPDATE.
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@10.0,20.0,10z")
    )
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@10.0,20.0,10z")
    )
    await promoter._drain_one()  # noqa: SLF001
    await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.update"]
    assert all(t != "incident.open" for t in fake_incident_event_stream.types())


async def test_sweeper_closes_stale_open_and_drops_promoted(
    fake_clock, fake_incident_store, fake_incident_event_stream
):
    from datetime import timedelta
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.cluster_store import ClusterStore
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.base import ClusterHit
    from app.services.incident_promoter.promoter import Promoter

    cfg = PromoterConfig.from_env()
    store = ClusterStore(clock=fake_clock)

    # Seed two clusters via real handle() paths
    hit_open = ClusterHit(
        cluster_key="firms:geo:4.0:4.0", detector_id="firms",
        incident_kind="firms.cluster", title="seed", severity="high",
        coords=(4.0, 4.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:4.0:4.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["x"],
    )
    hit_prom = ClusterHit(
        cluster_key="firms:geo:5.0:5.0", detector_id="firms",
        incident_kind="firms.cluster", title="seed2", severity="high",
        coords=(5.0, 5.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:5.0:5.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["y"],
    )
    await store.handle(hit_open, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    await store.handle(hit_prom, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    # Promote second
    store.get_by_cluster_key("firms:geo:5.0:5.0").incident_status = "promoted"

    # Both clusters are last_signal_ts == now; advance past quiet window
    fake_clock.advance(cfg.quiet_window_sec + 60)

    promoter = Promoter(
        signal_stream=None,
        cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[],
    )
    await promoter._sweep_once()  # noqa: SLF001

    # incident.open × 2 then incident.close × 1 (only for stale_open)
    assert fake_incident_event_stream.types().count("incident.close") == 1
    # Both clusters are gone from the store
    assert store.get_by_cluster_key("firms:geo:4.0:4.0") is None
    assert store.get_by_cluster_key("firms:geo:5.0:5.0") is None
    # The promoted incident is still PROMOTED in the fake store (not CLOSED)
    promoted_record = next(
        i for i in fake_incident_store.all() if i.title == "seed2"
    )
    from app.models.incident import IncidentStatus
    assert promoted_record.status == IncidentStatus.PROMOTED
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement.**

Replace the contents of `promoter.py` after the class header with:

```python
    # -- composable methods (Phase 4) -----------------------------------

    async def _subscribe(self) -> None:
        if self._signal_stream is None:
            self._subscribed_queue = None
            return
        self._subscribed_queue = self._signal_stream.subscribe()

    def _unsubscribe(self) -> None:
        if self._signal_stream is not None and self._subscribed_queue is not None:
            self._signal_stream.unsubscribe(self._subscribed_queue)
        self._subscribed_queue = None

    async def _rehydrate(self) -> None:
        if self._incident_store is None:
            return
        owned = await self._incident_store.list_owned_for_rehydrate()
        for incident in owned:
            cluster_key = self._extract_cluster_key(incident.layer_hints)
            if cluster_key is None:
                logger.info(
                    "promoter_rehydrate_skipped",
                    incident_id=incident.id,
                    reason="no_cluster_marker",
                )
                continue
            detector_id = cluster_key.split(":", 2)[1] if ":" in cluster_key else "unknown"
            self._cluster_store._by_key[cluster_key] = self._build_rehydrated_state(  # noqa: SLF001
                incident, cluster_key, detector_id
            )
            self._cluster_store._by_incident_id[incident.id] = cluster_key  # noqa: SLF001

    def _build_rehydrated_state(self, incident, cluster_key: str, detector_id: str):
        from app.services.incident_promoter.cluster_store import ClusterState

        return ClusterState(
            cluster_key=cluster_key,
            incident_id=incident.id,
            detector_id=detector_id,
            severity=incident.severity,
            coords=incident.coords,
            hit_count=len(incident.timeline),
            last_signal_ts=self._estimate_last_ts(incident),
            created_ts=incident.trigger_ts,
            contributing_signal_ids=[],
            incident_status=(
                "promoted" if str(incident.status) == "promoted" else "open"
            ),
        )

    @staticmethod
    def _extract_cluster_key(layer_hints: list[str]) -> str | None:
        for h in layer_hints:
            if h.startswith("cluster:"):
                return h[len("cluster:"):]
        return None

    def _estimate_last_ts(self, incident):
        if incident.timeline:
            offset = max(e.t_offset_s for e in incident.timeline)
            from datetime import timedelta
            return incident.trigger_ts + timedelta(seconds=offset)
        return incident.trigger_ts

    async def _drain_one(self) -> None:
        if self._subscribed_queue is None:
            return
        envelope = await self._subscribed_queue.get()
        await self._process(envelope)

    async def _drain_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._drain_one()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep loop alive
                logger.exception("promoter_drain_loop_error")

    async def _process(self, envelope) -> None:
        for detector in self._detectors:
            try:
                hit = detector.detect(envelope)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "promoter_detector_error",
                    detector_id=getattr(detector, "id", "?"),
                    error=str(exc),
                    envelope_event_id=getattr(envelope, "event_id", "?"),
                )
                continue
            if hit is None:
                continue
            await self._cluster_store.handle(
                hit,
                incident_store=self._incident_store,
                incident_event_stream=self._incident_event_stream,
            )

    async def run(self) -> None:
        if not self._config.enabled:
            logger.info("promoter_disabled_skipping_run")
            return
        if not self._has_runtime_deps():
            logger.warning(
                "promoter_run_missing_runtime_deps_skipping",
                has_signal_stream=self._signal_stream is not None,
                has_incident_store=self._incident_store is not None,
            )
            return
        # Register detector termination listeners (must be before any signal arrives)
        for detector in self._detectors:
            self._cluster_store.add_termination_listener(detector.on_cluster_terminated)
        await self._subscribe()
        try:
            await self._rehydrate()
            logger.info(
                "promoter_started",
                detectors_enabled=[d.id for d in self._detectors if d.enabled],
                rehydrated_count=len(self._cluster_store.active_clusters()),
            )
            await self._drain_loop()
        finally:
            self._unsubscribe()

    # -- sweeper --------------------------------------------------------

    async def _sweep_once(self) -> None:
        now = self._clock()
        snap = self._cluster_store.snapshot_for_sweep(
            quiet_window_sec=self._config.quiet_window_sec, now=now
        )
        # Expire cooldowns inline (no I/O)
        self._cluster_store.pop_expired_cooldowns(snap.expired_cooldown_keys)
        # Close stale open
        from app.models.incident import IncidentStatus
        for state in snap.stale_open:
            try:
                closed = await self._incident_store.close_incident(
                    state.incident_id, status=IncidentStatus.CLOSED
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "promoter_close_failed",
                    incident_id=state.incident_id,
                    error=str(exc),
                )
                continue
            await self._cluster_store.drop_cluster(state.cluster_key)
            if closed is not None:
                self._incident_event_stream.publish("incident.close", closed)
                logger.info(
                    "promoter_cluster_closed",
                    cluster_key=state.cluster_key,
                    incident_id=state.incident_id,
                    quiet_seconds=int(self._config.quiet_window_sec),
                    final_hit_count=state.hit_count,
                )
        # Drop stale promoted — no DB write
        for state in snap.stale_promoted:
            await self._cluster_store.drop_cluster(state.cluster_key)

    async def sweeper_loop(self) -> None:
        if not self._config.enabled:
            return
        if not self._has_runtime_deps():
            return
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.sweeper_tick_sec,
                )
                return  # stop set during the wait
            except asyncio.TimeoutError:
                pass
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("promoter_sweeper_error")
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_promoter.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/promoter.py services/backend/tests/incident_promoter/test_promoter.py
git commit -m "feat(promoter): Promoter run/rehydrate/drain + sweeper full implementation"
```

---

### Task 4.6: Router wiring — `/promote` and `/silence` call ClusterStore

**Files:**
- Modify: `services/backend/app/routers/incidents.py`
- Create: `services/backend/tests/incident_promoter/test_router_wiring.py`

- [ ] **Step 1: Write the failing test.**

`services/backend/tests/incident_promoter/test_router_wiring.py`:
```python
"""Verify /promote and /silence call ClusterStore on app.state.

Auth pattern matches the existing tests in test_incidents_router.py:
``monkeypatch.setattr(incidents_router.settings, "incidents_admin_token", ...)``
plus the ``X-Admin-Token`` request header. The mock cluster_store is
installed *inside* the TestClient context so the lifespan startup (which
sets a real ClusterStore on app.state) doesn't overwrite it.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.incident import Incident, IncidentStatus


def _fake_incident(id_: str) -> Incident:
    return Incident(
        id=id_, kind="manual", title="t", severity="high",
        coords=(0.0, 0.0), status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC),
    )


def test_promote_calls_cluster_store_mark_promoted(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    cs = AsyncMock()
    with patch(
        "app.routers.incidents.incident_store.create_incident",
        new=AsyncMock(return_value=_fake_incident("inc-promote-1")),
    ), patch(
        "app.routers.incidents.incident_store.close_incident",
        new=AsyncMock(return_value=_fake_incident("inc-promote-1").model_copy(
            update={"status": IncidentStatus.PROMOTED}
        )),
    ):
        with TestClient(app) as client:
            # Lifespan has run; now install the mock — it sticks for this test.
            app.state.cluster_store = cs

            resp = client.post(
                "/api/incidents/_admin/trigger",
                headers={"X-Admin-Token": "secret-xyz"},
                json={"title": "x", "kind": "manual", "severity": "high",
                      "coords": [0.0, 0.0]},
            )
            assert resp.status_code == 201, resp.text
            incident_id = resp.json()["id"]

            resp = client.post(
                f"/api/incidents/{incident_id}/promote",
                headers={"X-Admin-Token": "secret-xyz"},
            )
            assert resp.status_code == 200, resp.text

    cs.mark_promoted.assert_awaited_once_with(incident_id)


def test_silence_calls_cluster_store_mark_silenced(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    # PromoterConfig is read from app.state by the silence handler. Stub it.
    class _StubCfg:
        silence_cooldown_sec = 3600

    cs = AsyncMock()
    with patch(
        "app.routers.incidents.incident_store.create_incident",
        new=AsyncMock(return_value=_fake_incident("inc-silence-1")),
    ), patch(
        "app.routers.incidents.incident_store.close_incident",
        new=AsyncMock(return_value=_fake_incident("inc-silence-1").model_copy(
            update={"status": IncidentStatus.SILENCED}
        )),
    ):
        with TestClient(app) as client:
            app.state.cluster_store = cs
            app.state.promoter_config = _StubCfg()

            resp = client.post(
                "/api/incidents/_admin/trigger",
                headers={"X-Admin-Token": "secret-xyz"},
                json={"title": "x", "kind": "manual", "severity": "high",
                      "coords": [0.0, 0.0]},
            )
            assert resp.status_code == 201
            incident_id = resp.json()["id"]

            resp = client.post(
                f"/api/incidents/{incident_id}/silence",
                headers={"X-Admin-Token": "secret-xyz"},
            )
            assert resp.status_code == 200

    cs.mark_silenced.assert_awaited_once()
    kwargs = cs.mark_silenced.await_args.kwargs
    assert kwargs.get("until") is not None
```

- [ ] **Step 2: Run and confirm failure (router doesn't call cluster_store yet).**

- [ ] **Step 3: Modify the router endpoints.**

In `services/backend/app/routers/incidents.py`, locate the `promote_incident` and `silence_incident` endpoints. Add `request: Request` to the signature (already imported in that file per line 14). After the existing successful `close_incident` write inside `promote_incident`, append:

```python
    cluster_store = getattr(request.app.state, "cluster_store", None)
    if cluster_store is not None:
        try:
            await cluster_store.mark_promoted(incident_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("router_mark_promoted_failed", incident_id=incident_id, error=str(exc))
```

For `silence_incident`, also read the cooldown from app state:
```python
    cluster_store = getattr(request.app.state, "cluster_store", None)
    cfg = getattr(request.app.state, "promoter_config", None)
    if cluster_store is not None and cfg is not None:
        from datetime import UTC, datetime as _dt, timedelta as _td
        until = _dt.now(UTC) + _td(seconds=cfg.silence_cooldown_sec)
        try:
            await cluster_store.mark_silenced(incident_id, until=until)
        except Exception as exc:  # noqa: BLE001
            log.warning("router_mark_silenced_failed", incident_id=incident_id, error=str(exc))
```

> If `log` is not imported in this router, add `import structlog; log = structlog.get_logger(__name__)`.

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_router_wiring.py tests/test_incidents_router.py -v
```
Expected: all router tests pass (existing + 2 new).

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/routers/incidents.py services/backend/tests/incident_promoter/test_router_wiring.py
git commit -m "feat(promoter): /promote and /silence wire to ClusterStore"
```

---

### Task 4.7: Lifespan upgrade — wire runtime deps, register detectors, **start tasks**

**Files:**
- Modify: `services/backend/app/main.py`

- [ ] **Step 1: Replace the Phase-1 shell wiring with full wiring and start the tasks.**

Find the auto-promoter block added in Task 1.7. Replace the `Promoter(...)` construction and the (currently-disabled) task creation with:

```python
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_stream import get_incident_stream
    from app.services.signal_stream import get_signal_stream
    from app.services import incident_store as _incident_store_module

    _detectors = []
    if _promoter_cfg.firms_enabled:
        _detectors.append(FIRMSGeoClusterDetector(config=_promoter_cfg, clock=_promoter_clock))
    # Phase 5+ will append severity, telegram, gdelt here

    _promoter = Promoter(
        signal_stream=get_signal_stream(),
        cluster_store=_cluster_store,
        incident_store=_incident_store_module,
        incident_event_stream=get_incident_stream(),
        config=_promoter_cfg,
        clock=_promoter_clock,
        detectors=_detectors,
    )
    if _promoter_cfg.enabled:
        _promoter_task = asyncio.create_task(_promoter.run(), name="promoter")
        _sweeper_task = asyncio.create_task(_promoter.sweeper_loop(), name="promoter-sweeper")
```

- [ ] **Step 2: Smoke test backend boots.**
```bash
cd services/backend && uv run python -c "from app.main import app; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Run full backend test suite.**
```bash
cd services/backend && uv run pytest -q
```
Expected: all green.

- [ ] **Step 4: Commit.**
```bash
git add services/backend/app/main.py
git commit -m "feat(promoter): lifespan wires SignalStream + FIRMS detector"
```

---

### Task 4.8: Integration tests #1, #4, #5, #6 from spec §9.2

**Files:**
- Create: `services/backend/tests/integration/test_promoter_pipeline.py`

- [ ] **Step 1: Write the four integration tests.**

```python
"""Integration tests — Promoter + ClusterStore + real FIRMS detector + fakes.

Scenarios from spec §9.2: #1 FIRMS pipeline, #4 Promote mid-cluster,
#5 Silence mid-cluster (both layers), #6 Rehydrate-then-subscribe.
Tests #2 (Severity) and #3 (Telegram) live in Phases 5 and 6.
"""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.models.incident import IncidentStatus
from app.services.incident_promoter.cluster_store import ClusterStore
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
from app.services.incident_promoter.promoter import Promoter


@pytest.fixture
def cfg(monkeypatch) -> PromoterConfig:
    monkeypatch.setenv("ODIN_PROMOTER_QUIET_WINDOW_SEC", "900")
    monkeypatch.setenv("ODIN_PROMOTER_FIRMS_MIN_HITS", "3")
    return PromoterConfig.from_env()


class _FakeSignalStream:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
    def subscribe(self):
        return self.queue
    def unsubscribe(self, q):
        pass


async def _make_promoter(cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
                         signal_stream):
    detector = FIRMSGeoClusterDetector(config=cfg, clock=fake_clock)
    store = ClusterStore(clock=fake_clock)
    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    store.add_termination_listener(detector.on_cluster_terminated)
    await promoter._subscribe()  # noqa: SLF001
    return promoter, store, detector


async def test_firms_full_pipeline_open_update_close(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #1."""
    signal_stream = _FakeSignalStream()
    promoter, store, _ = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    await promoter._rehydrate()  # noqa: SLF001 — nothing to rehydrate

    url = "https://firms.example/#@1.0,1.0,10z"
    for _ in range(4):
        await signal_stream.queue.put(
            signal_envelope_factory(source="firms", url=url)
        )
    for _ in range(4):
        await promoter._drain_one()  # noqa: SLF001

    types = fake_incident_event_stream.types()
    assert types == ["incident.open", "incident.update"]
    incident = fake_incident_event_stream.published[0][1]
    assert "3 detection" in incident.title.lower()
    assert len(incident.timeline) == 1  # ignition adds a single trigger entry

    # advance past quiet window and sweep
    fake_clock.advance(cfg.quiet_window_sec + 60)
    await promoter._sweep_once()  # noqa: SLF001
    assert fake_incident_event_stream.types()[-1] == "incident.close"
    assert store.get_by_cluster_key("firms:geo:1.0:1.0") is None


async def test_promote_mid_cluster_absorbs_then_drops(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #4."""
    signal_stream = _FakeSignalStream()
    promoter, store, _ = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    await promoter._rehydrate()  # noqa: SLF001

    url = "https://firms.example/#@2.0,2.0,10z"
    for _ in range(3):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.open"]
    incident_id = fake_incident_event_stream.published[0][1].id

    await store.mark_promoted(incident_id)

    for _ in range(2):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(2):
        await promoter._drain_one()  # noqa: SLF001
    # No new SSE frames
    assert fake_incident_event_stream.types() == ["incident.open"]

    fake_clock.advance(cfg.quiet_window_sec + 60)
    await promoter._sweep_once()  # noqa: SLF001
    assert store.get_by_cluster_key("firms:geo:2.0:2.0") is None
    # Promoted incident is NOT auto-closed
    promoted = fake_incident_store.get(incident_id)
    assert promoted is not None and promoted.status == IncidentStatus.OPEN
    # ^ Promoter doesn't write the promoted state to DB itself; the router does.
    #   This test is store-only, so the incident stays OPEN in the fake store.


async def test_silence_drops_at_detector_and_at_store(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #5 — both layers."""
    signal_stream = _FakeSignalStream()
    promoter, store, detector = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    await promoter._rehydrate()  # noqa: SLF001

    url = "https://firms.example/#@3.0,3.0,10z"
    for _ in range(3):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001
    incident_id = fake_incident_event_stream.published[0][1].id
    until = fake_clock() + timedelta(seconds=cfg.silence_cooldown_sec)
    await store.mark_silenced(incident_id, until=until)

    # Layer 1 — detector drops signals silently (returns None, no accumulation)
    for _ in range(5):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(5):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert not detector._buckets  # noqa: SLF001

    # Layer 2 — synthesize a ClusterHit directly and call handle() during cooldown
    from app.models.incident import IncidentTimelineEvent
    from app.services.incident_promoter.detectors.base import ClusterHit

    synth = ClusterHit(
        cluster_key="firms:geo:3.0:3.0", detector_id="firms",
        incident_kind="firms.cluster", title="bypass", severity="high",
        coords=(3.0, 3.0), location="", sources_to_merge=[],
        layer_hints_to_merge=["auto_promoter:v1", "cluster:firms:geo:3.0:3.0"],
        timeline_event=IncidentTimelineEvent(t_offset_s=0.0, kind="trigger"),
        contributing_signal_ids=["bypass"],
    )
    await store.handle(synth, incident_store=fake_incident_store,
                       incident_event_stream=fake_incident_event_stream)
    assert fake_incident_event_stream.types() == ["incident.open"]
    assert "firms:geo:3.0:3.0" in store.cooldowns()

    # After cooldown expires, a fresh sequence ignites
    fake_clock.advance(cfg.silence_cooldown_sec + 1)
    for _ in range(3):
        await signal_stream.queue.put(signal_envelope_factory(source="firms", url=url))
    for _ in range(3):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types().count("incident.open") == 2


async def test_rehydrate_then_subscribe_does_not_double_create(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #6 — see existing test in tests/incident_promoter/test_promoter.py."""
    # This is a thinner integration variant that exercises the full Promoter.run
    # composition (subscribe → enqueue → rehydrate → drain) end-to-end.
    from app.models.incident import IncidentCreateRequest

    await fake_incident_store.create_incident(
        IncidentCreateRequest(
            title="FIRMS cluster ignited · 3 detections in firms:geo:6.0:6.0",
            kind="firms.cluster",
            severity="high",
            coords=(6.0, 6.0),
            layer_hints=["firms", "auto_promoter:v1", "cluster:firms:geo:6.0:6.0"],
            initial_text="seed",
        )
    )

    signal_stream = _FakeSignalStream()
    promoter, store, _ = await _make_promoter(
        cfg, fake_clock, fake_incident_store, fake_incident_event_stream, signal_stream
    )
    # signal arrives BEFORE rehydrate finishes
    await signal_stream.queue.put(
        signal_envelope_factory(source="firms", url="https://firms.example/#@6.0,6.0,10z")
    )
    await promoter._rehydrate()  # noqa: SLF001
    # drain — first FIRMS signal is pre-trigger (accumulation), no event yet
    await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == []
    # 2 more signals → 3rd is detector-ignition, but ClusterStore sees rehydrated key
    for _ in range(2):
        await signal_stream.queue.put(
            signal_envelope_factory(source="firms", url="https://firms.example/#@6.0,6.0,10z")
        )
    for _ in range(2):
        await promoter._drain_one()  # noqa: SLF001
    assert "incident.open" not in fake_incident_event_stream.types()
    assert "incident.update" in fake_incident_event_stream.types()
```

- [ ] **Step 2: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/integration/test_promoter_pipeline.py -v
```

- [ ] **Step 3: Commit.**
```bash
git add services/backend/tests/integration/test_promoter_pipeline.py
git commit -m "test(promoter): integration tests #1, #4, #5, #6 (FIRMS pipeline)"
```

---
## Phase 5 — Telegram detector (shingles v1)

### Task 5.1: Title normalization + 5-gram Jaccard

**Files:**
- Create: `services/backend/app/services/incident_promoter/detectors/telegram.py`
- Create: `services/backend/tests/incident_promoter/detectors/test_telegram.py`

- [ ] **Step 1: Write the failing tests.**

```python
"""Unit tests for Telegram detector helpers."""
import pytest

from app.services.incident_promoter.detectors.telegram import (
    _domain_of,
    _jaccard_5gram,
    _normalize_title,
    _shingles,
)


def test_normalize_lowercases_strips_urls_and_punctuation():
    raw = "BREAKING: Strike on Kharkiv https://t.me/foo/123 — confirmed!!"
    assert _normalize_title(raw) == "breaking strike on kharkiv confirmed"


def test_shingles_of_short_text_returns_single_token_tuple():
    assert _shingles("a b") == {("a", "b")}


def test_shingles_5gram_for_long_text():
    s = _shingles("alpha bravo charlie delta echo foxtrot")
    # 2 windows of 5 tokens each
    assert ("alpha", "bravo", "charlie", "delta", "echo") in s
    assert ("bravo", "charlie", "delta", "echo", "foxtrot") in s


def test_jaccard_5gram_identical_is_one():
    a = _shingles("strike on kharkiv overnight powerful")
    b = _shingles("strike on kharkiv overnight powerful")
    assert _jaccard_5gram(a, b) == 1.0


def test_jaccard_5gram_disjoint_is_zero():
    a = _shingles("alpha bravo charlie delta echo")
    b = _shingles("zulu yankee xray whisky victor")
    assert _jaccard_5gram(a, b) == 0.0


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://t.me/OSINTdefender/12345", "t.me"),
        ("http://example.com/path", "example.com"),
        ("", ""),
        (None, ""),
    ],
)
def test_domain_of(url, expected):
    assert _domain_of(url) == expected
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement the helpers.**

`services/backend/app/services/incident_promoter/detectors/telegram.py`:
```python
"""Telegram topic-cluster detector — shingles-based v1.

The TEI embedding path is gated by ``ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED``;
when that flag is true in v1, the detector logs a warning at construction and
disables itself (no network call). The shingles path remains the production
path for v1.
"""
from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import ClusterHit


_URL_RE = re.compile(r"https?://\S+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")


def _normalize_title(raw: str) -> str:
    s = _URL_RE.sub("", (raw or "").lower())
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _shingles(normalized: str, *, n: int = 5) -> set[tuple[str, ...]]:
    tokens = normalized.split()
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard_5gram(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _domain_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host
```

- [ ] **Step 4: Run and confirm pass.**

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/telegram.py services/backend/tests/incident_promoter/detectors/test_telegram.py
git commit -m "feat(promoter): Telegram detector helpers (normalize/shingles/jaccard)"
```

---

### Task 5.2: Telegram detector — centroid LRU, accumulation, ignition, update

**Files:**
- Modify: `telegram.py` + `test_telegram.py`

- [ ] **Step 1: Write the failing tests.**

Append:
```python
def _tg_envelope(signal_envelope_factory, title: str, url: str = "https://t.me/x/1"):
    return signal_envelope_factory(source="telegram", title=title, url=url)


def test_telegram_pre_trigger_and_ignition(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    cfg = PromoterConfig.from_env()
    det = TelegramTopicDetector(config=cfg, clock=fake_clock)
    titles = [
        "Russian strike on Kharkiv overnight powerful explosions reported",
        "Kharkiv overnight strike with powerful explosions reported Russia",
        "Powerful overnight strike on Kharkiv Russia explosions",
    ]
    h1 = det.detect(_tg_envelope(signal_envelope_factory, titles[0]))
    h2 = det.detect(_tg_envelope(signal_envelope_factory, titles[1]))
    h3 = det.detect(_tg_envelope(signal_envelope_factory, titles[2]))
    assert h1 is None and h2 is None
    assert h3 is not None
    assert h3.detector_id == "telegram"
    assert h3.cluster_key.startswith("telegram:topic:")
    assert h3.severity == "elevated"
    assert h3.coords is None
    assert len(h3.contributing_signal_ids) == 3


def test_telegram_does_not_match_unrelated_titles(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    det = TelegramTopicDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det.detect(_tg_envelope(signal_envelope_factory, "strike on kharkiv overnight powerful"))
    h = det.detect(_tg_envelope(signal_envelope_factory, "election results in argentina"))
    assert h is None
    # two separate centroids
    assert len(det._centroids) == 2  # noqa: SLF001


def test_telegram_domain_match_boost_lowers_threshold(signal_envelope_factory, fake_clock):
    """Marginal-overlap pair (Jaccard=0.5) matches with domain boost, not without."""
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    # Constructed shingle sets:
    # t1 → {(a,b,c,d,e), (b,c,d,e,f), (c,d,e,f,g)}
    # t2 → {(a,b,c,d,e), (b,c,d,e,f), (c,d,e,f,z)}
    # intersection=2, union=4 ⇒ Jaccard=0.50 — above 0.45 boost, below 0.55 default.
    t1 = "alpha bravo charlie delta echo foxtrot golf"
    t2 = "alpha bravo charlie delta echo foxtrot zulu"

    # Different domains → no boost → 2 separate centroids
    det_no_boost = TelegramTopicDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det_no_boost.detect(_tg_envelope(signal_envelope_factory, t1, url="https://t.me/a/1"))
    det_no_boost.detect(_tg_envelope(signal_envelope_factory, t2, url="https://example.com/x"))
    assert len(det_no_boost._centroids) == 2  # noqa: SLF001

    # Same domain → boost → single centroid
    det_with_boost = TelegramTopicDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det_with_boost.detect(_tg_envelope(signal_envelope_factory, t1, url="https://t.me/a/1"))
    det_with_boost.detect(_tg_envelope(signal_envelope_factory, t2, url="https://t.me/a/2"))
    assert len(det_with_boost._centroids) == 1  # noqa: SLF001


def test_telegram_lru_evicts_at_capacity(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    det = TelegramTopicDetector(
        config=PromoterConfig.from_env(), clock=fake_clock, max_centroids=3
    )
    for i in range(4):
        det.detect(_tg_envelope(
            signal_envelope_factory,
            title=f"unique topic number {i} alpha bravo charlie delta echo",
            url=f"https://t.me/u{i}/1",
        ))
    assert len(det._centroids) == 3  # noqa: SLF001


def test_telegram_on_cluster_terminated_with_suppress(signal_envelope_factory, fake_clock):
    from datetime import timedelta
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    cfg = PromoterConfig.from_env()
    det = TelegramTopicDetector(config=cfg, clock=fake_clock)
    for _ in range(3):
        det.detect(_tg_envelope(
            signal_envelope_factory,
            "strike on kharkiv overnight powerful explosions reported",
        ))
    cluster_key = next(iter(det._centroids.values())).cluster_key  # noqa: SLF001
    until = fake_clock() + timedelta(hours=1)
    det.on_cluster_terminated(cluster_key, suppress_until=until)
    # During cooldown nothing accumulates and nothing is emitted
    for _ in range(5):
        assert det.detect(_tg_envelope(
            signal_envelope_factory,
            "strike on kharkiv overnight powerful explosions reported",
        )) is None
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement the detector class.**

Append to `telegram.py`:
```python
import hashlib
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class _Centroid:
    cluster_key: str
    tokens: set[tuple[str, ...]]
    deque: deque = field(default_factory=deque)  # entries: (ts, event_id)
    ignited: bool = False
    last_seen_ts: datetime | None = None
    domain: str = ""


class TelegramTopicDetector:
    """Telegram topic-cluster detector. Shingles-only in v1."""

    id = "telegram"

    def __init__(
        self,
        *,
        config: PromoterConfig,
        clock: Callable[[], datetime],
        max_centroids: int = 50,
    ) -> None:
        self._config = config
        self._clock = clock
        self._max_centroids = max_centroids
        self._centroids: dict[str, _Centroid] = {}
        self._suppressed_until: dict[str, datetime] = {}
        if config.telegram_embeddings_enabled:
            logger.warning(
                "promoter_telegram_embeddings_flag_disables_detector_in_v1",
                hint="ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED=true; v1 has no embedding path.",
            )

    @property
    def enabled(self) -> bool:
        if self._config.telegram_embeddings_enabled:
            return False
        return self._config.telegram_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        if (envelope.payload.source or "").lower() != "telegram":
            return None

        normalized = _normalize_title(envelope.payload.title)
        if not normalized:
            return None
        shingles = _shingles(normalized)
        if not shingles:
            return None
        domain = _domain_of(envelope.payload.url)

        # Find best matching centroid
        best_key: str | None = None
        best_score = 0.0
        for centroid in self._centroids.values():
            score = _jaccard_5gram(shingles, centroid.tokens)
            threshold = (
                self._config.telegram_jaccard_threshold_domain
                if domain and centroid.domain == domain
                else self._config.telegram_jaccard_threshold
            )
            if score >= threshold and score > best_score:
                best_score = score
                best_key = centroid.cluster_key

        if best_key is None:
            # New centroid
            cluster_key = "telegram:topic:" + hashlib.sha1(
                ("|".join(sorted(" ".join(t) for t in shingles))).encode()
            ).hexdigest()[:12]
            centroid = _Centroid(
                cluster_key=cluster_key,
                tokens=shingles,
                domain=domain,
            )
            self._centroids[cluster_key] = centroid
            self._evict_if_needed()
        else:
            cluster_key = best_key
            centroid = self._centroids[cluster_key]
            # widen centroid tokens lazily
            centroid.tokens |= shingles

        # Suppression check
        suppress_until = self._suppressed_until.get(cluster_key)
        if suppress_until is not None:
            if self._clock() < suppress_until:
                return None
            self._suppressed_until.pop(cluster_key, None)

        self._prune(centroid)
        centroid.deque.append((self._clock(), envelope.event_id))
        centroid.last_seen_ts = self._clock()

        if centroid.ignited:
            return self._build_update_hit(envelope, cluster_key)
        if len(centroid.deque) >= self._config.telegram_min_hits:
            centroid.ignited = True
            return self._build_ignition_hit(envelope, cluster_key, centroid)
        return None

    def on_cluster_terminated(
        self, cluster_key: str, suppress_until: datetime | None = None
    ) -> None:
        if not cluster_key.startswith("telegram:topic:"):
            return
        c = self._centroids.pop(cluster_key, None)
        if suppress_until is None:
            self._suppressed_until.pop(cluster_key, None)
        else:
            self._suppressed_until[cluster_key] = suppress_until
        del c  # release reference

    # -- internals ------------------------------------------------------

    def _evict_if_needed(self) -> None:
        if len(self._centroids) <= self._max_centroids:
            return
        # Evict least-recently-seen
        oldest_key = min(
            self._centroids,
            key=lambda k: self._centroids[k].last_seen_ts or datetime.min.replace(tzinfo=self._clock().tzinfo),
        )
        self._centroids.pop(oldest_key, None)

    def _prune(self, centroid: _Centroid) -> None:
        cutoff = self._clock() - timedelta(seconds=self._config.telegram_window_sec)
        while centroid.deque and centroid.deque[0][0] < cutoff:
            centroid.deque.popleft()

    def _build_ignition_hit(self, envelope, cluster_key, centroid: _Centroid) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_ignition_timeline_event,
        )
        count = len(centroid.deque)
        title = f"Telegram cluster · {count} matching posts"
        ids = [eid for _ts, eid in centroid.deque]
        surrogate = ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="telegram.burst", title=title, severity="elevated",
            coords=None, location="", sources_to_merge=[], layer_hints_to_merge=[],
            timeline_event=None, contributing_signal_ids=[],  # type: ignore[arg-type]
        )
        return ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="telegram.burst", title=title, severity="elevated",
            coords=None, location="",
            sources_to_merge=[f"Telegram · {centroid.domain or 'unknown'}"],
            layer_hints_to_merge=[
                "telegram", "auto_promoter:v1", f"cluster:{cluster_key}",
            ],
            timeline_event=build_ignition_timeline_event(surrogate),
            contributing_signal_ids=ids,
        )

    def _build_update_hit(self, envelope, cluster_key) -> ClusterHit:
        from app.services.incident_promoter.detectors.base import (
            build_update_timeline_event,
        )
        domain = _domain_of(envelope.payload.url)
        title = f"Telegram post · {cluster_key}"
        surrogate = ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="telegram.burst", title=title, severity="elevated",
            coords=None, location="", sources_to_merge=[], layer_hints_to_merge=[],
            timeline_event=None, contributing_signal_ids=[],  # type: ignore[arg-type]
        )
        return ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="telegram.burst", title=title, severity="elevated",
            coords=None, location="",
            sources_to_merge=[f"Telegram · {domain or 'unknown'}"],
            layer_hints_to_merge=[
                "telegram", "auto_promoter:v1", f"cluster:{cluster_key}",
            ],
            timeline_event=build_update_timeline_event(surrogate, t_offset_s=0.0),
            contributing_signal_ids=[envelope.event_id],
        )
```

- [ ] **Step 4: Run and confirm pass.**

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/telegram.py services/backend/tests/incident_promoter/detectors/test_telegram.py
git commit -m "feat(promoter): Telegram detector v1 (shingles + LRU + suppression)"
```

---

### Task 5.3: Wire Telegram detector into lifespan + integration test #3

**Files:**
- Modify: `services/backend/app/main.py`
- Modify: `services/backend/tests/integration/test_promoter_pipeline.py`

- [ ] **Step 1: Lifespan — append Telegram to detectors.**

In `main.py`, in the auto-promoter block, replace the FIRMS-only detector list with:
```python
    from app.services.incident_promoter.detectors.firms import FIRMSGeoClusterDetector
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    _detectors: list = []
    if _promoter_cfg.firms_enabled:
        _detectors.append(FIRMSGeoClusterDetector(config=_promoter_cfg, clock=_promoter_clock))
    if _promoter_cfg.telegram_enabled:
        _detectors.append(TelegramTopicDetector(config=_promoter_cfg, clock=_promoter_clock))
```

- [ ] **Step 2: Add integration test #3.**

Append to `test_promoter_pipeline.py`:
```python
async def test_telegram_cluster_pipeline(
    cfg, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #3 — Telegram topic cluster + unrelated signal."""
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    detector = TelegramTopicDetector(config=cfg, clock=fake_clock)
    store = ClusterStore(clock=fake_clock)
    store.add_termination_listener(detector.on_cluster_terminated)

    signal_stream = _FakeSignalStream()
    promoter = Promoter(
        signal_stream=signal_stream,
        cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg,
        clock=fake_clock,
        detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001
    await promoter._rehydrate()  # noqa: SLF001

    matching = [
        "Strike on Kharkiv overnight powerful explosions reported",
        "Overnight strike on Kharkiv with powerful explosions",
        "Powerful overnight strike on Kharkiv explosions reported",
        "Kharkiv strike overnight powerful explosions",
    ]
    unrelated = "Argentina election results final tally posted"
    for title in matching:
        await signal_stream.queue.put(
            signal_envelope_factory(source="telegram", title=title, url="https://t.me/a/1")
        )
    await signal_stream.queue.put(
        signal_envelope_factory(source="telegram", title=unrelated, url="https://t.me/b/1")
    )
    for _ in range(5):
        await promoter._drain_one()  # noqa: SLF001

    types = fake_incident_event_stream.types()
    assert types.count("incident.open") == 1
    assert types.count("incident.update") == 1
    # unrelated didn't ignite (only 1 hit in its own centroid)
```

- [ ] **Step 3: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/integration/test_promoter_pipeline.py::test_telegram_cluster_pipeline -v
```

- [ ] **Step 4: Commit.**
```bash
git add services/backend/app/main.py services/backend/tests/integration/test_promoter_pipeline.py
git commit -m "feat(promoter): wire Telegram detector + integration test #3"
```

---

## Phase 6 — Severity Burst Detector (default-off)

### Task 6.1: Implement Severity detector + non-spatial handling

**Files:**
- Create: `services/backend/app/services/incident_promoter/detectors/severity.py`
- Create: `services/backend/tests/incident_promoter/detectors/test_severity.py`

- [ ] **Step 1: Write the failing tests.**

```python
"""Unit tests for Severity Burst detector."""
import pytest


def test_severity_disabled_by_default(fake_clock, signal_envelope_factory):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    assert cfg.severity_enabled is False
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    for _ in range(10):
        env = signal_envelope_factory(severity="high")
        assert det.detect(env) is None


def test_severity_ignition_at_min_hits_with_non_spatial(fake_clock, signal_envelope_factory,
                                                       monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    # 4 high signals — pre-trigger
    for _ in range(4):
        assert det.detect(signal_envelope_factory(severity="high", source="rss")) is None
    hit = det.detect(signal_envelope_factory(severity="high", source="telegram"))
    assert hit is not None
    assert hit.cluster_key == "severity:global"
    assert hit.coords is None
    assert hit.severity == "high"
    assert "auto_promoter:v1" in hit.layer_hints_to_merge


def test_severity_low_signals_do_not_count(fake_clock, signal_envelope_factory, monkeypatch):
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    for _ in range(10):
        assert det.detect(signal_envelope_factory(severity="low")) is None
    assert not det._buckets["severity:global"].signals  # noqa: SLF001


def test_severity_on_cluster_terminated_resets(fake_clock, signal_envelope_factory, monkeypatch):
    from datetime import timedelta
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    det = SeverityBurstDetector(config=cfg, clock=fake_clock)
    for _ in range(5):
        det.detect(signal_envelope_factory(severity="high"))
    until = fake_clock() + timedelta(hours=1)
    det.on_cluster_terminated("severity:global", suppress_until=until)
    for _ in range(5):
        assert det.detect(signal_envelope_factory(severity="high")) is None
    fake_clock.advance(3601)
    # Restart accumulation
    for _ in range(4):
        assert det.detect(signal_envelope_factory(severity="high")) is None
    assert det.detect(signal_envelope_factory(severity="high")) is not None
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement.**

`services/backend/app/services/incident_promoter/detectors/severity.py`:
```python
"""Severity-burst detector. DEFAULT-OFF in v1.

Cluster key is always ``severity:global``; the resulting incident is
non-spatial. ClusterStore resolves ``coords=None`` to ``(0.0, 0.0)`` and
appends ``map:no_pin`` to ``layer_hints`` — the frontend must respect this
hint or non-spatial incidents will render at Null Island.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import (
    ClusterHit,
    build_ignition_timeline_event,
    build_update_timeline_event,
)


_HIGH_SET = {"high", "critical"}


@dataclass
class _Bucket:
    signals: deque = field(default_factory=deque)
    ignited: bool = False


class SeverityBurstDetector:
    id = "severity"

    def __init__(
        self, *, config: PromoterConfig, clock: Callable[[], datetime]
    ) -> None:
        self._config = config
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {"severity:global": _Bucket()}
        self._suppressed_until: dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._config.severity_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        sev = (envelope.payload.severity or "").lower()
        if sev not in _HIGH_SET:
            return None
        cluster_key = "severity:global"
        suppress_until = self._suppressed_until.get(cluster_key)
        if suppress_until is not None:
            if self._clock() < suppress_until:
                return None
            self._suppressed_until.pop(cluster_key, None)

        bucket = self._buckets[cluster_key]
        cutoff = self._clock() - timedelta(seconds=self._config.severity_window_sec)
        while bucket.signals and bucket.signals[0][0] < cutoff:
            bucket.signals.popleft()
        bucket.signals.append((self._clock(), envelope.event_id, sev))

        if bucket.ignited:
            return self._build_update(envelope, cluster_key)
        if len(bucket.signals) >= self._config.severity_min_hits:
            bucket.ignited = True
            return self._build_ignition(envelope, cluster_key, bucket)
        return None

    def on_cluster_terminated(
        self, cluster_key: str, suppress_until: datetime | None = None
    ) -> None:
        if cluster_key != "severity:global":
            return
        self._buckets[cluster_key] = _Bucket()
        if suppress_until is None:
            self._suppressed_until.pop(cluster_key, None)
        else:
            self._suppressed_until[cluster_key] = suppress_until

    def _build_ignition(self, envelope, cluster_key, bucket: _Bucket) -> ClusterHit:
        count = len(bucket.signals)
        sources_in_burst = {e for *_x, e in []}  # placeholder typing
        # Recompute distinct sources from the deque — bucket entries are
        # (ts, event_id, severity) — we use envelope.payload.source for ignition
        # source diversity; v1 keeps this simple and just shows the count.
        title = f"Severity burst · {count} high-severity signals"
        ids = [eid for _ts, eid, _sev in bucket.signals]
        surrogate = ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="", sources_to_merge=[], layer_hints_to_merge=[],
            timeline_event=None, contributing_signal_ids=[],  # type: ignore[arg-type]
        )
        return ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="",
            sources_to_merge=["severity-burst"],
            layer_hints_to_merge=[
                "events", "auto_promoter:v1", f"cluster:{cluster_key}",
            ],
            timeline_event=build_ignition_timeline_event(surrogate),
            contributing_signal_ids=ids,
        )

    def _build_update(self, envelope, cluster_key) -> ClusterHit:
        title = f"Severity hit · {envelope.payload.source}"
        surrogate = ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="", sources_to_merge=[], layer_hints_to_merge=[],
            timeline_event=None, contributing_signal_ids=[],  # type: ignore[arg-type]
        )
        return ClusterHit(
            cluster_key=cluster_key, detector_id=self.id,
            incident_kind="severity.burst", title=title, severity="high",
            coords=None, location="",
            sources_to_merge=["severity-burst"],
            layer_hints_to_merge=[
                "events", "auto_promoter:v1", f"cluster:{cluster_key}",
            ],
            timeline_event=build_update_timeline_event(surrogate, t_offset_s=0.0),
            contributing_signal_ids=[envelope.event_id],
        )
```

- [ ] **Step 4: Run and confirm pass.**

- [ ] **Step 5: Wire into lifespan.**

In `main.py`, extend the detector list:
```python
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector
    if _promoter_cfg.severity_enabled:
        _detectors.append(SeverityBurstDetector(config=_promoter_cfg, clock=_promoter_clock))
```

- [ ] **Step 6: Add integration test #2.**

Append to `test_promoter_pipeline.py`:
```python
async def test_severity_burst_pipeline_with_map_no_pin(
    monkeypatch, fake_clock, fake_incident_store, fake_incident_event_stream,
    signal_envelope_factory,
):
    """Spec §9.2 #2 — severity burst on opt-in flag, coords=(0,0)+map:no_pin."""
    monkeypatch.setenv("ODIN_PROMOTER_SEVERITY_ENABLED", "true")
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.severity import SeverityBurstDetector

    cfg = PromoterConfig.from_env()
    detector = SeverityBurstDetector(config=cfg, clock=fake_clock)
    store = ClusterStore(clock=fake_clock)
    store.add_termination_listener(detector.on_cluster_terminated)

    signal_stream = _FakeSignalStream()
    promoter = Promoter(
        signal_stream=signal_stream, cluster_store=store,
        incident_store=fake_incident_store,
        incident_event_stream=fake_incident_event_stream,
        config=cfg, clock=fake_clock, detectors=[detector],
    )
    await promoter._subscribe()  # noqa: SLF001
    await promoter._rehydrate()  # noqa: SLF001

    sources = ["rss", "telegram", "firms", "rss", "telegram"]
    for s in sources:
        await signal_stream.queue.put(signal_envelope_factory(source=s, severity="high"))
    for _ in range(5):
        await promoter._drain_one()  # noqa: SLF001
    assert fake_incident_event_stream.types() == ["incident.open"]
    incident = fake_incident_event_stream.published[0][1]
    assert incident.coords == (0.0, 0.0)
    assert "map:no_pin" in incident.layer_hints
```

- [ ] **Step 7: Run and confirm pass.**

- [ ] **Step 8: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/severity.py services/backend/tests/incident_promoter/detectors/test_severity.py services/backend/tests/integration/test_promoter_pipeline.py services/backend/app/main.py
git commit -m "feat(promoter): Severity-Burst detector (default-off) + integration test"
```

---

## Phase 7 — GDELT Detector Skeleton (default-off)

### Task 7.1: Payload audit + skeleton

**Files:**
- Create: `services/backend/app/services/incident_promoter/detectors/gdelt.py`
- Create: `services/backend/tests/incident_promoter/detectors/test_gdelt.py`

Note: This task does **not** wire GDELT into the lifespan. The detector ships disabled by default and the lifespan code stays focused on FIRMS + Severity + Telegram. Enabling GDELT requires verifying the real payload schema first; the smoke test below pins the disabled behavior.

- [ ] **Step 1: Audit the real GDELT payload (no code change yet).**

Read `services/data-ingestion/feeds/gdelt_collector.py`. Identify which fields it puts on the Redis stream and which match the spec's expectations (`actor1_geo_lat/lon`, `tone`, `mention_count`). Record findings in a comment at the top of the detector module (Step 3 below).

- [ ] **Step 2: Write the failing test.**

`services/backend/tests/incident_promoter/detectors/test_gdelt.py`:
```python
"""Unit tests for GDELT skeleton — default-off behavior only."""
def test_gdelt_disabled_by_default_returns_none(fake_clock, signal_envelope_factory):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.gdelt import GDELTToneSpikeDetector

    cfg = PromoterConfig.from_env()
    assert cfg.gdelt_enabled is False
    det = GDELTToneSpikeDetector(config=cfg, clock=fake_clock)
    for _ in range(10):
        env = signal_envelope_factory(
            source="gdelt",
            extras={"actor1_geo_lat": 10.0, "actor1_geo_lon": 20.0,
                    "tone": -8.5, "mention_count": 5},
        )
        assert det.detect(env) is None


def test_gdelt_on_cluster_terminated_is_noop(fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.gdelt import GDELTToneSpikeDetector

    det = GDELTToneSpikeDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det.on_cluster_terminated("gdelt:geo:10.0:20.0:RUS")    # no exception
```

- [ ] **Step 3: Implement the skeleton.**

`services/backend/app/services/incident_promoter/detectors/gdelt.py`:
```python
"""GDELT tone-spike detector — SKELETON, default-off in v1.

The exact field names below (``actor1_geo_lat``, ``actor1_geo_lon``,
``tone``, ``mention_count``) MUST be verified against the live
``services/data-ingestion/feeds/gdelt_collector.py`` output before this
detector is enabled. See spec §10 (Risks) and §12 (Phase 7).

When ``ODIN_PROMOTER_GDELT_ENABLED=true`` is set, the detector will start
processing signals using the field names above. If the live schema
differs, the detector will silently drop every signal (no hits) because
the field lookups return ``None``.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.models.signals import SignalEnvelope
from app.services.incident_promoter.config import PromoterConfig
from app.services.incident_promoter.detectors.base import ClusterHit


class GDELTToneSpikeDetector:
    id = "gdelt"

    def __init__(
        self, *, config: PromoterConfig, clock: Callable[[], datetime]
    ) -> None:
        self._config = config
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return self._config.gdelt_enabled

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None:
        if not self.enabled:
            return None
        # Real accumulation logic deferred until the payload schema is verified.
        # When implementing: build cluster_key as
        #   gdelt:geo:<round(lat,0.5)>:<round(lon,0.5)>:<actor1>
        # and apply min_hits / window_sec from config.
        return None

    def on_cluster_terminated(
        self, cluster_key: str, suppress_until: datetime | None = None
    ) -> None:
        # No state to reset until real detection is implemented.
        return
```

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/detectors/test_gdelt.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/services/incident_promoter/detectors/gdelt.py services/backend/tests/incident_promoter/detectors/test_gdelt.py
git commit -m "feat(promoter): GDELT skeleton (default-off, payload schema unverified)"
```

---

## Phase 8 — Admin Inspector Endpoint

### Task 8.1: `GET /api/incidents/_admin/promoter`

**Files:**
- Modify: `services/backend/app/routers/incidents.py`
- Create: `services/backend/tests/incident_promoter/test_admin_inspector.py`

- [ ] **Step 1: Write the failing test.**

```python
"""Tests for GET /api/incidents/_admin/promoter."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services.incident_promoter.cluster_store import ClusterState, ClusterStore
from app.services.incident_promoter.config import PromoterConfig


def test_admin_inspector_returns_snapshot(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    clock = lambda: datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    store = ClusterStore(clock=clock)
    store._by_key["firms:geo:1.0:1.0"] = ClusterState(  # noqa: SLF001
        cluster_key="firms:geo:1.0:1.0", incident_id="inc-a",
        detector_id="firms", severity="high", coords=(1.0, 1.0),
        hit_count=4, last_signal_ts=clock(), created_ts=clock(),
        incident_status="open",
    )
    store._by_incident_id["inc-a"] = "firms:geo:1.0:1.0"  # noqa: SLF001
    store._cooldowns["telegram:topic:abc"] = clock() + timedelta(hours=1)  # noqa: SLF001

    with TestClient(app) as client:
        # Install the seeded store after lifespan has set its own.
        app.state.cluster_store = store
        app.state.promoter_config = PromoterConfig.from_env()

        resp = client.get(
            "/api/incidents/_admin/promoter",
            headers={"X-Admin-Token": "secret-xyz"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "enabled_detectors" in body
    assert any(c["cluster_key"] == "firms:geo:1.0:1.0" for c in body["active_clusters"])
    assert body["cooldowns"][0]["cluster_key"] == "telegram:topic:abc"
    assert "cooldown_until" in body["cooldowns"][0]


def test_admin_inspector_returns_empty_when_no_promoter(monkeypatch):
    from app.routers import incidents as incidents_router
    monkeypatch.setattr(
        incidents_router.settings, "incidents_admin_token", "secret-xyz"
    )

    with TestClient(app) as client:
        app.state.cluster_store = None
        app.state.promoter_config = None
        resp = client.get(
            "/api/incidents/_admin/promoter",
            headers={"X-Admin-Token": "secret-xyz"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled_detectors"] == []
    assert body["active_clusters"] == []
    assert body["cooldowns"] == []
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement.**

In `services/backend/app/routers/incidents.py`, add the inspector route **before** the `/{incident_id}` route:

```python
@router.get(
    "/_admin/promoter",
    dependencies=[Depends(_require_admin)],
)
async def admin_promoter_inspector(request: Request) -> dict:
    """Read-only snapshot of the auto-promoter ClusterStore."""
    cluster_store = getattr(request.app.state, "cluster_store", None)
    cfg = getattr(request.app.state, "promoter_config", None)
    if cluster_store is None or cfg is None:
        return {
            "enabled_detectors": [],
            "config": {},
            "active_clusters": [],
            "cooldowns": [],
        }
    active = [
        {
            "cluster_key": s.cluster_key,
            "incident_id": s.incident_id,
            "detector_id": s.detector_id,
            "incident_status": s.incident_status,
            "severity": s.severity,
            "hit_count": s.hit_count,
            "last_signal_ts": s.last_signal_ts.isoformat(),
            "created_ts": s.created_ts.isoformat(),
        }
        for s in cluster_store.active_clusters()
    ]
    cooldowns = [
        {"cluster_key": k, "cooldown_until": t.isoformat()}
        for k, t in cluster_store.cooldowns().items()
    ]
    return {
        "enabled_detectors": cfg.enabled_detector_ids(),
        "config": {
            "quiet_window_sec": cfg.quiet_window_sec,
            "sweeper_tick_sec": cfg.sweeper_tick_sec,
            "silence_cooldown_sec": cfg.silence_cooldown_sec,
        },
        "active_clusters": active,
        "cooldowns": cooldowns,
    }
```

> The decorator order matters: this route MUST be declared in the source file **before** the `@router.get("/{incident_id}")` route. Verify by inspection.

- [ ] **Step 4: Run and confirm pass.**
```bash
cd services/backend && uv run pytest tests/incident_promoter/test_admin_inspector.py -v
```

- [ ] **Step 5: Commit.**
```bash
git add services/backend/app/routers/incidents.py services/backend/tests/incident_promoter/test_admin_inspector.py
git commit -m "feat(promoter): read-only admin inspector endpoint"
```

---

## Phase 9 — E2E, env, release notes

### Task 9.1 (removed) — E2E test is **out of scope for this plan**

Rationale: AGENTS.md requires `pytest.mark.skip` to carry a TODO comment **and** a ticket reference; this plan has no ticket system, and a skipped placeholder test would violate that rule. The integration scenarios in `tests/integration/test_promoter_pipeline.py` already exercise `Promoter.run` end-to-end against the real `ClusterStore`, real detectors, and the timeline/SSE side effects.

A future hardening pass may add a true E2E that mocks `redis.asyncio.from_url` and exercises the `SignalStream` consumer loop. Track that as separate planning work; this plan ships without it.

The `services/backend/tests/e2e/__init__.py` directory created in Task 1.1 stays (empty) so the future test has somewhere to live.

---

### Task 9.2: `.env.example` updates

**Files:**
- Modify: whichever `.env.example` exists (try repo root, then `services/backend/.env.example`)

- [ ] **Step 1: Verify location.**
```bash
ls -1 .env.example services/backend/.env.example 2>&1 | head
```

- [ ] **Step 2: Append the Promoter section.**

Append to the chosen file:
```
# ---- Auto-Promoter (signal → incident) ----
ODIN_PROMOTER_ENABLED=true
ODIN_PROMOTER_FIRMS_ENABLED=true
ODIN_PROMOTER_FIRMS_MIN_HITS=3
ODIN_PROMOTER_FIRMS_WINDOW_SEC=86400
ODIN_PROMOTER_FIRMS_BUCKET_DEG=0.1
# Severity burst is non-spatial; ENABLE ONLY AFTER frontend supports map:no_pin
ODIN_PROMOTER_SEVERITY_ENABLED=false
ODIN_PROMOTER_SEVERITY_MIN_HITS=5
ODIN_PROMOTER_SEVERITY_WINDOW_SEC=900
ODIN_PROMOTER_TELEGRAM_ENABLED=true
ODIN_PROMOTER_TELEGRAM_MIN_HITS=3
ODIN_PROMOTER_TELEGRAM_WINDOW_SEC=1800
ODIN_PROMOTER_TELEGRAM_JACCARD_THRESHOLD=0.55
ODIN_PROMOTER_TELEGRAM_JACCARD_THRESHOLD_DOMAIN=0.45
# TEI-embedding path is a v1.1 placeholder — keep false in v1
ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED=false
# GDELT default-off until payload schema is verified
ODIN_PROMOTER_GDELT_ENABLED=false
ODIN_PROMOTER_GDELT_MIN_HITS=3
ODIN_PROMOTER_GDELT_WINDOW_SEC=3600
ODIN_PROMOTER_QUIET_WINDOW_SEC=900
ODIN_PROMOTER_SWEEPER_TICK_SEC=60
ODIN_PROMOTER_SILENCE_COOLDOWN_SEC=3600
```

- [ ] **Step 3: Commit.**
```bash
git add <path-to-env-example>
git commit -m "docs(env): document auto-promoter env vars"
```

---

### Task 9.3: Final smoke + release-notes bullet

**Files:**
- Modify: `docs/CONTAINER-STATUS.md` (add bullet)
- Final repo-wide test run.

- [ ] **Step 1: Run the full backend test suite + lint.**
```bash
cd services/backend && uv run pytest -q && uv run ruff check app/ tests/
```
Expected: green.

- [ ] **Step 2: Add release-notes bullet.**

Append to `docs/CONTAINER-STATUS.md` (or wherever release notes live in this project; check by inspection):
```markdown
### 2026-05-19 — Auto-Promoter v1 landed

- New backend lifespan task observes `/api/signals/stream` and promotes
  qualifying signals to incidents.
- Detectors enabled by default: FIRMS Geo-Cluster, Telegram Topic Cluster.
- Detectors default-off in v1: Severity Burst (waits on frontend `map:no_pin`),
  GDELT Tone Spike (waits on payload schema verification).
- Admin inspector: `GET /api/incidents/_admin/promoter`.
- E2E test (mocked Redis XREAD → SSE assertion) deferred to a follow-up plan;
  integration coverage in `tests/integration/test_promoter_pipeline.py` is the
  highest-level test in v1.
- See `docs/superpowers/specs/2026-05-19-incident-auto-promoter-design.md`.
```

- [ ] **Step 3: Commit.**
```bash
git add docs/CONTAINER-STATUS.md
git commit -m "docs: release notes for auto-promoter v1"
```

---

## Verification matrix (run after the last task)

```bash
# Backend tests
cd services/backend && uv run pytest -q
# Lint
cd services/backend && uv run ruff check app/services/incident_promoter app/routers/incidents.py app/services/incident_store.py
# Boot smoke
cd services/backend && uv run python -c "from app.main import app; print('ok')"
# Real-world smoke (requires running stack)
curl -s http://localhost:8080/api/incidents/_admin/promoter -H "X-Admin-Token: $INCIDENTS_ADMIN_TOKEN" | jq
```

