# Corpus cleanup — odin_intel content quality (2026-06-19)

Triggered by the essay-quality test: a small-model vs Opus comparison both stumbled on
the same junk source (a base64-image SWP-WebMonitor chunk). Goal: stop junk reaching
retrieval and ingest.

## Survey (corrected)

First-pass survey read only the `content` field and reported ~57% junk. **That was a
field-reading bug:** bare `rss` points store their prose under `summary` (no `content`
key); `rag.evidence._excerpt` already falls back content→summary→description→title.
After mirroring that fallback the real picture is:

- `odin_intel` total: **649k points**, but **621k are structured data** (GDELT-GKG 543k,
  FIRMS 76k, USGS/EONET/…) that are **outside the analysis read-path** (corpus_policy
  admits only rss / rss_fulltext / suv_structured + NLM). Not prose junk — index bloat (Tier 3).
- **Analysis lane: ~24.9k points; real junk ≈ 1.6% (404), not 14k.**

## Tier 1 — read-path + ingest guards (SHIPPED, branch, not deployed)

Shared predicate `content_quality.content_junk_reason(text)` (logic twin in both services,
drift-tested): flags empty / base64-image-heavy / too-short / too-few-words / long
keyword-soup-without-structure. NLM single-sentence claims pass; bullet lists & ;:-prose pass.

- **Read-path** (`intelligence/rag/corpus_policy.validate_lane`, analysis lane only): drops
  junk results, evaluating the same content→summary→description→title text the model is shown
  (B1 fix — checking only `content` would have dropped ~24 wire/gov feeds). Logs
  `corpus_content_dropped` with a reason breakdown. Realtime/telegram lane untouched.
- **Ingest-guard** (`data-ingestion/feeds/fulltext_collector`): strips base64 data-URIs +
  skips junk chunks before embed/upsert; all-junk body → terminal `skipped_lowquality`
  (no supersede, no infinite retry).
- Tests: 333 (intelligence) + 1010 (data-ingestion) pass; ruff clean. Two-stage reviewed
  (subagent + code-reviewer); B1 blocker + S1/S2/N1 all fixed.
- **Deploy note:** read-path change is live only after the intelligence service is
  rebuilt/restarted; ingest-guard after data-ingestion restart. Non-destructive + reversible.

## Tier 2 — delete/archive DRY-RUN (prepared, NOTHING deleted)

`scripts_corpus_cleanup_dryrun.py` applies the exact gate to the analysis lane and writes
candidate IDs to `odin-data/notebooklm/cleanup_candidates.json`. Result:

- **404 candidates (1.63%)**: too_few_words 335 (mostly Google-News `<a href>` redirect
  summaries — no analyzable text), base64_heavy 40 (swp-berlin WebMonitor), too_short 24,
  low_prose 5 (Bundestag Drucksache titles w/o body). Sources: rss 361, rss_fulltext 43.
- **Decision pending (operator):** delete the pure junk (Google-News link-only + base64),
  keep/leave thin-but-real headlines, or just archive. Read-path already excludes all 404
  from retrieval, so deletion is storage/index hygiene only — do it backup-first.

## Tier 3 — ADR (parked): collection split

**Context:** `odin_intel` holds 649k points but 96% are structured event/geo data
(gdelt_gkg, firms, usgs, eonet, portwatch, gdacs, ucdp) that the analysis read-path never
retrieves. They bloat the index and conflate three different data shapes.

**Decision (proposed, NOT yet taken):** split into purpose-built collections —
`odin_intel` (analysis prose: rss/rss_fulltext/suv/NLM), `odin_events` (GDELT-GKG),
`odin_geo_signals` (FIRMS/USGS/EONET/…). Keeps each retrieval space clean and right-sized.

**Status:** deferred — does NOT block essay quality (structured data is already out of the
analysis read-path). Revisit as a dedicated migration (re-point collectors + read clients +
backfill/migrate existing points). Track as a TASK.
