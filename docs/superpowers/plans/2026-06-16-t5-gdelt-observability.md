# T5 — gdelt_raw Robustness & Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gdelt_raw` MENTIONS drops observable (distinguish a genuine "no resolvable Document/Event" drop from a normal replay/existing-edge no-op) and make a hard crash mid-store-write recoverable (write-ahead intent so a stranded slice always lands in the pending set) — closing WP-09 (Medium/SILENT_SKIP) and WP-10 (Medium/SILENT_SKIP).

**Architecture:** Two independent fixes (per spec `docs/superpowers/specs/2026-06-15-writepath-graph-integrity-fixes-design.md`, section T5). **WP-09 (observability only — the theme-filtering is by design and is NOT changed):** `MERGE_MENTION` becomes `OPTIONAL MATCH … FOREACH(conditional MERGE) … RETURN d_found, e_found` so the writer can tell a real drop (a MATCH bound zero rows) from a replay/existing-edge no-op (`relationships_created == 0` but both bound); `write_mentions` classifies each outcome, counts per slice, and emits structlog "metrics". **WP-10 (write-ahead intent):** in `run.py`, `add_pending(store, S)` runs *before* each store write and `remove_pending` on success, so a `SIGKILL` between the parquet checkpoint and the store write still leaves S in the pending set for `replay_pending`; the parquet checkpoint stays the (store-independent) download gate, unchanged; a new `reconcile_forward_state` flags any store whose `last_slice` lags the parquet pointer.

**Tech Stack:** Python 3.12, `uv`, `pytest`/`pytest-asyncio`, `neo4j` async bolt driver, Redis (`redis.asyncio`), structlog, `click` CLI, Neo4j 5 Community. Single service: `services/data-ingestion`.

---

## Background: the two verified defects (read before implementing)

**WP-09 — silent MENTIONS drops, no metric.** `MERGE_MENTION` (`neo4j_writer.py:88-96`) starts `MATCH (d:Document {url:$doc_url}) MATCH (e:GDELTEvent {event_id:$event_id}) MERGE (d)-[r:MENTIONS]->(e)`. GDELT `Document`s exist only for theme-matched articles (by design); mentions are scoped by surviving event_ids — orthogonal criteria. For a mention whose article was **not** theme-matched, the leading `MATCH` binds **zero rows**, the chained `MERGE` is a clean no-op, the tx commits — **no edge, no error, no log** (`write_mentions:192-206` discards `tx.run`'s result). Idempotent replay never recovers it. The design doc named a `gdelt_mentions_written_total` metric that was never implemented. **Crucial subtlety:** you **cannot** detect a drop from `relationships_created == 0` — that is *also* 0 on a normal replay (edge already exists). The only "no resolvable Document/Event" signal is the leading MATCH binding nothing. Fix is observability-only; **do not** add a stub-Document fallback (it would defeat the theme filter).

**WP-10 — hard-crash strands a slice.** In `run.py` `run_forward_slice`, `set_last_slice("parquet", S)` (`:144`) commits **before** any store write, and `add_pending` runs **only inside the `except`** (`:160/:170`). A `SIGKILL`/OOM between the parquet advance and the store write lands after the parquet pointer moved but before the `except` could enqueue S → S is absent from both pending sets, and the forward gate (`:187-190`, purely the parquet pointer) never re-touches it. Only a manual backfill recovers it. The primitives already exist: `state.add_pending`/`remove_pending`/`list_pending` (`state.py:52-61`) and `recovery.replay_pending` (`recovery.py:27-62`, re-processes the pending sets and `remove_pending`s on success). The fix is to enqueue **before** the write (write-ahead intent), not only on exception.

### Scope / non-goals

- **Files:** `gdelt_raw/writers/neo4j_writer.py`, `gdelt_raw/run.py`, `gdelt_raw/recovery.py`, `gdelt_raw/cli.py` + their tests. Do **not** touch `parser.py`/`filter.py`/`qdrant_writer.py` (T2) or the read-path/entity files (T3).
- **"metrics" = structlog events** — there is no Prometheus registry in this repo (existing pattern: `log.info("qdrant_written", count=…)`). Emit the spec's metric names as structlog event names so a future metrics migration can grep them.
- **Do NOT gate `forward()` on `is_slice_fully_done`** — the parquet checkpoint must stay the store-independent download gate (a down store must not force re-downloads). Leave `run.py:136-150` + `:187-190` as-is.
- The theme-filter disjointness (why some mentions have no Document) is **by design** — this tranche makes it *visible*, it does not change what is ingested.

---

## File Structure

Run all commands from `services/data-ingestion`. `uv sync --all-extras` once before the first test run (matches CI).

- **Modify** `gdelt_raw/writers/neo4j_writer.py` — restructure `MERGE_MENTION` (OPTIONAL MATCH + conditional FOREACH MERGE + `RETURN d_found, e_found`); add `_classify_mention`; `write_mentions` classifies/counts/emits metrics and takes a `slice_id`; `write_from_parquet` passes `slice_id`.
- **Modify** `tests/test_gdelt_neo4j_writer.py` — update the stale `ON MATCH` template test; add `_classify_mention` + `write_mentions` counting/metric tests.
- **Modify** `gdelt_raw/run.py` — write-ahead `add_pending`/`remove_pending` around each store write.
- **Modify** `tests/test_gdelt_forward.py` — assert the pending entry exists *before* the external write.
- **Create** `gdelt_raw/recovery.py` reconcile function (`reconcile_forward_state`) — flags stores lagging the parquet pointer.
- **Modify** `gdelt_raw/cli.py` — a `reconcile` command surfacing the lag.
- **Create/Modify** `tests/test_gdelt_recovery.py` — `reconcile_forward_state` tests.

---

## Task 1: WP-09 — observable MENTIONS writes

**Files:**
- Modify: `gdelt_raw/writers/neo4j_writer.py` (`MERGE_MENTION` `:88-96`; `write_mentions` `:192-206`; `write_from_parquet` mentions call `:236-238`)
- Modify: `tests/test_gdelt_neo4j_writer.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_gdelt_neo4j_writer.py`:

(a) The existing `test_merge_mention_sets_properties_on_match_too` asserts `"ON MATCH" in MERGE_MENTION` — the restructured template no longer uses `ON MATCH`. Replace that test with one that locks the NEW shape:

```python
def test_merge_mention_optional_match_and_returns_found_flags():
    """WP-09: OPTIONAL MATCH so a missing Document/Event is detectable (not a
    silent zero-row no-op); conditional MERGE only when both bound; RETURN the
    found-flags so write_mentions can classify drops."""
    from gdelt_raw.writers.neo4j_writer import MERGE_MENTION
    assert "OPTIONAL MATCH (d:Document {url: $doc_url})" in MERGE_MENTION
    assert "OPTIONAL MATCH (e:GDELTEvent {event_id: $event_id})" in MERGE_MENTION
    assert "FOREACH" in MERGE_MENTION
    assert "r.tone = $tone" in MERGE_MENTION  # properties still set
    assert "d_found" in MERGE_MENTION and "e_found" in MERGE_MENTION
    # No stub-Document fallback (must not defeat the theme filter):
    assert "MERGE (d:Document" not in MERGE_MENTION
```

(b) Add `_classify_mention` unit tests (pure function — the heart of WP-09):

```python
def test_classify_mention_outcomes():
    from gdelt_raw.writers.neo4j_writer import _classify_mention
    assert _classify_mention(d_found=False, e_found=True, rels_created=0) == "dropped_no_document"
    assert _classify_mention(d_found=True, e_found=False, rels_created=0) == "dropped_no_event"
    assert _classify_mention(d_found=True, e_found=True, rels_created=1) == "written"
    assert _classify_mention(d_found=True, e_found=True, rels_created=0) == "existing"
    # missing-document takes precedence when both are missing
    assert _classify_mention(d_found=False, e_found=False, rels_created=0) == "dropped_no_document"
```

(c) Add a `write_mentions` test that mocks the driver/tx/result chain and asserts the per-slice counts + the drop warning (uses structlog capture):

```python
import structlog
from unittest.mock import AsyncMock, MagicMock


def _mention_result(d_found: bool, e_found: bool, rels_created: int):
    """Mock a neo4j async Result: .single() -> record, .consume() -> summary."""
    result = MagicMock()
    result.single = AsyncMock(return_value={"d_found": d_found, "e_found": e_found})
    summary = MagicMock()
    summary.counters.relationships_created = rels_created
    result.consume = AsyncMock(return_value=summary)
    return result


def _writer_with_tx(results: list):
    """Neo4jWriter whose session().begin_transaction().run() yields the given
    results in order. No real Neo4j."""
    from gdelt_raw.writers.neo4j_writer import Neo4jWriter
    tx = MagicMock()
    tx.run = AsyncMock(side_effect=results)
    tx.commit = AsyncMock()
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=tx)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin_transaction = AsyncMock(return_value=tx_cm)
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    w = Neo4jWriter("bolt://localhost:7687", "neo4j", "x")
    w._driver = MagicMock()
    w._driver.session = MagicMock(return_value=session_cm)
    return w


@pytest.mark.asyncio
async def test_write_mentions_counts_and_warns_on_drops():
    w = _writer_with_tx([
        _mention_result(True, True, 1),    # written
        _mention_result(True, True, 0),    # existing
        _mention_result(False, True, 0),   # dropped_no_document
        _mention_result(True, False, 0),   # dropped_no_event
    ])
    mentions = [
        {"mention_url": f"https://ex.com/{i}", "event_id": f"gdelt:event:{i}",
         "tone": 0.0, "confidence": 100, "char_offset": 0}
        for i in range(4)
    ]
    with structlog.testing.capture_logs() as logs:
        counts = await w.write_mentions(mentions, "20260425120000")

    assert counts == {"written": 1, "existing": 1,
                      "dropped_no_document": 1, "dropped_no_event": 1}
    metric = [e for e in logs if e["event"] == "gdelt_mentions_written_total"]
    assert metric and metric[0]["written"] == 1 and metric[0]["dropped_no_document"] == 1
    assert any(e["event"] == "gdelt_mentions_dropped_no_document_total"
               and e["log_level"] == "warning" for e in logs)
```

(The module already imports `pytest` and `from gdelt_raw.schemas import GDELTDocumentWrite, GDELTEventWrite`.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_gdelt_neo4j_writer.py -k "mention or classify" -v`
Expected: FAIL — `_classify_mention` missing; `MERGE_MENTION` still has `ON MATCH`/no `OPTIONAL MATCH`; `write_mentions` takes no `slice_id` / returns None.

- [ ] **Step 3: Restructure `MERGE_MENTION`**

In `gdelt_raw/writers/neo4j_writer.py`, replace `MERGE_MENTION` (`:88-97`):

```python
MERGE_MENTION = """
// Intentional: :Document (unscoped) so GDELT mentions can bridge to docs from
// other ingestion paths. OPTIONAL MATCH (not MATCH) so a mention whose article
// was not theme-matched is a DETECTABLE drop, not a silent zero-row no-op
// (WP-09). The FOREACH performs the MERGE only when both nodes resolved.
OPTIONAL MATCH (d:Document {url: $doc_url})
OPTIONAL MATCH (e:GDELTEvent {event_id: $event_id})
FOREACH (_ IN CASE WHEN d IS NOT NULL AND e IS NOT NULL THEN [1] ELSE [] END |
  MERGE (d)-[r:MENTIONS]->(e)
    SET r.tone = $tone, r.confidence = $confidence, r.char_offset = $char_offset
)
RETURN d IS NOT NULL AS d_found, e IS NOT NULL AS e_found
"""
# SET (not ON CREATE/ON MATCH) is unconditional last-write-wins — equivalent to
# the prior template's identical ON CREATE/ON MATCH SET, but FOREACH-legal.
```

- [ ] **Step 4: Add `_classify_mention` + rewrite `write_mentions`**

Add the helper near `_validate_rows`:

```python
def _classify_mention(*, d_found: bool, e_found: bool, rels_created: int) -> str:
    """Classify one MERGE_MENTION outcome. A drop is a MATCH binding nothing —
    NOT rels_created == 0 (that is also 0 on replay / existing edge)."""
    if not d_found:
        return "dropped_no_document"
    if not e_found:
        return "dropped_no_event"
    return "written" if rels_created > 0 else "existing"
```

Replace `write_mentions` (`:192-206`):

```python
    async def write_mentions(self, mentions: list[dict], slice_id: str) -> dict[str, int]:
        """mentions: canonical dicts with event_id, mention_url, tone, confidence,
        char_offset. A mention whose article was not theme-matched has no
        Document and is counted as dropped_no_document (by-design filtering — see
        WP-09), never silently lost. Returns per-slice outcome counts."""
        counts = {"written": 0, "existing": 0,
                  "dropped_no_document": 0, "dropped_no_event": 0}
        async with self._driver.session() as session:  # noqa: SIM117
            async with await session.begin_transaction() as tx:
                for m in mentions:
                    result = await tx.run(MERGE_MENTION, {
                        "doc_url": m["mention_url"],
                        "event_id": m["event_id"],
                        "tone": m.get("tone"),
                        "confidence": m.get("confidence"),
                        "char_offset": m.get("char_offset"),
                    })
                    record = await result.single()
                    summary = await result.consume()
                    outcome = _classify_mention(
                        d_found=bool(record["d_found"]),
                        e_found=bool(record["e_found"]),
                        rels_created=summary.counters.relationships_created,
                    )
                    counts[outcome] += 1
                await tx.commit()

        log.info("gdelt_mentions_written_total", slice=slice_id, **counts)
        if counts["dropped_no_document"] or counts["dropped_no_event"]:
            log.warning(
                "gdelt_mentions_dropped_no_document_total",
                slice=slice_id,
                dropped_no_document=counts["dropped_no_document"],
                dropped_no_event=counts["dropped_no_event"],
            )
        return counts
```

Update the `write_from_parquet` mentions call (`:236-238`) to pass `slice_id`:

```python
        if mentions_path.exists() and ev_path.exists() and gkg_path.exists():
            m_df = pl.read_parquet(mentions_path)
            await self.write_mentions(m_df.to_dicts(), slice_id)
```

- [ ] **Step 5: Run to verify pass + no regression**

Run: `uv run pytest tests/test_gdelt_neo4j_writer.py -v`
Expected: all PASS (the new mention tests + the existing template/schema/skip-and-log tests). Note: the integration test `test_gdelt_integration.py` calls `write_from_parquet` (which now passes `slice_id`); it is `@pytest.mark.integration` and skips without dev-compose — confirm it still *collects* (no import/signature error): `uv run pytest tests/test_gdelt_integration.py --collect-only -q`.

Run: `uv run ruff check gdelt_raw/writers/neo4j_writer.py tests/test_gdelt_neo4j_writer.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t5-gdelt-observability
git add services/data-ingestion/gdelt_raw/writers/neo4j_writer.py services/data-ingestion/tests/test_gdelt_neo4j_writer.py
git commit -m "feat(gdelt-raw): observable MENTIONS writes — classify drops vs replay, emit per-slice metrics (WP-09)"
```

---

## Task 2: WP-10 — write-ahead intent in the forward path

**Files:**
- Modify: `gdelt_raw/run.py` (`run_forward_slice` Neo4j block `:152-160`, Qdrant block `:162-170`)
- Modify: `tests/test_gdelt_forward.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_gdelt_forward.py` (it already uses `monkeypatch` + `AsyncMock` writers + a real/fake `GDELTState`; mirror `test_store_state_not_advanced_on_failure` which asserts `list_pending("neo4j")` membership). Add a test that the slice is pending **before** the store write runs — i.e. the writer, when called, can already see itself in pending:

```python
@pytest.mark.asyncio
async def test_slice_is_pending_before_external_write(tmp_path, monkeypatch):
    """WP-10 write-ahead: a SIGKILL mid-write must leave the slice recoverable.
    Prove it by asserting the pending entry exists DURING the writer call (i.e.
    enqueued before the write, not only in the except handler)."""
    # ... arrange state + parsed slice the same way test_store_state_not_advanced_on_failure does ...
    seen_pending = {}

    async def _neo4j_write(parquet_base, slice_id, date):
        seen_pending["neo4j"] = await state.list_pending("neo4j")  # captured DURING the write

    neo4j_writer = AsyncMock()
    neo4j_writer.write_from_parquet = AsyncMock(side_effect=_neo4j_write)
    qdrant_writer = AsyncMock()
    qdrant_writer.upsert_from_parquet = AsyncMock(return_value=0)

    # ... run run_forward_slice(entries, state=state, parquet_base=..., neo4j_writer=neo4j_writer,
    #     qdrant_writer=qdrant_writer, tmp_dir=...) with the download/parse monkeypatched as the
    #     sibling tests do ...

    assert "20260425120000" in seen_pending["neo4j"]            # enqueued BEFORE the write
    assert "20260425120000" not in await state.list_pending("neo4j")  # removed on success
```

Build the arrange/run scaffolding by copying the structure of the existing `test_store_state_not_advanced_on_failure` (same monkeypatching of `_extract_and_parse`/download and the same `GDELTState`/`run_forward_slice` call) — read that test first and reuse its fixtures verbatim, changing only the writer side-effects and the assertions above.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_gdelt_forward.py::test_slice_is_pending_before_external_write -v`
Expected: FAIL — today `add_pending` runs only in the `except`, so during a *successful* write the slice is not yet pending → `seen_pending["neo4j"]` is empty.

- [ ] **Step 3: Implement write-ahead intent**

In `gdelt_raw/run.py` `run_forward_slice`, replace the Neo4j block (`:152-160`) and Qdrant block (`:162-170`):

```python
    # Neo4j — write-ahead intent: enqueue BEFORE the write so a hard kill
    # (SIGKILL/OOM) mid-write still leaves the slice in pending for
    # replay_pending. remove_pending only on confirmed success (WP-10).
    await state.add_pending("neo4j", slice_id)
    try:
        await neo4j_writer.write_from_parquet(parquet_base, slice_id, date)
        await state.set_store_state(slice_id, "neo4j", "done")
        await state.set_last_slice("neo4j", slice_id)
        await state.remove_pending("neo4j", slice_id)
    except Exception as e:
        log.error("gdelt_neo4j_write_failed", slice=slice_id, error=str(e))
        await state.set_store_state(slice_id, "neo4j", f"failed:{e}")
        # slice stays in pending (already enqueued) for replay_pending

    # Qdrant — INDEPENDENT of Neo4j outcome; same write-ahead intent.
    await state.add_pending("qdrant", slice_id)
    try:
        await qdrant_writer.upsert_from_parquet(parquet_base, slice_id, date)
        await state.set_store_state(slice_id, "qdrant", "done")
        await state.set_last_slice("qdrant", slice_id)
        await state.remove_pending("qdrant", slice_id)
    except Exception as e:
        log.error("gdelt_qdrant_write_failed", slice=slice_id, error=str(e))
        await state.set_store_state(slice_id, "qdrant", "pending_embed")
        # slice stays in pending (already enqueued) for replay_pending
```

Do **not** change the parquet checkpoint (`:136-150`) or the forward gate (`:187-190`).

- [ ] **Step 4: Run to verify pass + no regression**

Run: `uv run pytest tests/test_gdelt_forward.py -v`
Expected: all PASS — including `test_store_state_not_advanced_on_failure` (the slice is still in pending after a failure — now because it was enqueued up-front and never removed) and `test_parquet_written_before_external_stores`.

Run: `uv run ruff check gdelt_raw/run.py tests/test_gdelt_forward.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t5-gdelt-observability
git add services/data-ingestion/gdelt_raw/run.py services/data-ingestion/tests/test_gdelt_forward.py
git commit -m "fix(gdelt-raw): write-ahead add_pending before store writes so a hard crash never strands a slice (WP-10)"
```

---

## Task 3: WP-10 — reconcile command for parquet/store lag

**Files:**
- Modify: `gdelt_raw/recovery.py` (add `reconcile_forward_state`)
- Modify: `gdelt_raw/cli.py` (add a `reconcile` command)
- Modify: `tests/test_gdelt_recovery.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_gdelt_recovery.py` (it constructs a `GDELTState` over a fake/real async Redis — mirror its existing fixtures), add:

```python
@pytest.mark.asyncio
async def test_reconcile_flags_store_lagging_parquet(fake_state):
    """parquet checkpoint is store-independent and advances first; a store whose
    last_slice trails it is a candidate stranded slice (WP-10)."""
    from gdelt_raw.recovery import reconcile_forward_state

    await fake_state.set_last_slice("parquet", "20260425121500")
    await fake_state.set_last_slice("neo4j", "20260425120000")   # lags
    await fake_state.set_last_slice("qdrant", "20260425121500")  # in sync

    report = await reconcile_forward_state(fake_state)
    assert report["parquet"] == "20260425121500"
    assert report["lagging"] == ["neo4j"]
    assert report["neo4j"] == "20260425120000"


@pytest.mark.asyncio
async def test_reconcile_no_lag_when_all_in_sync(fake_state):
    from gdelt_raw.recovery import reconcile_forward_state
    for store in ("parquet", "neo4j", "qdrant"):
        await fake_state.set_last_slice(store, "20260425121500")
    report = await reconcile_forward_state(fake_state)
    assert report["lagging"] == []
```

Use the same `GDELTState`/Redis fixture the existing recovery tests use (read `tests/test_gdelt_recovery.py` first; if it builds state inline, replicate that — name the fixture/local to match).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_gdelt_recovery.py -k reconcile -v`
Expected: FAIL — `reconcile_forward_state` does not exist.

- [ ] **Step 3: Implement `reconcile_forward_state`**

In `gdelt_raw/recovery.py`, add:

```python
async def reconcile_forward_state(state: GDELTState) -> dict:
    """Flag stores whose last_slice trails the parquet checkpoint.

    The parquet pointer is the store-independent download gate and advances
    first; a store pointer that lags it indicates a slice whose parquet exists
    but whose store write did not confirm (WP-10 — e.g. a hard crash mid-write).
    Such slices should be in the pending set for replay_pending; this is the
    detection half. Returns the three pointers plus the list of lagging stores."""
    parquet = await state.get_last_slice("parquet")
    report: dict = {"parquet": parquet, "lagging": []}
    for store in ("neo4j", "qdrant"):
        ptr = await state.get_last_slice(store)
        report[store] = ptr
        # slice_ids are zero-padded YYYYMMDDHHMMSS → lexicographic == chronological
        if parquet is not None and (ptr is None or ptr < parquet):
            report["lagging"].append(store)
    if report["lagging"]:
        log.warning(
            "gdelt_forward_state_lag",
            parquet=parquet,
            lagging=report["lagging"],
            neo4j=report.get("neo4j"),
            qdrant=report.get("qdrant"),
        )
    return report
```

- [ ] **Step 4: Add the `reconcile` CLI command**

In `gdelt_raw/cli.py`, add a command alongside `status` (it already imports `replay_pending`; add the reconcile import). Mirror the `status` command's `_get_clients`/`_close_clients` pattern:

```python
@main.command()
def reconcile():
    """Report stores whose last_slice trails the parquet checkpoint (WP-10)."""
    async def _go():
        from gdelt_raw.recovery import reconcile_forward_state
        state, neo4j, qdrant = await _get_clients()
        try:
            report = await reconcile_forward_state(state)
            click.echo(f"parquet last_slice: {report['parquet']}")
            for store in ("neo4j", "qdrant"):
                flag = "  LAGS" if store in report["lagging"] else ""
                click.echo(f"{store:>7} last_slice: {report[store]}{flag}")
            if report["lagging"]:
                click.echo(f"\nLagging: {report['lagging']} — run `forward` "
                           f"or `resume <job>` to replay pending slices.")
        finally:
            await _close_clients(state, neo4j, qdrant)
    _run(_go())
```

(Match the exact `_get_clients`/`_close_clients`/`_run` signatures already in `cli.py` — read the `status` command first and copy its client-lifecycle handling verbatim.)

- [ ] **Step 5: Run to verify pass + no regression**

Run: `uv run pytest tests/test_gdelt_recovery.py -v`
Expected: all PASS (reconcile tests + existing replay tests).
Run (CLI wiring smoke): `uv run python -c "from gdelt_raw.cli import main; assert 'reconcile' in main.commands; print('reconcile command registered')"`
Expected: `reconcile command registered`.
Run: `uv run ruff check gdelt_raw/recovery.py gdelt_raw/cli.py tests/test_gdelt_recovery.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t5-gdelt-observability
git add services/data-ingestion/gdelt_raw/recovery.py services/data-ingestion/gdelt_raw/cli.py services/data-ingestion/tests/test_gdelt_recovery.py
git commit -m "feat(gdelt-raw): reconcile command flags stores lagging the parquet checkpoint (WP-10)"
```

---

## Final verification (after Task 3)

- [ ] Full data-ingestion suite: `uv run pytest -q` → 0 failures (record pass/skip counts).
- [ ] Lint: `uv run ruff check gdelt_raw/ tests/` → clean.
- [ ] Confirm the forward gate (`run.py:187-190`) and parquet checkpoint were NOT changed (`git diff a1f7b53..HEAD -- gdelt_raw/run.py` shows only the two store blocks).
- [ ] Confirm `replay_pending` (`recovery.py`) still removes-on-success (unchanged) — it is the repair half that the write-ahead intent feeds.

---

## Self-Review (spec coverage)

| Spec T5 item | Task |
| --- | --- |
| WP-09 detect drop via leading MATCH binding zero rows (NOT `relationships_created == 0`) | Task 1 (`OPTIONAL MATCH … RETURN d_found, e_found` + `_classify_mention`) |
| WP-09 `written` from `relationships_created`; `dropped_no_document/_event` only when MATCH bound nothing; `existing` optional | Task 1 (`_classify_mention`) |
| WP-09 emit `gdelt_mentions_written_total` + `gdelt_mentions_dropped_no_document_total` + structured warning | Task 1 (structlog events) |
| WP-09 no stub-Document fallback | Task 1 (template test asserts `MERGE (d:Document` absent) |
| WP-10 `add_pending` before each store write + `remove_pending` on success | Task 2 |
| WP-10 keep parquet as the store-independent download gate; don't gate `forward()` on `is_slice_fully_done` | Background + Task 2 (unchanged) |
| WP-10 reconcile flags parquet-ahead-of-store; shared replay command | Task 3 (`reconcile_forward_state` + CLI) + existing `replay_pending` |
| WP-10 test: pending entry exists before the external write | Task 2 |
