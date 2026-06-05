# Entity Resolution — Neo4j KB

Methodology for deduplicating `:Entity` nodes in the knowledge graph and keeping
the ingest write-path from regenerating duplicates.

## Policy: "Name != Identity"

Merge **only** when two names *surely* denote the same real entity.

- ✅ National-qualified aliases / pure case+type variants:
  `US Navy` · `U.S. Navy` · `United States Navy` → **`U.S. Navy`** (`MILITARY_UNIT`)
- ❌ Generic names stay separate: `Navy` is **not** `U.S. Navy` (could be Royal /
  Iranian / IRGC Navy depending on context). Generics are tagged `generic=true`.
- Same exact string typed both `ORGANIZATION` and `MILITARY_UNIT` → collapse to
  `MILITARY_UNIT` (coast guards → `ORGANIZATION`, a deliberate choice).
- Cross-name aliases (e.g. `IRGC` ≡ `Islamic Revolutionary Guard Corps`) are a
  separate **Tier-2** decision — not part of the safe same-identity merge.

## One-off graph cleanup (manual, reviewed)

Always: **JSON backup → dry-run table → merge → verify**.

1. Dump affected nodes + relationships to `backups/` (git-ignored — live data).
2. Print a dry-run table (`name`, `type`, `mentions`, `degree`) per curated group.
3. Merge only an **explicit, enumerated, curated** group list (never an
   algorithmic sweep of all clusters — that is entity corruption and the
   auto-mode classifier will, correctly, block it).
4. Merge with `apoc.refactor.mergeNodes(ns, {properties:'discard', mergeRels:true})`;
   preserve original spellings in `e.aliases`; tag `e.canonicalized_at`.
5. Verify: 0 orphaned fragments, mention counts preserved, sample edges re-point.

## Ingest write-path canonicalization

The DB cleanup is cosmetic on its own — the same rules must run before every
Neo4j write or the pipeline recreates the duplicates on the next run.

- Single source of truth: `services/data-ingestion/canonicalize.py`
  (`canonicalize_entity(name, type) -> CanonicalEntity`). Pure, no I/O, curated
  alias map mirroring the merges above. Generics pass through unchanged.
- Wired **before** the write in both paths:
  - `pipeline.py` (RSS/GDELT/Telegram — the continuous duplicate generator)
  - `nlm_ingest/ingest_neo4j.py` — entity upsert **and** the name-based MATCHes
    (relation endpoints, claim→entity links) are canonicalized consistently so a
    rename never orphans a relationship.
- `write_templates.py` stays deterministic Cypher; aliases are append-deduped,
  never overwritten.

To extend coverage, add a curated entry to `_ALIAS_GROUPS` in `canonicalize.py`
and a test in `tests/test_canonicalize.py` (TDD: red first).
