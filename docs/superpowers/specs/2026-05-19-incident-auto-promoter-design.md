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
                         close_incident(id, status=CLOSED) + publish("incident.close")
                     drop state from store + fan out on_cluster_terminated(key)

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

- `app/main.py` — lifespan starts/stops `Promoter` task and `Sweeper` task; attaches `ClusterStore` to `app.state`.
- `app/services/incident_store.py` — adds **two** methods and tightens **one**:
  - `apply_signal_update(incident_id, *, timeline_event, severity, sources_to_merge, layer_hints_to_merge) -> Incident` — atomic write covering all four mutations in a single Cypher transaction.
  - `list_owned_for_rehydrate() -> list[Incident]` — returns incidents whose `layer_hints` contain `auto_promoter:v1` (uses existing `INCIDENT_LIST_OPEN` + Python filter; no new Cypher).
  - `close_incident(incident_id, status)` — must become **idempotent**: return current record (unchanged) if it is already in a terminal state ∈ {`closed`, `silenced`, `promoted`}. Signature stays `(incident_id, status: IncidentStatus, when: datetime | None = None) -> Incident | None` (matches existing code; Sweeper always passes `status=IncidentStatus.CLOSED` explicitly).
- `app/routers/incidents.py`:
  - Adds `GET /api/incidents/_admin/promoter` behind `Depends(_require_admin)`. **Must be declared before** `/{incident_id}` per existing router comment.
  - **`promote_incident` and `silence_incident` are wired to the ClusterStore:** after a successful Neo4j write, the handler reads `cluster_store = getattr(request.app.state, "cluster_store", None)` and (if present) calls `cluster_store.mark_promoted(incident_id)` or `mark_silenced(incident_id, until=now+cooldown)`. No-op when the Promoter is disabled or the cluster is unknown to the store.

## 4. Detector Contract

### 4.1 Protocol

```python
class Detector(Protocol):
    id: str               # "firms" | "severity" | "telegram" | "gdelt"
    enabled: bool

    def detect(self, envelope: SignalEnvelope) -> ClusterHit | None: ...

    def on_cluster_terminated(
        self,
        cluster_key: str,
        suppress_until: datetime | None = None,
    ) -> None: ...
        # Called by ClusterStore when a cluster ends. Resets the
        # detector's per-bucket pre-trigger state so the next signal
        # starts a fresh accumulation window.
        #
        # `suppress_until=None` (default) — natural end (Sweeper close
        #   or promote-quiet drop). Future signals at this key may
        #   immediately re-enter pre-trigger accumulation.
        #
        # `suppress_until=datetime` — analyst silence. The detector
        #   MUST track this per-key and discard any signal whose
        #   cluster_key is still suppressed when `detect()` is called.
        #   Detector clears the suppression lazily on the next call
        #   whose clock() >= suppress_until.
```

The Detector receives the same `clock: Callable[[], datetime]` as the Promoter via its constructor, so suppression timing is testable without real time.

Detectors are **stateful but side-effect-free** w.r.t. ClusterStore / Neo4j: they may hold per-bucket sliding-window deques, an `ignited: set[cluster_key]` flag, and a `_suppressed_until: dict[cluster_key, datetime]` map internally, but **never** mutate `ClusterStore` or Neo4j directly. Output is a `ClusterHit` or `None`.

**Threshold semantics (Option A — detector-side accumulation):**

For each incoming envelope the detector first computes its `cluster_key`, then evaluates in order:

1. **Suppressed?** If `_suppressed_until.get(cluster_key)` is set and `clock() < that` → return `None` (do **not** even append to the deque — otherwise pre-trigger state would leak past the cooldown). If set but expired → pop the entry, fall through.
2. **Accumulate.** Append `(ts, event_id, …)` to the bucket deque; prune by detector window.
3. **Decide:**
   - If not ignited and `len(deque) < min_hits` → return `None`.
   - If not ignited and `len(deque) >= min_hits` → mark ignited; return a ClusterHit whose `contributing_signal_ids` lists all event_ids currently in the deque (used for in-memory audit; see §5 on the **single** trigger Timeline entry).
   - If ignited → return a ClusterHit for the single new signal (this becomes an update).

A `ClusterHit` therefore always represents an actionable event. ClusterStore decides "create vs. update" purely from whether `cluster_key` already exists in `_by_key`.

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
    timeline_event: IncidentTimelineEvent    # ALWAYS exactly one entry — see §5.0 below
    contributing_signal_ids: list[str]       # ≥ min_hits at ignition, len==1 on update
                                             # (audit / in-memory only — does NOT shape Neo4j timeline)
```

**Termination callback:** at startup, the Promoter registers each detector's `on_cluster_terminated` as a listener on `ClusterStore` via `cluster_store.add_termination_listener(detector.on_cluster_terminated)`. When ClusterStore drops a cluster, it fans the callback out to all registered detectors with the appropriate `suppress_until`:

| Termination cause | Callback args |
|---|---|
| Sweeper close (quiet window) | `on_cluster_terminated(key)` — no suppression |
| Promote-quiet drop | `on_cluster_terminated(key)` — no suppression |
| Analyst silence | `on_cluster_terminated(key, suppress_until=<cooldown_end>)` |

Each detector clears its bucket state and (in the silence case) records the suppression so subsequent signals at that key are dropped at the detector boundary, never reaching `ClusterStore`. The `_cooldowns` map in `ClusterStore` is the second line of defense — if a foreign caller (or a fresh detector instance) somehow emits a `ClusterHit` for a suppressed key, the store still drops it. **Both layers must agree** on the same `suppress_until` value, which is why `mark_silenced` is the single source of that timestamp.

### 4.2 Cluster Keys

| Detector | Cluster Key | Notes |
|---|---|---|
| firms | `firms:geo:<lat_b>:<lon_b>` with `round(coord, 1)` → ~11 km cell | Coords parsed via regex on FIRMS URL `@<lat>,<lon>,<zoom>z`. Unparsable URL → no hit. |
| severity | `severity:global` | Single global burst lane in v1. |
| telegram | `telegram:topic:<centroid_hash>` | Centroid is normalized title 5-gram set; hash = sha1(sorted_tokens)[:12]. |
| gdelt | `gdelt:geo:<lat_b>:<lon_b>:<actor1>` with `round(coord, 0.5)` → ~55 km cell | GDELT geocoding is coarse; bucket reflects that. |

### 4.3 Detector Specs

All detectors apply the threshold semantics from §4.1: per-bucket deque, prune by window, emit `ClusterHit` only when ignited or updating.

#### FIRMS Geo-Cluster
- **Trigger threshold:** `len(bucket.deque) >= 3` within 24 h window in same `firms:geo:*` bucket.
- **Initial severity:** `high`. Escalate to `critical` at `hit_count >= 10`.
- **State:** `_buckets: dict[cluster_key, _BucketWindow]` with `deque[(ts, event_id)]` + `ignited: bool`. Pruned on every `detect()` call.
- **Coord parse:** Regex `@(?P<lat>-?\d+\.\d+),(?P<lon>-?\d+\.\d+),` on `payload.url`.
- **Source merge:** `["FIRMS · VIIRS_SNPP_NRT"]` (canonicalized).
- **Layer hints:** `["firms", "events", "auto_promoter:v1", "cluster:<key>"]`.
- **Ignition hit:** `contributing_signal_ids` = all event_ids currently in deque (≥3).
- **Update hit:** `contributing_signal_ids = [envelope.event_id]`, single timeline entry.

#### Severity Burst
- **Trigger threshold:** `len(bucket.deque) >= 5` within 15 min window. Only counts signals with `severity ∈ {high, critical}` (any source).
- **Cluster key:** `severity:global` (single global lane in v1).
- **Initial severity:** `high`. Escalate to `critical` at `hit_count >= 10`.
- **State:** one `_BucketWindow` for the single global key.
- **Coords:** `None` → ClusterStore resolves to `(0.0, 0.0)` + appends `map:no_pin` to `layer_hints`.
- **DEFAULT: DISABLED** in v1 (`ODIN_PROMOTER_SEVERITY_ENABLED=false`). Enable only after Frontend supports `map:no_pin`. Documented in release notes.

#### Telegram Topic Cluster (Shingles v1)
- **Trigger threshold:** `≥3` signals matching same centroid within 30 min window, `source == "telegram"`.
- **Matching rule:** normalize title (lowercase, strip URLs, strip non-alnum), compute 5-gram token set, **Jaccard ≥ 0.55** against the nearest active centroid. Same URL domain → threshold lowered to **0.45** (domain-match boost). No match → new centroid (pre-trigger).
- **State:** LRU of up to 50 active centroids `{tokens, cluster_key, deque, ignited, last_seen_ts}`. LRU eviction by `last_seen_ts`.
- **Initial severity:** `elevated`. Escalate: `high` at `hit_count >= 5`, `critical` at `hit_count >= 10`.
- **Embeddings path:** if `ODIN_PROMOTER_TELEGRAM_EMBEDDINGS_ENABLED=true`, log warning on detector init and **disable detector entirely** (skeleton only, no network in v1). Test covers this.

#### GDELT Tone Spike
- **Trigger threshold:** `≥3` GDELT signals in same `gdelt:geo:*:*` bucket within 60 min with `abs(tone) ≥ 7`.
- **Initial severity:** `elevated`. Escalate: `high` at `hit_count >= 10` mentions OR seeing `abs(tone) >= 9` in any contributing signal.
- **State:** `_BucketWindow` per cluster_key, plus tone tracking.
- **DEFAULT: DISABLED** in v1 (`ODIN_PROMOTER_GDELT_ENABLED=false`). Planning task: verify real GDELT payload schema (`actor1_geo_lat/lon`, `tone`, `mention_count`). Enable only after schema confirmation.

## 5. ClusterStore Lifecycle

### 5.0 Timeline Contract (Ignition vs. Update)

`IncidentCreateRequest` only carries an `initial_text` for the trigger event today (`incident_store.create_incident` builds a single `IncidentTimelineEvent` at `t_offset_s=0.0`). The Promoter respects this contract — `incident_store` is **not** extended to accept a list of initial timeline events.

- **Ignition incident** (`create_incident`) gets **one** timeline entry: a summary of the cluster, e.g.
  - FIRMS: `"FIRMS cluster ignited · 3 detections in firms:geo:48.0:37.8"`
  - Severity: `"Severity burst · 5 high-severity signals from 3 sources"`
  - Telegram: `"Telegram cluster · 3 matching posts"`
- The 3 contributing event_ids live in `ClusterState.contributing_signal_ids` (in-memory, bounded 50) for audit and the admin inspector. They are **not** persisted to Neo4j as separate timeline entries on open.
- **Update incidents** (`apply_signal_update`) append exactly one timeline entry per qualifying signal — that's the existing append-only path and remains the normal mode of timeline growth.

`ClusterHit.timeline_event` always carries this single entry. Build helpers:

```python
def build_ignition_timeline_event(hit: ClusterHit, contributing_count: int) -> IncidentTimelineEvent:
    return IncidentTimelineEvent(
        t_offset_s=0.0,
        kind="trigger",
        text=hit.title,   # detector-supplied summary
        severity=hit.severity,
    )

def build_update_timeline_event(hit: ClusterHit, t_offset_s: float) -> IncidentTimelineEvent:
    return IncidentTimelineEvent(
        t_offset_s=t_offset_s,
        kind="observation",
        text=hit.title,   # detector-supplied per-signal summary
        severity=hit.severity,
    )
```

Detectors construct the summary inline; ClusterStore does not synthesize text.

### 5.1 Data Model

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
```

```python
class ClusterStore:
    _by_key: dict[str, ClusterState]
    _by_incident_id: dict[str, str]
    _reserving: set[str]                          # in-flight create keys
    _cooldowns: dict[str, datetime]               # cluster_key → expires_at (silence)
    _termination_listeners: list[Callable[[str], None]]
    _lock: asyncio.Lock
    _clock: Callable[[], datetime]
```

**Why `_cooldowns` is a separate dict:** silence drops the `ClusterState` immediately (the incident is closed for the Promoter), but the cooldown must survive that drop so subsequent hits within the cooldown window are still rejected. Mixing cooldown into `ClusterState` would force us to keep zombie states purely to remember "don't open a new one."

**Termination listeners:** detectors register `on_cluster_terminated(cluster_key)` callbacks via `add_termination_listener()`. ClusterStore invokes them on Sweeper-close, promote-quiet-drop, and silence. All registration happens during Promoter init (before any signal is processed) so concurrency on the list is trivial.

### 5.2 handle(hit) — Phased Locking

A `ClusterHit` arriving at `handle()` is already "actionable" by detector contract (threshold met or update for ignited cluster). `handle()` only decides create vs. update vs. drop based on store state.

```
Phase 1 (under lock):
    now = clock()

    # Cooldown check first (survives state-drops from silence)
    cooldown_until = _cooldowns.get(hit.cluster_key)
    if cooldown_until is not None:
        if now < cooldown_until:
            log("promoter_cluster_silenced", cluster_key=hit.cluster_key,
                cooldown_seconds=int((cooldown_until - now).total_seconds()))
            return
        else:
            _cooldowns.pop(hit.cluster_key, None)      # expired — clean up

    existing = _by_key.get(hit.cluster_key)

    if existing is None:
        if hit.cluster_key in _reserving:
            log("promoter_race_dropped"); return       # race tolerance
        _reserving.add(hit.cluster_key)
        action = "create"
    elif existing.incident_status == "promoted":
        existing.last_signal_ts = now                  # internal only
        log("promoter_promoted_absorb"); return
    else:
        action = "update"

Phase 2 (outside lock — I/O):
    if action == "create":
        payload = build_create_request(hit)             # resolves coords + layer_hints
        # Initial timeline is built from hit.contributing_signal_ids (≥ min_hits)
        # by build_create_request; first entry is the trigger event.
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

### 5.3 Promote semantics

When the analyst calls `POST /incidents/{id}/promote`:
1. Router performs the Neo4j status transition `open → promoted` (existing behavior).
2. After the write succeeds, the handler calls:
   ```python
   cluster_store = getattr(request.app.state, "cluster_store", None)
   if cluster_store is not None:
       await cluster_store.mark_promoted(incident_id)
   ```
3. `mark_promoted(incident_id)`:
   - Looks up `cluster_key` via `_by_incident_id`. No-op if absent (manual / non-Promoter incident).
   - Under lock, sets `_by_key[cluster_key].incident_status = "promoted"`.
   - Subsequent hits hit the `incident_status == "promoted"` branch in `handle()` and are silently absorbed (`last_signal_ts` updated, no Timeline, no SSE, no new incident).
4. After 15 min of quiet (no new hits), the Sweeper drops the `ClusterState` from the store and fans out `on_cluster_terminated(cluster_key)` to detectors. The promoted incident **stays promoted in Neo4j**; the Sweeper does not auto-close it.

### 5.4 Silence semantics

When the analyst calls `POST /incidents/{id}/silence`:
1. Router performs the Neo4j status transition `open → silenced` (existing behavior).
2. After the write succeeds, the handler calls:
   ```python
   cluster_store = getattr(request.app.state, "cluster_store", None)
   if cluster_store is not None:
       await cluster_store.mark_silenced(
           incident_id,
           until=clock() + timedelta(seconds=config.silence_cooldown_sec),
       )
   ```
3. `mark_silenced(incident_id, until)`:
   - Looks up `cluster_key` via `_by_incident_id`. No-op if absent.
   - Under lock, removes `_by_key[cluster_key]` and `_by_incident_id[incident_id]`.
   - Writes `_cooldowns[cluster_key] = until`.
   - Fans out `on_cluster_terminated(cluster_key, suppress_until=until)` to detectors **outside the lock** (listeners are local + cheap, but locking around external callbacks is asking for deadlocks). Detectors thereby refuse to even accumulate during the cooldown.
4. While a `_cooldowns` entry is live, every hit at that cluster_key is dropped with `promoter_cluster_silenced` log.
5. When a hit arrives after `_cooldowns[cluster_key]` has expired, Phase 1 cleans up the entry and proceeds normally → a fresh incident may be created.
6. Cooldowns are **in-memory only**; backend restart loses them. Documented v1 trade-off.

### 5.5 Sweeper (60 s tick)

The Sweeper has two responsibilities: close stale clusters and expire stale cooldowns. Both run on every tick.

```
async def sweeper_loop():
    while not stop_event.is_set():
        await asyncio.sleep(config.sweeper_tick_sec)
        await self._sweep_once()

async def _sweep_once():
    now = clock()
    # 1) Identify stale clusters under lock
    async with cluster_store._lock:
        stale = [s for s in _by_key.values()
                 if (now - s.last_signal_ts).total_seconds() > config.quiet_window_sec]
        # 2) Expire cooldowns (no I/O needed)
        expired_cooldowns = [k for k, t in _cooldowns.items() if t <= now]
        for k in expired_cooldowns:
            _cooldowns.pop(k, None)

    # 3) Process stale clusters (DB I/O outside lock)
    for state in stale:
        if state.incident_status == "open":
            try:
                closed = await incident_store.close_incident(
                    state.incident_id,
                    status=IncidentStatus.CLOSED,
                )
                if closed is not None:
                    publish("incident.close", closed)
            except Exception as exc:
                log.warning("promoter_close_failed",
                            incident_id=state.incident_id, error=str(exc))
                continue                                # retry next tick — state stays in store
        # promoted clusters are dropped silently (no DB write)

        async with cluster_store._lock:
            _by_key.pop(state.cluster_key, None)
            _by_incident_id.pop(state.incident_id, None)
        # 4) Fan out termination callback (outside lock — listeners are local + cheap)
        for listener in self._termination_listeners:
            try:
                listener(state.cluster_key)
            except Exception:
                log.warning("promoter_terminate_callback_failed",
                            cluster_key=state.cluster_key)
```

The Sweeper passes `status=IncidentStatus.CLOSED` explicitly to `incident_store.close_incident` — there is no implicit default. Note `close_incident` is idempotent (§3.2): a non-terminal incident is closed; a terminal one is returned unchanged. The Sweeper publishes `incident.close` only when `closed is not None`, so a missing incident does not leak an SSE frame.

### 5.6 Rehydrate — Subscribe First, Then Rehydrate

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
            )
        cluster_store._by_incident_id = {s.incident_id: s.cluster_key for s in cluster_store._by_key.values()}
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
    { "cluster_key": "telegram:topic:…", "cooldown_until": "2026-05-19T20:30:00Z" }
  ],
  "reserving_now": ["..."]
}
```

## 9. Test Strategy

No `freezegun`. `Promoter` and `ClusterStore` accept `clock: Callable[[], datetime]`. Tests use `FakeClock` (mutable wrapper).

### 9.1 Unit (~30 tests)

**Per detector (4 modules × ~4 cases):**
- FIRMS:
  - URL coord parse (happy + malformed → returns None).
  - Pre-trigger: 2 signals in bucket → both return `None`, deque has 2 entries.
  - Ignition: 3rd signal → returns `ClusterHit` with `contributing_signal_ids` of length 3 **and** `timeline_event` is a single ignition-summary entry (text contains `"3 detections"`).
  - Post-ignition update: 4th signal → returns `ClusterHit` with single contributing id and `kind="observation"` timeline entry.
  - `on_cluster_terminated(key)` resets the bucket → next signal restarts pre-trigger accumulation from 0.
  - **Silence suppression**: `on_cluster_terminated(key, suppress_until=clock()+1h)` → next 3 signals in same bucket return `None` and deque stays empty (no accumulation during cooldown). Advance clock past `suppress_until` → next signal accumulates normally; takes 3 signals to ignite.
- Severity:
  - Deque prunes signals older than 15 min.
  - 4 high signals → all None; 5th → ignition hit with `coords=None`.
  - `on_cluster_terminated("severity:global")` clears global window.
- Telegram:
  - Title normalization (URLs, punctuation, casing).
  - 5-gram Jaccard correctness (happy 0.6, edge 0.55, miss 0.3).
  - Domain-match boost lowers threshold to 0.45.
  - LRU eviction at 51st centroid (least-recently-seen evicted, terminates).
  - Ignition vs. update emit pattern (analogous to FIRMS).
  - **Embeddings flag = true → detector logs warning at init, all `detect()` calls return None, no network call.**
- GDELT:
  - Feature flag off → all `detect()` return None.
  - Payload field mapping (`actor1_geo_lat/lon`, `tone`, `mention_count`).
  - geo+actor bucket determinism.
  - Ignition vs. update analog.

**ClusterStore (~8 cases):**
- Novel key → reserves, creates, finalizes, publishes `incident.open`.
- Existing key → updates, publishes `incident.update`.
- `_reserving` race: second concurrent novel hit → `promoter_race_dropped`.
- `mark_promoted(incident_id)`: sets `incident_status="promoted"`; subsequent hit → silent absorb.
- `mark_silenced(incident_id, until)`: drops state, sets `_cooldowns[key]=until`, fires `on_cluster_terminated(key, suppress_until=until)` to all registered listeners (verified with a spy listener).
- Cooldown survives state drop: after `mark_silenced`, synthesize a `ClusterHit` for the suppressed key directly and call `handle()` → dropped with `promoter_cluster_silenced` log; `_cooldowns[key]` still present.
- Cooldown expires: synthesize hit with `clock()` past `until` → cooldown popped, new incident created (path through `create`).
- Sweeper: stale open → close DB + publish + drop + callback; stale promoted → drop + callback only; non-stale → unchanged; expired cooldowns popped on every tick.

**Helpers:** `max_severity`, `apply_escalation_rule` (per-detector escalation curves), `_extract_cluster_key`, `_estimate_last_ts` (with empty timeline fallback), `build_create_request` (coord resolution + `map:no_pin` injection).

### 9.2 Integration (~6 tests, `tests/integration/test_promoter_pipeline.py`)

Uses `FakeIncidentStore` (in-process dict) + `FakeIncidentEventStream` (collecting list) + real ClusterStore + real Detectors + `FakeClock`:

1. **FIRMS cluster builds** — Signals 1+2 into the same bucket → **0** events emitted (pre-trigger). Signal 3 → exactly **1 `incident.open`** whose timeline contains a **single trigger entry** (`"FIRMS cluster ignited · 3 detections in …"`); `ClusterState.contributing_signal_ids` lists all 3. Signal 4 → **1 `incident.update`** appending one timeline entry. Advance clock 16 min, run sweeper → **1 `incident.close`** plus `on_cluster_terminated(key)` (no `suppress_until`) fired on the FIRMS detector.
2. **Severity burst** — Signals 1–4 high → 0 events. Signal 5 → 1 `incident.open` with `coords=(0,0)` and `layer_hints` containing `map:no_pin`. (Test forces `SEVERITY_ENABLED=true` via env override fixture.)
3. **Telegram cluster** — 4 titles with token overlap + 1 unrelated → 1 `incident.open` (at the 3rd matching) + 1 `incident.update` (at the 4th) + 0 events for the unrelated.
4. **Promote mid-cluster via router-style call** — 3 FIRMS → 1 open. Call `cluster_store.mark_promoted(incident_id)` directly (router behavior). 2 more FIRMS same bucket → 0 updates, 0 new incidents (silent absorb). Advance clock 16 min, run sweeper → cluster dropped from store, `on_cluster_terminated` fired, but **no `incident.close` published** (status remains `promoted`).
5. **Silence mid-cluster via router-style call** — 3 Telegram → 1 open. Call `cluster_store.mark_silenced(incident_id, until=clock()+1h)`. Assert: state removed, `_cooldowns[key]` populated, `on_cluster_terminated(key, suppress_until=until)` fired (detector's `_suppressed_until[key]` populated). 1 more matching Telegram during cooldown → detector returns `None` (signal not accumulated), 0 store calls, `promoter_cluster_silenced` log NOT emitted (because no ClusterHit ever reaches the store — this is the **detector-side** drop). Advance clock 61 min; detector's lazy suppression check pops the entry; send fresh signal sequence → 3 signals later, **fresh `incident.open`** under same cluster_key. **Also test the second line of defense**: synthesize a ClusterHit for the suppressed key directly (bypassing the detector) and call `handle()` during cooldown → dropped with `promoter_cluster_silenced` log.
6. **Rehydrate-then-subscribe** — Pre-seed FakeIncidentStore with 1 open auto-incident. Construct Promoter; call `_subscribe()`; enqueue a matching FIRMS envelope via the SignalStream subscribe queue; call `_rehydrate()`; call `_drain_one()`. Assert: 1 `incident.update`, **0** `incident.open`. (`Promoter.run` is structured as four composable async methods — `_subscribe`, `_rehydrate`, `_drain_loop`, `_drain_one` — so this test does not need mocked timing.)

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
| Promote/silence wiring lives in two places (router + ClusterStore) | Router calls `mark_promoted` / `mark_silenced` after a successful Neo4j write. If a future caller writes to Neo4j without going through the router (e.g., a background worker), Promoter state will diverge. Mitigation: only the existing router endpoints write the `promoted` / `silenced` states; this is enforced by code review. |
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

1. **Skeleton & contract** — `Detector` protocol (incl. `on_cluster_terminated`), `ClusterHit`, `PromoterConfig`, `ClusterStore` shell (with `_cooldowns`, `_termination_listeners`, `mark_promoted`, `mark_silenced`, `add_termination_listener`), lifespan wiring (no detectors yet, no-op Promoter behind master flag). Router wiring for `promote_incident` / `silence_incident` → `cluster_store.mark_promoted` / `mark_silenced` (with `cluster_store is None` graceful no-op).
2. **`incident_store`** — add `apply_signal_update`, `list_owned_for_rehydrate`, tighten `close_incident` to idempotent (+ tests).
3. **FIRMS detector** with per-bucket pre-trigger deque, ignition, `on_cluster_terminated` reset (+ unit tests + integration test #1).
4. **ClusterStore full lifecycle** — Sweeper (clusters + cooldowns), Rehydrate (subscribe-first), termination-callback fan-out (+ unit ClusterStore tests + integration tests #4, #5, #6).
5. **Telegram detector** (shingles + ignition) + test #3 + embeddings-flag-disabled test.
6. **Severity detector** (default-off) + test #2.
7. **GDELT detector skeleton** (default-off, schema unverified) + smoke test.
8. **Admin inspector endpoint** + smoke test.
9. **E2E test** + `.env.example` + release notes (incl. "enable Severity only after frontend `map:no_pin` lands").
