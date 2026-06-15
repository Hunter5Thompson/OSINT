# T3 — Entity Canonicalization + Read-Path Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the knowledge graph's Entity layer fragmenting on every RSS run (lowercase RSS types vs UPPERCASE NLM types → distinct nodes), and stop the read-path returning null/arbitrary-ordered event timestamps (closes WP-04 Medium/DUPLICATION + WP-08 Medium/correctness).

**Architecture:** Two independent fixes (per spec `docs/superpowers/specs/2026-06-15-writepath-graph-integrity-fixes-design.md`, section T3). **WP-04 (write-path):** the lowercase→UPPERCASE entity-type normalizer already exists (`normalize_entity_type` + `LEGACY_ENTITY_TYPE_MAP` in `nlm_ingest/schemas.py`, called from `pipeline.py` behind `settings.entity_type_normalize`); flip its default ON so RSS and NLM converge on one `(name, type)` node, fix the dead `entity_name_type` index (it references a property nothing writes), and add a composite-unique constraint after the existing idempotent dedup migrations. **WP-08 (read-path, API-compatible):** every read template returns/sorts on `ev.timestamp`, which no write-path sets (the real anchor is `ev.timeline_at`); replace with `coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp` and sort on that coalesced alias, in both the backend router and the intelligence graph tool, plus a CI grep guard.

**Tech Stack:** Python 3.12, `uv`, `pytest`/`pytest-asyncio`/`fastapi.testclient`, pydantic v2, structlog, Neo4j 5 **Community** (~5.26 per the installed APOC), Cypher. Three services touched: `data-ingestion`, `backend`, `intelligence`, plus `.github/workflows/ci.yml`.

---

## Background: the two verified defects (read before implementing)

**WP-04 — cross-path Entity key split.** RSS (`pipeline.py`) provably writes **lowercase** types (the extraction `_RESPONSE_SCHEMA` enum at `pipeline.py:263-266`: `person, organization, location, weapon_system, satellite, vessel, aircraft, military_unit`). NLM (`nlm_ingest/write_templates.py:16`) provably writes **UPPERCASE** via the `EntityType` Literal. Both `MERGE (e:Entity {name, type})`, so `"organization"` and `"ORGANIZATION"` are **distinct nodes** — the graph re-fragments on every RSS run, re-dirtying the one-shot merge migration. The fix is already wired but **gated off**: `pipeline.py:522` calls `normalize_entity_type(entity_type)` only `if settings.entity_type_normalize` (default `False`, `config.py:124`). `normalize_entity_type` (`nlm_ingest/schemas.py:39-49`) maps via `LEGACY_ENTITY_TYPE_MAP` (`:27-36`) whose **8 keys are exactly the RSS enum's 8 values** — full coverage, so flipping the default deterministically normalizes every RSS type; unknown values fail-soft (pass through + structlog warn, `pipeline.py:525-535`). Separately, the `entity_name_type` index (`gdelt_raw/migrations/phase2_indexes.cypher:11-12`) is on `(e.normalized_name, e.type)` — **nothing writes `normalized_name`** — so it never serves the `MERGE` lookups. There is **no uniqueness constraint** on `Entity`.

**WP-08 — read-path reads `ev.timestamp` which no write-path sets.** Grep-confirmed: the live pipeline writes `ev.timeline_at` (`pipeline.py:523`), the GDELT writer writes `ev.timeline_at` (`gdelt_raw/writers/neo4j_writer.py:35/49`); **no write-path sets `ev.timestamp`**. Yet `backend/app/routers/graph.py` (3 sites: `:135-136`, `:143-144`, `:189-192`) and `intelligence/agents/tools/graph_templates.py` (3 sites: `:51-53`, `:65-67`, `:91-92`) all `RETURN ev.timestamp AS timestamp ... ORDER BY ev.timestamp DESC`. Result: returned `timestamp` is always null, and ordering over an all-null key has no tiebreak (arbitrary storage order, not newest-first). `timeline.py` already reads `ev.timeline_at` correctly — the read-path is just inconsistent.

### Repair / scope notes

- **WP-04 repair** = re-run the two existing idempotent migrations (`migrations/neo4j_entity_type_canonicalization.cypher` rewrites legacy lowercase→UPPERCASE; `migrations/neo4j_duplicate_merge.cypher` merges eligible same-name groups). They are **not changed** by this tranche — they are the repair. The ~414 multi-type semantic-conflict groups remain manual (unchanged). The new composite-unique constraint is applied **after** those, behind an exact-`(name,type)`-duplicate **preflight** (multi-type groups the merge skips can still leave exact dups, which would make `CREATE CONSTRAINT` fail).
- **WP-08 repair** = none (`timeline_at` is already correct on nodes; this is a pure read-template fix).
- **Constraint edition note:** Neo4j 5 **Community** supports node property uniqueness constraints, **including composite (multi-property)** — only node-KEY and property-EXISTENCE constraints are Enterprise-only. The migration uses a composite `(name, type)` uniqueness constraint; it documents a single derived-`entity_key` fallback as a contingency, to be confirmed at operator apply-time against the live instance. **`pipeline.py` itself needs no code change** — only the `config.py` default flips.
- **`canonicalize.py` is out of scope** — it does curated *name*-alias resolution, not type-case normalization (that is `normalize_entity_type`). Do not touch it.

---

## File Structure

Run commands from the relevant service dir (noted per task). The worktree is fresh off `main` (includes T1+T2); run `uv sync --all-extras` per service before its first test run (matches CI).

- **Modify** `services/data-ingestion/config.py` — flip `entity_type_normalize` default `False`→`True` + rewrite the rationale comment.
- **Modify** `services/data-ingestion/tests/test_config.py` — assert the new default.
- **Modify** `services/data-ingestion/tests/test_pipeline.py` — make the two flag-OFF tests set the flag explicitly; fix the now-stale "default-OFF" docstrings; annotate the `_make_settings` helper's pinned `False`.
- **Modify** `services/data-ingestion/gdelt_raw/migrations/phase2_indexes.cypher` — fix the `entity_name_type` index to `(e.name, e.type)`.
- **Create** `services/data-ingestion/migrations/neo4j_entity_name_type_unique.cypher` — preflight query + composite-unique constraint + entity_key-fallback doc.
- **Create** `services/data-ingestion/tests/test_entity_constraint_migration.py` — content-lock the index + constraint cypher.
- **Modify** `services/backend/app/routers/graph.py` — coalesced timestamp + alias-ordering (3 sites).
- **Modify** `services/backend/tests/unit/test_graph_router.py` — assert the coalesced cypher (2 tests).
- **Modify** `services/intelligence/agents/tools/graph_templates.py` — coalesced timestamp + alias-ordering (3 sites).
- **Modify** `services/intelligence/tests/test_graph_templates.py` — assert the coalesced cypher.
- **Modify** `services/intelligence/tests/test_cypher_validation.py` — line 24 example uses `ev.timeline_at`.
- **Modify** `.github/workflows/ci.yml` — new job forbidding `ORDER BY ev.timestamp` in the read templates.

---

## Task 1: Flip `entity_type_normalize` default ON (WP-04 write-path)

**Files:**
- Modify: `services/data-ingestion/config.py` (`:120-124`)
- Modify: `services/data-ingestion/tests/test_config.py`
- Modify: `services/data-ingestion/tests/test_pipeline.py` (`_make_settings` ~`:29`; flag-OFF tests at the `TestEntityTypeNormalization` class ~`:242-292` and `test_generic_name_is_not_folded` ~`:397-402`)

Work from `services/data-ingestion`. First: `uv sync --all-extras`.

- [ ] **Step 1: Write the failing test (new default + explicit flag-off)**

In `tests/test_config.py`, add (it already constructs `Settings`; mirror its style — use `from config import Settings`):

```python
def test_entity_type_normalize_defaults_on():
    """WP-04: the RSS write-path must canonicalize lowercase types by default so
    it converges with the NLM UPPERCASE path on one (name, type) Entity node."""
    from config import Settings
    assert Settings.model_fields["entity_type_normalize"].default is True
```

In `tests/test_pipeline.py`, make the two flag-OFF tests independent of the helper default by passing the flag explicitly. Change `test_pipeline_passes_through_when_flag_off` to call `settings=_make_settings(entity_type_normalize=False)` (instead of `_make_settings()`), and in `test_generic_name_is_not_folded` ensure its `_run(...)` path sets `entity_type_normalize=False` (the `_run` helper passes `**settings_overrides` to `_make_settings`, so call `self._run({...}, entity_type_normalize=False)` if `_run` forwards overrides, otherwise pass the override through the same mechanism the class already uses — read `_run`'s signature first and thread the flag the same way).

- [ ] **Step 2: Run to verify the new test fails**

Run: `uv run pytest tests/test_config.py::test_entity_type_normalize_defaults_on -v`
Expected: FAIL — default is currently `False`.

- [ ] **Step 3: Flip the default + update the comment**

In `config.py`, replace `:120-124`:

```python
    # --- Entity-type normalizer (WP-04: default ON) ---
    # ON by default: the RSS write-path canonicalizes its lowercase enum types
    # (person -> PERSON, ...) onto the canonical UPPERCASE EntityType set BEFORE
    # the MERGE (e:Entity {name, type}), so RSS and NLM writes converge on ONE
    # node per (name, type). The lowercase enum is fully covered by
    # LEGACY_ENTITY_TYPE_MAP (nlm_ingest/schemas.py); unknown values fail-soft
    # (pass through unchanged + a structlog warning). Set False only to
    # reproduce the pre-WP-04 lowercase-passthrough behaviour.
    entity_type_normalize: bool = True
```

- [ ] **Step 4: Keep the flag-OFF tests honest (docstrings + helper note)**

In `tests/test_pipeline.py`:
- At the `_make_settings` helper, annotate the pinned value (find the line `"entity_type_normalize": False,` ~`:29`) with a trailing comment: `# pinned False for fixture determinism; prod default is True (config.py). Normalization tests set this explicitly.`
- In the `TestEntityTypeNormalization` class docstring (~`:242-248`), replace the "default-OFF" framing with: the normalizer is **default ON** in prod (config.py); these tests pin the flag explicitly to cover both the opt-out (`False`) and the normalize (`True`) paths.
- In `test_pipeline_passes_through_when_flag_off`, update the inline comment that said "Default flag value is False — pass nothing" to reflect that the test now passes `entity_type_normalize=False` explicitly to exercise the opt-out path.

- [ ] **Step 5: Run to verify pass + no regression**

Run: `uv run pytest tests/test_config.py tests/test_pipeline.py -v`
Expected: all PASS — the new default test passes; the flag-OFF tests still assert lowercase passthrough (now via the explicit `False`); `test_pipeline_normalizes_when_flag_on` and the curated-alias tests unchanged.

Run: `uv run ruff check config.py tests/test_config.py tests/test_pipeline.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t3-entity-readpath
git add services/data-ingestion/config.py services/data-ingestion/tests/test_config.py services/data-ingestion/tests/test_pipeline.py
git commit -m "fix(ingestion): default entity_type_normalize ON so RSS/NLM Entity types converge (WP-04)"
```

---

## Task 2: Fix the Entity index + add the composite-unique constraint (WP-04)

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/migrations/phase2_indexes.cypher` (`:11-12`)
- Create: `services/data-ingestion/migrations/neo4j_entity_name_type_unique.cypher`
- Create: `services/data-ingestion/tests/test_entity_constraint_migration.py`

Work from `services/data-ingestion`.

- [ ] **Step 1: Write the failing test (content-lock the migrations)**

Create `tests/test_entity_constraint_migration.py`:

```python
"""Content locks for the WP-04 Entity index/constraint migrations.

These are operator-applied .cypher files (not run in CI), so we lock their
content to prevent the dead-index regression (an index on a property nothing
writes) and to pin the composite-unique key shape."""

from __future__ import annotations

from pathlib import Path

DI = Path(__file__).resolve().parents[1]


def test_entity_name_type_index_references_a_written_property():
    cypher = (DI / "gdelt_raw" / "migrations" / "phase2_indexes.cypher").read_text()
    # The index must key on e.name (written by both write-paths), not the dead
    # e.normalized_name (WP-04).
    assert "entity_name_type" in cypher
    assert "(e.name, e.type)" in cypher
    assert "normalized_name" not in cypher


def test_entity_uniqueness_constraint_is_composite_name_type():
    cypher = (DI / "migrations" / "neo4j_entity_name_type_unique.cypher").read_text()
    assert "FOR (e:Entity)" in cypher
    assert "REQUIRE (e.name, e.type) IS UNIQUE" in cypher
    # Must be IF NOT EXISTS (idempotent) and must NOT be a node-key constraint
    # (Enterprise-only on this Community deployment).
    assert "IF NOT EXISTS" in cypher
    assert "IS NODE KEY" not in cypher
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_entity_constraint_migration.py -v`
Expected: FAIL — `phase2_indexes.cypher` still says `normalized_name`; the constraint file does not exist yet.

- [ ] **Step 3: Fix the dead index**

In `gdelt_raw/migrations/phase2_indexes.cypher`, replace `:11-12`:

```cypher
CREATE INDEX entity_name_type IF NOT EXISTS
  FOR (e:Entity) ON (e.name, e.type);
```

- [ ] **Step 4: Create the composite-unique constraint migration**

Create `migrations/neo4j_entity_name_type_unique.cypher`:

```cypher
// WP-04 — Entity (name, type) composite uniqueness constraint.
//
// Apply ORDER (operator-run against the live Neo4j; not run in CI):
//   1. migrations/neo4j_entity_type_canonicalization.cypher  (lowercase -> UPPERCASE)
//   2. migrations/neo4j_duplicate_merge.cypher               (merge eligible same-name groups)
//   3. The PREFLIGHT below — it MUST return zero rows before step 4.
//   4. The CREATE CONSTRAINT below.
//
// Why the preflight: neo4j_duplicate_merge.cypher intentionally SKIPS the ~414
// multi-type semantic-conflict groups (e.g. "X" as both PERSON and
// ORGANIZATION). Such a group can still contain *exact* (name, type)
// duplicates (e.g. two "X"/PERSON nodes), which would make CREATE CONSTRAINT
// fail. Resolve any rows the preflight returns by hand, then create the
// constraint.
//
// Edition: Neo4j 5 Community supports composite node *uniqueness* constraints
// (only NODE KEY / EXISTENCE constraints are Enterprise-only). If a specific
// Community build rejects the composite form, the documented fallback is to
// write a derived single property e.entity_key = e.name + '' + e.type on
// BOTH write-paths (pipeline.py and nlm_ingest/write_templates.py) and put a
// plain single-property unique constraint on e.entity_key instead. Prefer the
// composite form; only fall back if the live instance refuses it.

// ---- PREFLIGHT (run first; must return zero rows) ----
// MATCH (e:Entity)
// WITH e.name AS name, e.type AS type, count(*) AS c
// WHERE c > 1
// RETURN name, type, c ORDER BY c DESC;

// ---- CONSTRAINT (run only after the preflight is clean) ----
CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS
  FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE;
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_entity_constraint_migration.py -v`
Expected: PASS.

Run: `uv run ruff check tests/test_entity_constraint_migration.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t3-entity-readpath
git add services/data-ingestion/gdelt_raw/migrations/phase2_indexes.cypher services/data-ingestion/migrations/neo4j_entity_name_type_unique.cypher services/data-ingestion/tests/test_entity_constraint_migration.py
git commit -m "fix(ingestion): fix dead entity_name_type index + add (name,type) unique constraint w/ preflight (WP-04)"
```

---

## Task 3: Backend read-path coalesced timestamp (WP-08)

**Files:**
- Modify: `services/backend/app/routers/graph.py` (`:135-136`, `:143-144`, `:189-192`)
- Modify: `services/backend/tests/unit/test_graph_router.py`

Work from `services/backend`. First: `uv sync --all-extras` (and the suite needs `NEO4J_PASSWORD` — set `export NEO4J_PASSWORD=ci-test-password` for local runs, matching CI).

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_graph_router.py`, add to `class TestGraphEndpoints` and `class TestGeoEventsEndpoint` (they already inspect `mock.call_args.args[0]` — mirror `test_events_query_uses_element_id_not_ev_id`):

```python
    def test_events_query_coalesces_timestamp_and_sorts_on_alias(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = client.get("/api/graph/events")
            assert resp.status_code == 200
            cypher = mock.call_args.args[0]
            assert (
                "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp"
                in cypher
            )
            assert "ORDER BY timestamp DESC" in cypher
            assert "ORDER BY ev.timestamp" not in cypher
```

And in `class TestGeoEventsEndpoint`:

```python
    def test_geo_events_query_coalesces_timestamp_and_sorts_on_alias(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = client.get("/api/graph/events/geo")
            assert resp.status_code == 200
            cypher = mock.call_args.args[0]
            assert (
                "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp"
                in cypher
            )
            assert "ORDER BY timestamp DESC" in cypher
            assert "ORDER BY ev.timestamp" not in cypher
```

- [ ] **Step 2: Run to verify they fail**

Run: `NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_graph_router.py -k coalesce -v`
Expected: FAIL — templates still emit `ev.timestamp AS timestamp` / `ORDER BY ev.timestamp DESC`.

- [ ] **Step 3: Fix the three query sites in `graph.py`**

In `app/routers/graph.py`, in `get_events` (entity branch `:134-136`):

```python
            "RETURN elementId(ev) AS id, ev.title AS name, ev.codebook_type AS type, "
            "ev.severity AS severity, "
            "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp "
            "ORDER BY timestamp DESC LIMIT $limit",
```

The no-entity branch (`:142-144`) — same RETURN/ORDER BY replacement.

In `get_geo_events` (`:188-192`):

```python
        f"RETURN elementId(ev) AS id, ev.title AS title, ev.codebook_type AS codebook_type, "
        f"ev.severity AS severity, "
        f"coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp, "
        f"l.name AS location_name, l.country AS country, "
        f"l.lat AS lat, l.lon AS lon "
        f"ORDER BY timestamp DESC LIMIT $limit"
```

(Sort on the projected `timestamp` alias — NOT `ev.timeline_at` — so legacy nodes carrying only `ev.timestamp`/`ev.date_added` don't null-sort.)

- [ ] **Step 4: Run to verify pass + no regression**

Run: `NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_graph_router.py -v`
Expected: all PASS (the existing `test_events_endpoint`, `test_returns_events_with_location`, element-id tests, etc. still pass — the `timestamp` field is still returned, just coalesced).

Run: `uv run ruff check app/routers/graph.py tests/unit/test_graph_router.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t3-entity-readpath
git add services/backend/app/routers/graph.py services/backend/tests/unit/test_graph_router.py
git commit -m "fix(backend): read-path returns/sorts on coalesced ev.timeline_at not unset ev.timestamp (WP-08)"
```

---

## Task 4: Intelligence read-path coalesced timestamp (WP-08)

**Files:**
- Modify: `services/intelligence/agents/tools/graph_templates.py` (`events_by_entity` `:50-53`, `event_timeline` `:64-67`, `source_backed` `:90-92`)
- Modify: `services/intelligence/tests/test_graph_templates.py`
- Modify: `services/intelligence/tests/test_cypher_validation.py` (`:24`)

Work from `services/intelligence`. First: `uv sync --all-extras`.

- [ ] **Step 1: Write the failing test**

In `tests/test_graph_templates.py`, add:

```python
class TestTimestampCoalesce:
    def test_time_ordered_templates_coalesce_and_sort_on_alias(self):
        from agents.tools.graph_templates import TEMPLATES
        for tid in ("events_by_entity", "event_timeline", "source_backed"):
            cypher = TEMPLATES[tid]["cypher"]
            assert (
                "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp"
                in cypher
            ), f"{tid} must return the coalesced timestamp"
            assert "ORDER BY timestamp DESC" in cypher, f"{tid} must sort on the alias"
            assert "ORDER BY ev.timestamp" not in cypher, f"{tid} must not sort on ev.timestamp"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_graph_templates.py::TestTimestampCoalesce -v`
Expected: FAIL — templates still use `ev.timestamp`.

- [ ] **Step 3: Fix the three templates**

In `agents/tools/graph_templates.py`:

`events_by_entity` (`:50-53`):
```python
            "RETURN ev.title AS title, ev.codebook_type AS type, "
            "ev.severity AS severity, "
            "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp, "
            "ev.confidence AS confidence "
            "ORDER BY timestamp DESC "
```

`event_timeline` (`:64-67`):
```python
            "RETURN ev.title AS title, ev.codebook_type AS type, "
            "ev.severity AS severity, "
            "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp, "
            "l.name AS location, l.country AS country "
            "ORDER BY timestamp DESC "
```

`source_backed` (`:90-92`):
```python
            "RETURN ev.title AS event, s.name AS source, s.url AS url, "
            "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp "
            "ORDER BY timestamp DESC "
```

(Leave `co_occurring` and `top_connected` untouched — they order by `shared_events`/`connections`.)

- [ ] **Step 4: Update the stale read-only-validator example**

In `tests/test_cypher_validation.py`, change the `test_match_with_order_limit` example (`:24`) from `ev.timestamp` to the real anchor so the example tracks the new convention:

```python
            "MATCH (ev:Event) RETURN ev ORDER BY ev.timeline_at DESC LIMIT 10"
```

- [ ] **Step 5: Run to verify pass + no regression**

Run: `uv run pytest tests/test_graph_templates.py tests/test_cypher_validation.py -v`
Expected: all PASS — including `test_all_templates_are_readonly` (coalesce is a read function, still passes the read-only validator) and `test_eight_templates_registered`.

Run: `uv run ruff check agents/tools/graph_templates.py tests/test_graph_templates.py tests/test_cypher_validation.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t3-entity-readpath
git add services/intelligence/agents/tools/graph_templates.py services/intelligence/tests/test_graph_templates.py services/intelligence/tests/test_cypher_validation.py
git commit -m "fix(intelligence): graph templates return/sort on coalesced ev.timeline_at not unset ev.timestamp (WP-08)"
```

---

## Task 5: CI grep guard — forbid `ORDER BY ev.timestamp` on read templates (WP-08)

**Files:**
- Modify: `.github/workflows/ci.yml`

Work from the worktree root.

- [ ] **Step 1: Add the guard job**

In `.github/workflows/ci.yml`, add a new job (sibling of `lint-python`):

```yaml
  guard-read-templates:
    name: guard · read templates
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Forbid ORDER BY ev.timestamp on read templates (WP-08)
        run: |
          set -euo pipefail
          # ev.timestamp is never written by any write-path; read templates must
          # use coalesce(ev.timeline_at, ev.timestamp, ev.date_added) and ORDER BY
          # the projected alias. Guard the two read-template files.
          if grep -rn "ORDER BY ev.timestamp" \
              services/backend/app/routers/graph.py \
              services/intelligence/agents/tools/graph_templates.py; then
            echo "::error::Found 'ORDER BY ev.timestamp' in a read template — sort on the coalesced timestamp alias (WP-08)."
            exit 1
          fi
          echo "OK: no 'ORDER BY ev.timestamp' in read templates"
```

- [ ] **Step 2: Verify the guard logic locally**

Run (from the worktree root) the exact grep the job runs, and confirm it finds nothing after Tasks 3–4:

```bash
grep -rn "ORDER BY ev.timestamp" \
  services/backend/app/routers/graph.py \
  services/intelligence/agents/tools/graph_templates.py && echo "FOUND (guard would FAIL)" || echo "OK: guard passes"
```
Expected: `OK: guard passes` (exit-1 from grep → the `||` branch).

Also sanity-check the YAML is valid:
```bash
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"
```
Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/feature+t3-entity-readpath
git add .github/workflows/ci.yml
git commit -m "ci: forbid ORDER BY ev.timestamp on read templates (WP-08 guard)"
```

---

## Final verification (after Task 5)

- [ ] data-ingestion: `cd services/data-ingestion && uv run pytest -q` → 0 failures.
- [ ] backend: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest -q` → 0 failures.
- [ ] intelligence: `cd services/intelligence && uv run pytest -q` → 0 failures.
- [ ] ruff (mirror CI): `uvx ruff@0.15.15 check services/intelligence services/data-ingestion services/backend services/vision-enrichment` → clean.
- [ ] guard grep returns nothing on the two read-template files.

---

## Self-Review (spec coverage)

| Spec T3 item | Task |
| --- | --- |
| WP-04 flip `entity_type_normalize` default True (config.py) | Task 1 |
| WP-04 RSS lowercase enum fully covered by LEGACY_ENTITY_TYPE_MAP (no pipeline.py change) | Task 1 (verified: 8 enum values == 8 map keys) |
| WP-04 composite unique `(name, type)` after pre-dedupe; verify Community supports composite (else entity_key) | Task 2 (composite; preflight; fallback documented) |
| WP-04 fix `entity_name_type` index to a written property | Task 2 (`normalized_name`→`name`) |
| WP-04 repair = re-run existing canonicalization + duplicate_merge migrations (unchanged) | Background / Task 2 doc (not modified) |
| WP-08 `coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp` + sort on coalesced alias — graph.py | Task 3 |
| WP-08 same — graph_templates.py | Task 4 |
| WP-08 update `test_cypher_validation.py:24` | Task 4 |
| WP-08 CI grep forbidding `ORDER BY ev.timestamp` on read templates | Task 5 |
| WP-08 repair = none | Background |
