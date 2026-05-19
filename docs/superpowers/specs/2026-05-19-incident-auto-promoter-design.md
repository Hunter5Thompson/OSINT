# Incident Auto-Promoter — Design

- **Status:** Draft for review
- **Date:** 2026-05-19
- **Author:** RT + Claude (brainstorm)
- **Scope:** Backend feature — automatic promotion of signals to incidents
- **Implements:** Closes the gap between live `/api/signals/stream` and the War Room incident surface

---

## 1. Problem

Today the War Room is incident-driven (`useIncidents` → `/api/incidents/stream`), but incidents only enter the database via `POST /api/incidents/_admin/trigger` — a manual stub explicitly flagged in code as *"deliberate stub for v1 — real pattern detection is …"*.

Signals are flowing live: RSS, FIRMS, GDELT, Telegram, etc. accumulate in Redis stream `events` and surface in the Hugin feed. None of them turn into incidents. Result: the War Room is empty unless an analyst manually fires the admin endpoint.

This spec defines an **Auto-Promoter** — a backend subsystem that watches the signal stream, applies a small set of pattern detectors, and creates / updates / closes incidents through the existing `incident_store`. No schema changes, no new persistence, no LLM dependency for the core path.

## 2. Goals / Non-Goals

**Goals (v1)**
- Convert qualifying signals into incidents automatically.
- Four detectors: FIRMS geo-cluster, Severity burst, Telegram topic cluster, GDELT tone spike.
- Update an existing incident when more signals hit the same cluster (no toast spam).
- Auto-close clusters after 15 min of silence.
- Respect analyst overrides (`promote`, `silence`).
- Crash-resistant: a misbehaving detector must not take the backend down.
- Observable via structlog.

**Non-Goals**
- LLM-based classification of signal type (the codebook is a separate concern).
- Per-region severity bursts (v1 is a single global burst lane).
- Persistent cluster state (in-memory only; restart rehydrates from Neo4j).
- Prometheus / OTel metrics (structlog-only; metrics are a follow-up).
- TEI-embedding-based Telegram clustering (skeleton + flag only; activated in v1.1).
- Frontend `map:no_pin` rendering (separate frontend PR).

## 3. Architecture

```
Redis Stream "events"
       │
       ▼
SignalStream (existing — ring buffer + Redis consumer)
       │
       │  subscribe() → asyncio.Queue
       ▼
Promoter.run()  (FastAPI lifespan task)
       │
       ├── for each envelope:
       │     for det in detectors:
       │         hit = det.detect(envelope) → ClusterHit | None
       │         if hit: cluster_store.handle(hit)
       │
       └── Sweeper.loop()  (60s tick)
             for state in cluster_store.iter_owned():
                 if quiet > 15min:
                     if state.status == "open":
                         close_incident() + publish("incident.close")
                     drop state from store

ClusterStore (in-memory, asyncio.Lock-protected)
       │
       ▼
incident_store.create_incident / apply_signal_update / close_incident
       │
       ▼
Neo4j  +  incident_event_stream.publish(...)
       │
       ▼
SSE /api/incidents/stream → frontend
```

### 3.1 Module Layout

```
services/backend/app/services/incident_promoter/
├── __init__.py
├── promoter.py          # Promoter — orchestrates detectors + sweeper
├── cluster_store.py     # ClusterStore — in-memory cluster lifecycle
├── detectors/
│   ├── __init__.py
│   ├── base.py          # Detector protocol + ClusterHit dataclass
│   ├── firms.py
│   ├── severity.py
│   ├── telegram.py
│   └── gdelt.py
└── config.py            # PromoterConfig (env-driven)
```

### 3.2 Touched Existing Modules

- `app/main.py` — lifespan starts/stops `Promoter` task and `Sweeper` task.
- `app/services/incident_store.py` — adds **two** methods and tightens **one**:
  - `apply_signal_update(incident_id, *, timeline_event, severity, sources_to_merge, layer_hints_to_merge) -> Incident` — atomic write covering all four mutations in a single Cypher transaction.
  - `list_owned_for_rehydrate() -> list[Incident]` — returns incidents whose `layer_hints` contain `auto_promoter:v1` (uses existing `INCIDENT_LIST_OPEN` + Python filter; no new Cypher).
  - `close_incident(incident_id)` — must become **idempotent**: return current record if status ∈ {`closed`, `silenced`, `promoted`}, do not error. Signature stays `Incident | None`.
- `app/routers/incidents.py` — adds `GET /api/incidents/_admin/promoter` behind `Depends(_require_admin)`. **Must be declared before** `/{incident_id}` per existing router comment.

## 4. Detector Contract

### 4.1 Protocol

```python
class Detector(Protocol):
    id: str               # "firms" | "severity" | "telegram" | "gdelt"
    enabled: bool

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None: ...
```

Detectors are **stateful but side-effect-free**: they may hold sliding-window deques or LRU centroids internally, but **never** mutate `ClusterStore` or Neo4j directly. Output is a `ClusterHit` or `None`.

```python
@dataclass(frozen=True)
class ClusterHit:
    cluster_key: str
    detector_id: str
    incident_kind: str
    title: str
    severity: Severity                       # "low" | "elevated" | "high" | "critical"
    coords: tuple[float, float] | None       # None = non-spatial
    location: str
    sources_to_merge: list[str]
    layer_hints_to_merge: list[str]
    timeline_event: IncidentTimelineEvent
    contributing_signal_ids: list[str]
```

### 4.2 Cluster Keys

| Detector | Cluster Key | Notes |
|---|---|---|
| firms | `firms:geo:<lat_b>:<lon_b>` with `round(coord, 1)` → ~11 km cell | Coords parsed via regex on FIRMS URL `@<lat>,<lon>,<zoom>z`. Unparsable URL → no hit. |
| severity | `severity:global` | Single global burst lane in v1. |
| telegram | `telegram:topic:<centroid_hash>` | Centroid is normalized title 5-gram set; hash = sha1(sorted_tokens)[:12]. |
| gdelt | `gdelt:geo:<lat_b>:<lon_b>:<actor1>` with `round(coord, 0.5)` → ~55 km cell | GDELT geocoding is coarse; bucket reflects that. |

### 4.3 Detector Specs

#### FIRMS Geo-Cluster
- **Trigger:** ≥3 FIRMS signals in same `firms:geo:*` bucket within 24 h.
- **Initial severity:** `high`. Escalate to `critical` at ≥10 hits.
- **State:** none (each signal is checked against the ClusterStore directly via the bucket key).
- **Coord parse:** Regex `@(?P<lat>-?\d+\.\d+),(?P<lon>-?\d+\.\d+),` on `payload.url`.
- **Source merge:** `["FIRMS · VIIRS_SNPP_NRT"]` (canonicalized).
- **Layer hints:** `["firms", "events", "auto_promoter:v1", "cluster:<key>"]`.

#### Severity Burst
- **Trigger:** ≥5 signals with `severity ∈ {high, critical}` within 15 min, any source.
- **Initial severity:** `high`. Escalate to `critical` at ≥10.
- **State:** internal deque `[(ts, severity, event_id)]`, pruned on every call.
- **Coords:** `None` → ClusterStore resolves to `(0.0, 0.0)` + `map:no_pin` layer hint.
- **DEFAULT: DISABLED** in v1 (`ODIN_PROMOTER_SEVERITY_ENABLED=false`). Enable only after Frontend supports `map:no_pin`. Documented in release notes.

#### Telegram Topic Cluster (Shingles v1)
- **Trigger:** ≥3 signals with `source == "telegram"` and matching topic within 30 min.
- **Matching rule:** normalize title (lowercase, strip URLs, strip non-alnum), compute 5-gram token set, **Jaccard ≥ 0.55** against the nearest active centroid. Same URL domain → threshold lowered to **0.45** (domain-match boost).
- **State:** LRU of up to 50 active centroids `{vector, cluster_key, last_seen_ts, hit_count}`.
- **Initial severity:** `elevated`. Escalate: `high` at ≥5, `critical` at ≥10.
- **Embeddings path:** if `ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED=true`, log warning and **disable detector** (skeleton only, no network in v1). Test covers this.

#### GDELT Tone Spike
- **Trigger:** ≥3 GDELT signals in same `gdelt:geo:*:*` bucket within 60 min with `abs(tone) ≥ 7`.
- **Initial severity:** `elevated`. Escalate: `high` at ≥10 mentions OR `abs(tone) ≥ 9`.
- **State:** internal deque per bucket.
- **DEFAULT: DISABLED** in v1 (`ODIN_PROMOTER_GDELT_ENABLED=false`). Planning task: verify real GDELT payload schema (`actor1_geo_lat/lon`, `tone`, `mention_count`). Enable only after schema confirmation.

## 5. ClusterStore Lifecycle

```python
@dataclass
class ClusterState:
    cluster_key: str
    incident_id: str
    detector_id: str
    severity: Severity
    coords: tuple[float, float]
    hit_count: int
    last_signal_ts: datetime
    created_ts: datetime
    contributing_signal_ids: list[str]    # bounded 50, in-memory
    incident_status: Literal["open", "promoted"]   # tracks external state
    silenced_until: datetime | None       # cooldown after silence
```

```python
class ClusterStore:
    _by_key: dict[str, ClusterState]
    _by_incident_id: dict[str, str]
    _reserving: set[str]                  # in-flight create keys
    _lock: asyncio.Lock
    _clock: Callable[[], datetime]
```

### 5.1 handle(hit) — Phased Locking

```
Phase 1 (under lock):
    existing = _by_key.get(hit.cluster_key)

    if existing is None:
        if hit.cluster_key in _reserving:
            log("promoter_race_dropped"); return       # race tolerance
        _reserving.add(hit.cluster_key)
        action = "create"
    elif existing.incident_status == "promoted":
        existing.last_signal_ts = clock()              # internal only
        log("promoter_promoted_absorb"); return
    elif existing.silenced_until and clock() < existing.silenced_until:
        log("promoter_cluster_silenced"); return
    else:
        action = "update"

Phase 2 (outside lock — I/O):
    if action == "create":
        payload = build_create_request(hit)             # resolves coords + layer_hints
        incident = await incident_store.create_incident(payload)
    else:  # update
        new_severity = apply_escalation_rule(...)
        incident = await incident_store.apply_signal_update(...)

Phase 3 (under lock — finalize):
    if action == "create":
        _by_key[hit.cluster_key] = ClusterState(...)
        _by_incident_id[incident.id] = hit.cluster_key
        _reserving.discard(hit.cluster_key)
        publish("incident.open", incident)
    else:
        existing.hit_count += 1
        existing.last_signal_ts = clock()
        existing.severity = new_severity
        existing.contributing_signal_ids = (existing.contributing_signal_ids + hit.contributing_signal_ids)[-50:]
        publish("incident.update", incident)
```

**Known race:** two hits for the same novel cluster_key arriving in the gap between Phase 1 and Phase 3 of the first hit. Second hit is dropped (`promoter_race_dropped`). At observed signal rates this is rare; explicitly accepted as v1 simplification.

### 5.2 Promote semantics

When the analyst calls `POST /incidents/{id}/promote`:
- Neo4j status → `promoted`.
- The next hit at the cluster sees `existing.incident_status == "promoted"` and is **silently absorbed** (only `last_signal_ts` updated, no Timeline, no SSE, no new incident).
- **Note:** the Promoter does not actively watch the `incident.promote` SSE — it discovers the promotion lazily on the next hit. For v1 this is acceptable. If needed in v1.1, the Promoter can subscribe to the incident event stream.
- After 15 min of quiet, the Sweeper drops the `ClusterState` from the store. The promoted incident **stays promoted in Neo4j**; the Sweeper does not auto-close it.

### 5.3 Silence semantics

When the analyst calls `POST /incidents/{id}/silence`:
- Neo4j status → `silenced`.
- Next hit at the cluster: ClusterStore sets `silenced_until = clock() + 1h`, drops the existing ClusterState (silenced incident is closed for the Promoter).
- Hits during cooldown are dropped with `promoter_cluster_silenced` log.
- After cooldown expires, the next hit creates a fresh incident under the same cluster_key.
- Cooldown is **in-memory only** — restart loses it. Accepted v1 trade-off.

### 5.4 Sweeper (60 s tick)

```
async def sweeper_loop():
    while not stop_event.is_set():
        await asyncio.sleep(60)
        async with cluster_store._lock:
            now = clock()
            candidates = [s for s in _by_key.values()
                          if (now - s.last_signal_ts) > QUIET_WINDOW]
        for state in candidates:
            if state.incident_status == "open":
                try:
                    closed = await incident_store.close_incident(state.incident_id)
                    publish("incident.close", closed)
                except Exception as exc:
                    log.warning("promoter_close_failed", incident_id=state.incident_id, error=str(exc))
                    continue                            # retry next tick
            # promoted clusters are silently dropped, no DB write
            async with cluster_store._lock:
                _by_key.pop(state.cluster_key, None)
                _by_incident_id.pop(state.incident_id, None)
```

### 5.5 Rehydrate — Subscribe First, Then Rehydrate

`Promoter.run()` is composed of three testable methods:

- `_subscribe()` — registers an `asyncio.Queue` with `SignalStream`, stores it as `self._queue`.
- `_rehydrate()` — reads owned incidents from Neo4j, populates `ClusterStore`.
- `_drain_loop()` — endless `await self._queue.get()` → `_process(envelope)` loop.
- `_drain_one()` — internal helper that pulls one envelope and processes it (for tests).

```python
async def run():
    await self._subscribe()                              # PHASE A: buffer starts
    try:
        owned = await incident_store.list_owned_for_rehydrate()
        for incident in owned:
            cluster_key = _extract_cluster_key(incident.layer_hints)
            if cluster_key is None: continue
            detector_id = cluster_key.split(":")[1]
            cluster_store._by_key[cluster_key] = ClusterState(
                cluster_key=cluster_key,
                incident_id=incident.id,
                detector_id=detector_id,
                severity=incident.severity,
                coords=incident.coords,
                hit_count=len(incident.timeline),
                last_signal_ts=_estimate_last_ts(incident),
                created_ts=incident.trigger_ts,
                contributing_signal_ids=[],
                incident_status=incident.status if incident.status in {"open","promoted"} else "open",
                silenced_until=None,
            )
        # PHASE B: drain queue — every envelope now sees populated store
        await self._drain_loop()
    finally:
        self._unsubscribe()
```

`_estimate_last_ts(incident)`:
- If `incident.timeline` is non-empty: `incident.trigger_ts + timedelta(seconds=max(e.t_offset_s for e in timeline))`.
- If `incident.timeline` is empty: `incident.trigger_ts` (oldest possible — Sweeper will close at next tick).

`_extract_cluster_key(layer_hints)`: returns the **first** hint matching `cluster:*`; returns `None` if no such hint exists (the incident is then skipped during rehydrate with `promoter_rehydrate_skipped` log, reason=`no_cluster_marker`).

Since `IncidentTimelineEvent.t_offset_s` is often small (most timeline entries describe events within minutes of trigger), restart-rehydrated incidents tend to be swept quickly. This is **intentional** — prevents zombie clusters from infinite restart accumulation.

**Buffer overflow risk:** SignalStream queue is `maxsize=1000`. If rehydrate (Neo4j list ~<500 records) somehow takes longer than 1000 signals' worth of time, the queue overflows and signals are dropped. At observed rates and Neo4j list timings (<100 ms), this is impossible. Documented as accepted boundary.

## 6. Configuration

`PromoterConfig` in `app/services/incident_promoter/config.py`, pydantic `BaseSettings` style, env-prefixed `ODIN_PROMOTER_`.

| Env Var | Default | Notes |
|---|---|---|
| `ODIN_PROMOTER_ENABLED` | `true` | Master kill-switch. |
| `ODIN_PROMOTER_FIRMS_ENABLED` | `true` | |
| `ODIN_PROMOTER_FIRMS_MIN_HITS` | `3` | |
| `ODIN_PROMOTER_FIRMS_WINDOW_SEC` | `86400` | 24 h |
| `ODIN_PROMOTER_FIRMS_BUCKET_DEG` | `0.1` | ~11 km |
| `ODIN_PROMOTER_SEVERITY_ENABLED` | **`false`** | Default-off until frontend `map:no_pin` lands. |
| `ODIN_PROMOTER_SEVERITY_MIN_HITS` | `5` | |
| `ODIN_PROMOTER_SEVERITY_WINDOW_SEC` | `900` | 15 min |
| `ODIN_PROMOTER_TELEGRAM_ENABLED` | `true` | |
| `ODIN_PROMOTER_TELEGRAM_MIN_HITS` | `3` | |
| `ODIN_PROMOTER_TELEGRAM_WINDOW_SEC` | `1800` | 30 min |
| `ODIN_PROMOTER_TELEGRAM_JACCARD_THRESHOLD` | `0.55` | Domain boost → `0.45`. |
| `ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED` | `false` | Skeleton flag — true currently disables detector with warn-log. |
| `ODIN_PROMOTER_GDELT_ENABLED` | **`false`** | Default-off until payload schema verified. |
| `ODIN_PROMOTER_GDELT_MIN_HITS` | `3` | |
| `ODIN_PROMOTER_GDELT_WINDOW_SEC` | `3600` | 60 min |
| `ODIN_PROMOTER_QUIET_WINDOW_SEC` | `900` | 15 min — drives Sweeper. |
| `ODIN_PROMOTER_SWEEPER_TICK_SEC` | `60` | |
| `ODIN_PROMOTER_SILENCE_COOLDOWN_SEC` | `3600` | 1 h |

`.env.example` updated with all keys + comments.

## 7. Lifespan & Error Handling

### 7.1 Lifespan wiring (`app/main.py`)

```python
@asynccontextmanager
async def lifespan(app):
    # existing signal/incident bootstrap...
    cluster_store = ClusterStore(clock=lambda: datetime.now(UTC))
    app.state.cluster_store = cluster_store

    config = PromoterConfig.from_env()
    promoter = Promoter(
        signal_stream=get_signal_stream(),
        cluster_store=cluster_store,
        incident_store=incident_store,
        incident_event_stream=get_incident_stream(),
        config=config,
        clock=cluster_store._clock,
    )
    promoter_task = sweeper_task = None
    if config.enabled:
        promoter_task = asyncio.create_task(promoter.run(), name="promoter")
        sweeper_task = asyncio.create_task(promoter.sweeper_loop(), name="promoter-sweeper")

    try:
        yield
    finally:
        promoter.request_stop()
        for t in (promoter_task, sweeper_task):
            if t is None: continue
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        # existing teardown
```

### 7.2 Error matrix

| Failure | Behavior |
|---|---|
| Detector raises in `detect()` | Log `promoter_detector_error`, skip detector for this envelope, continue with others. |
| `incident_store.create_incident` raises | `_reserving.discard(key)`; drop hit; log `promoter_create_failed`. Next hit retries. |
| `apply_signal_update` raises | ClusterState unchanged; log `promoter_update_failed`. Next hit retries. |
| `publish(...)` raises | Log + swallow. Neo4j has been written; frontend recovers on next refresh / rehydrate. |
| `close_incident` raises in Sweeper | ClusterState left in place; next tick retries. |
| Outer run-loop raises | `except Exception: log + sleep(1) + continue`. Task is never allowed to die. |
| Backend shutdown mid-write | Lifespan cancels tasks; Cypher templates are MERGE-idempotent; next restart rehydrates cleanly. |

## 8. Observability

Structlog only — no Prometheus / OTel in v1.

| Event | Key Fields |
|---|---|
| `promoter_started` | `detectors_enabled`, `rehydrated_count` |
| `promoter_cluster_opened` | `cluster_key`, `detector_id`, `incident_id`, `severity` |
| `promoter_cluster_updated` | `cluster_key`, `incident_id`, `hit_count`, `severity` |
| `promoter_cluster_closed` | `cluster_key`, `incident_id`, `quiet_seconds`, `final_hit_count` |
| `promoter_cluster_silenced` | `cluster_key`, `incident_id`, `cooldown_seconds` |
| `promoter_promoted_absorb` | `cluster_key`, `incident_id` |
| `promoter_detector_error` | `detector_id`, `error`, `envelope_event_id` |
| `promoter_create_failed` | `cluster_key`, `error` |
| `promoter_update_failed` | `cluster_key`, `incident_id`, `error` |
| `promoter_close_failed` | `incident_id`, `error` |
| `promoter_race_dropped` | `cluster_key` |
| `promoter_rehydrate_skipped` | `incident_id`, `reason` |

### 8.1 Admin inspector

`GET /api/incidents/_admin/promoter` (behind `Depends(_require_admin)`, declared **before** `/{incident_id}` in router):

```json
{
  "enabled_detectors": ["firms", "telegram"],
  "config": { "...summary..." },
  "active_clusters": [
    {
      "cluster_key": "firms:geo:48.0:37.8",
      "incident_id": "inc-…",
      "detector_id": "firms",
      "incident_status": "open",
      "severity": "high",
      "hit_count": 4,
      "last_signal_ts": "2026-05-19T19:34:11Z",
      "created_ts": "2026-05-19T18:50:02Z"
    }
  ],
  "cooldowns": [
    { "cluster_key": "telegram:topic:…", "silenced_until": "2026-05-19T20:30:00Z" }
  ],
  "reserving_now": ["..."]
}
```

## 9. Test Strategy

No `freezegun`. `Promoter` and `ClusterStore` accept `clock: Callable[[], datetime]`. Tests use `FakeClock` (mutable wrapper).

### 9.1 Unit (~25 tests)

**Per detector (4 modules × ~3 cases):**
- FIRMS: URL coord parse (happy + malformed); bucket boundaries (negatives); ClusterHit fields correct.
- Severity: deque pruning; threshold reached / not reached; `coords=None` set.
- Telegram: title normalization; 5-gram Jaccard correctness; domain-match boost; LRU eviction; **embeddings flag = true → detector disables itself, no network call**.
- GDELT: feature flag off → no hit; payload field mapping; geo+actor bucket.

**ClusterStore (~6 cases):** novel key → create+finalize; existing key → update; promoted state → silent absorb; silenced cooldown → silent drop; `_reserving` race → `promoter_race_dropped`; Sweeper: stale open → closed, stale promoted → dropped (no DB), non-stale → unchanged.

**Helpers:** `max_severity`, `apply_escalation_rule`, `_extract_cluster_key`, `_estimate_last_ts`.

### 9.2 Integration (~6 tests, `tests/integration/test_promoter_pipeline.py`)

Uses `FakeIncidentStore` (in-process dict) + `FakeIncidentEventStream` (collecting list) + real ClusterStore + real Detectors + `FakeClock`:

1. **FIRMS cluster builds** — 3 FIRMS signals same bucket → 1 `incident.open` + 2 `incident.update`. Advance clock 16 min → Sweeper emits `incident.close`.
2. **Severity burst** — 5 high signals from 3 sources in 14 min → 1 `incident.open` with `coords=(0,0)` and `layer_hints` containing `map:no_pin`. (Test forces `SEVERITY_ENABLED=true`.)
3. **Telegram cluster** — 4 titles with token overlap + 1 unrelated → 1 incident with 3 updates + 1 unmatched signal.
4. **Promote mid-cluster** — 2 FIRMS → open, simulate `incident.promote` (set state.incident_status), 2 more FIRMS same bucket → no updates, no new incident. Clock advance 16 min → cluster dropped from store, promoted incident remains promoted.
5. **Silence mid-cluster** — 2 Telegram → open, simulate `incident.silence`, 1 more hit → dropped. Advance 61 min, new hit → fresh incident.
6. **Rehydrate-then-subscribe** — Pre-seed FakeIncidentStore with 1 open auto-incident. Construct Promoter; call `_subscribe()`; enqueue a matching FIRMS envelope via the SignalStream subscribe queue; call `_rehydrate()`; call `_drain_one()`. Assert: 1 `incident.update`, **0** `incident.open`. (`Promoter.run` is structured as three composable async methods — `_subscribe`, `_rehydrate`, `_drain_loop` — so this test does not need mocked timing.)

### 9.3 E2E (1 test, `tests/e2e/test_promoter_e2e.py`)

Real FastAPI TestClient + real SignalStream singleton + `redis.asyncio` mocked via `AsyncMock`. `incident_store` overridden to FakeIncidentStore. Push 3 FIRMS XREAD responses; subscribe to `/api/incidents/stream` SSE; verify frame sequence `incident.open` → `incident.update` × 2.

### 9.4 Out of test scope

- Real Neo4j Cypher (covered by `incident_store` tests).
- TEI embedding path (not active in v1 code).
- Frontend `map:no_pin` rendering (separate PR).
- Rehydrate buffer overflow at >1000 signals (documented as accepted boundary).

## 10. Risks & Open Items

| Risk | Mitigation |
|---|---|
| Severity-Burst incidents appearing at Null Island in the UI | **Default-off in v1.** Frontend `map:no_pin` is a follow-up PR; enable Severity only after frontend lands. |
| GDELT signal payload schema unknown | **Default-off in v1.** Planning task: inspect `services/data-ingestion/feeds/gdelt_collector.py` to confirm `actor1_geo_lat/lon`, `tone`, `mention_count` field availability. Enable only after confirmation. |
| Telegram Jaccard too sticky in noisy channels | Conservative defaults (0.55, 0.45 with domain boost). Operator can tune via env without code change. |
| Phase-1/Phase-3 race drops occasional hits | At observed rates (~10/min total), drop probability is < 1%. Accepted; can be revisited if logs show `promoter_race_dropped` clustering. |
| Cooldown lost on restart | Accepted v1 trade-off (in-memory only). |
| Promoter discovers `promote` lazily (on next hit), not in real time | Hits between promote and Sweeper-drop merely update `last_signal_ts` in-memory. If real-time matters in v1.1, subscribe Promoter to the incident event stream. |
| Restart-rehydrated incidents may auto-close quickly | Intentional — prevents zombie clusters. Documented. |
| Backend gets a new responsibility (pattern detection) on top of API serving | Acceptable for v1 scale; if signals/sec exceeds ~50, consider extracting to a dedicated worker. |

## 11. Out of Scope (Explicit)

- LLM-based codebook classification for `signal.type`.
- Multi-region severity bursts.
- Geo-aware incident merging across detector types (e.g., FIRMS + Telegram at same coords).
- Persistent cluster state (Redis-backed or Neo4j-backed).
- Analyst configurability via UI (env-only in v1).
- Backfill / replay over historic signals.
- Audit trail of contributing signals in Neo4j.

## 12. Implementation Phases (for the plan)

The implementation plan (`writing-plans` skill) will break this into:

1. Skeleton & contract — `Detector` protocol, `ClusterHit`, `PromoterConfig`, `ClusterStore` shell, lifespan wiring (no detectors yet, no-op Promoter behind master flag).
2. `apply_signal_update` + idempotent `close_incident` in `incident_store` (+ tests).
3. FIRMS detector + integration test #1.
4. ClusterStore full lifecycle: Promote, Silence, Sweeper, Rehydrate (+ tests #4, #5, #6).
5. Telegram detector (shingles) + test #3 + embeddings-flag-disabled test.
6. Severity detector (default-off) + test #2.
7. GDELT detector skeleton (default-off, schema unverified) + smoke test.
8. Admin inspector endpoint + smoke test.
9. E2E test + `.env.example` + release notes.
