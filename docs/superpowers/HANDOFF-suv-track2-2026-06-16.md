# HANDOFF — SUV Track 2 (Defense Companies → Graph + Qdrant)

**Date:** 2026-06-16 · **Branch:** `worktree-suv-track2-skeleton` (pushed to `feature/suv-track2-companies`, NO PR yet) · **Base:** main `0dc96c0` (post-T4)

## TL;DR — where to start
The walking-skeleton GATE passed (GO) and the deterministic-extraction CORE is built + reviewed + **proven on the real crawl (77/77 companies)**. **3 of 13 tasks done.** Continue with **Task 4 (countries.py)** → through Task 13, using the **proven workflow** (writing-plans is already refreshed; go straight to subagent-driven-development with full two-stage review per task). The remaining tasks are the graph/Qdrant/CLI-gate/intelligence half — heavier and including the **human curation gate + live writes**, so they get full review rigor.

## Authoritative docs (all on this branch)
- **Plan (REFRESHED, execute this):** `docs/superpowers/plans/2026-06-14-suv-track2-companies.md`. **READ THE "## REFRESH 2026-06-16" BLOCK AT THE TOP FIRST** — it supersedes the original where they conflict (Task 0 done; Task 3 → deterministic `parse.py`, NOT vLLM; Task 1 website absent; Task 4 = the real address→country work; all integration points re-verified vs current main with exact file:line).
- **Design spec:** `docs/superpowers/specs/2026-06-14-suv-track2-companies-design.md` (review-corrected; architecture + the mandatory `--approved-matches` gate + the corpus_policy pair-validation reasoning).
- **Walking-skeleton findings:** `docs/superpowers/specs/2026-06-16-suv-track2-walking-skeleton-findings.md` (the GO + scope-simplification deltas).
- **Memory:** `reference_suv_source.md` (auto-loaded) has the same status + the gotchas.

## DONE (committed on this branch, 6 commits, working tree clean)
- `7047954` skeleton spike (GO) · `e6734d2` plan refresh · `84baf9c` .gitignore restore (see Gotchas).
- **T2-1** `suv_structured/schemas.py` — `Company` model + `profile_text` (5 tests). `19e849f`
- **T2-2** `suv_structured/fetch.py` — `fetch_directory_markdown` via crawl4ai `/md` (3 tests). `6289047`
- **T2-3** `suv_structured/parse.py` — DETERMINISTIC markdown→`list[Company]` + German normalizers `parse_employees`/`parse_revenue_eur`/`parse_founded`/`parse_products` + `derive_hq` (7 tests, **review APPROVED**). `56fd518`
- **Proven on real data:** parsing `scratch/suv_dir.json` (the real crawl, gitignored) → **77 companies**, coverage hq_country/hq_city/founded/products = 77/77 (76 Deutschland + 1 Niederlande=KNDS), description 76/77, employees 73/77, revenue 72/77 (undisclosed → None, honest). All 20 suv+contract tests green.

## REMAINING — Tasks 4–13 (per the plan; full two-stage review each)
4. **`countries.py`** — map the parser's German HQ country ("Deutschland"/"Niederlande") → the existing graph `Entity{type:"COUNTRY"}` node NAMES (likely English: "Germany"/"Netherlands"). Unmapped → `HEADQUARTERED_IN` skipped+logged. (The parser already derives the German country string; this maps it to the graph.)
5. **`write_templates.py`** — deterministic SUV Cypher: `HEADQUARTERED_IN` `Entity{ORGANIZATION}`→`Entity{type:"COUNTRY"}`, **MATCH-only for country (never MERGE)**. Keep SEPARATE from `nlm_ingest/write_templates.py` (that dict is key-locked by `test_nlm_relations.py:56`).
6. **`match_report.py`** — produce the dry-run match report (the gate's data): per company → `decision: match|new|ambiguous` + proposed existing `Entity` + `approved: false`. Uses `canonicalize_entity` (canonicalize.py:110) — note it does NO fuzzy matching, so "Rheinmetall AG" won't auto-match "Rheinmetall"; surface as ambiguous for curation.
7. **`build_companies.py`** — Neo4j writer (HTTP tx API `POST {neo4j_url}/db/neo4j/tx/commit` + `$params`, like `nlm_ingest/ingest_neo4j.py`). In-place enrich existing `Entity` via **targeted SET of named props only** (never `SET e = {}`); aliases **append+dedup** (pattern: `nlm_ingest/write_templates.py:18` `e.aliases = coalesce(...) + [a IN $aliases WHERE NOT a IN ...]`). NEW company → MERGE `Entity{type:"ORGANIZATION"}`. No `:Company` label.
8. **Qdrant profiles** — one point/company in `odin_intel`. **POINT-ID COLLISION FIX (critical):** all 77 companies share the directory `suv_url`, so DON'T key the point-id on suv_url — key on `slug(name)` (uint64 `int(sha256("suv_structured|"+slug(name))[:16],16)`, fulltext pattern). Payload via `provenance_fields(source_type="dataset", provider="suv.report")` (provenance.py:26), `content=profile_text(c)`, **NO credibility field** (read-side; `credibility.py:63 suv.report:0.78` already wired). TEI embed: `POST {tei_embed_url}/embed {"inputs":text}` → 1024-dim.
9. **`cli.py`** (`odin-suv-structured`) — `fetch | parse | build`, with the **HARD `--approved-matches <match_report.yaml>` gate**: build refuses without it; refuses entries still `ambiguous`/`approved:false`; re-derives matches and aborts if they diverge from the approved report (stale approval can't write wrong merges).
10. **Intelligence `rag/corpus_policy.py`** — pair-validation. Add `"suv_structured"` to `ANALYSIS_SOURCES` (:18). Replace the flat `_ANALYSIS_TYPES` (:95) with a source→expected-source_type map so the PAIR is validated (`validate_lane` :98-127). Must DROP `rss/dataset` and `suv_structured/rss`, KEEP `rss/rss`, `rss_fulltext/rss`, `suv_structured/dataset`, NLM/`notebooklm`; `rss/gdelt` still dropped. Tests in `tests/test_corpus_policy.py` `TestGuardAndMerge`. **Cross-service → needs an intelligence image rebuild on deploy.**
11. **Packaging** — `pyproject.toml` `[project.scripts]` (:38-42) add `odin-suv-structured = "suv_structured.cli:cli"`; `[tool.hatch...wheel].include` (:48-61) add `"suv_structured/**/*.py"` + `"suv_structured/seeds/*.yaml"`; `Dockerfile` (:18-27) add `COPY services/data-ingestion/suv_structured/ suv_structured/`. (data-ingestion has NO `.vscode` — pytest.ini auto-discovers, no change needed.)
12. **Full suite + lint** both services green.
13. **Operational run (HUMAN GATE → live writes):** snapshot/dry-run → emit `match_report.yaml` → **user curates/approves** (the Human-in-the-Loop checkpoint — present the enumerated company→Entity matches per [[feedback_entity_resolution]] "Name != Identity") → `build --approved-matches` → verify. **Take a Neo4j backup first** (see the T4 repair runbook: community has no STOP DATABASE → offline `neo4j-admin dump` in a throwaway container).

## Proven workflow to continue (same as T1–T5 + the SUV core)
EnterWorktree already exists (this one) → plan already refreshed → **subagent-driven-development**: per task = sonnet implementer (TDD red→green) + sonnet spec-review + sonnet quality-review (the heavy tasks 7/9/10/13 deserve the full two-stage; tiny ones can be one combined review) → opus final holistic → finishing-a-development-branch → PR → CI poll. Run tests with `cd services/data-ingestion && uv run pytest` (NOT bare `python3` — deps in uv venv); intelligence tests need `cd services/intelligence && uv run pytest`.

## Decisions to honor
- **Deterministic, no LLM** on the extraction path (skeleton proved 77/77). Committed YAML seed stays as the reproducible human-review gate; producer = `parse.py`.
- **Two-Loop write-path discipline:** no LLM-generated Cypher; deterministic templates + `$param` binding only.
- **Entity-resolution:** "Name != Identity" — only curated approved merges via the hard `--approved-matches` gate; ambiguous → surfaced for curation, never auto-merged.
- TDD mandatory; two-stage review per task (never skip, per [[feedback_never_skip_reviews]]).

## Gotchas (learned this session)
- **NEVER `>` a tracked file.** A skeleton-spike `printf 'scratch/' > .gitignore` CLOBBERED the repo's root `.gitignore` (lost `!services/data-ingestion/uv.lock` re-include → broke `test_docker_runtime_contract`). Fixed `84baf9c`. Always Read+append.
- **Point-id collision:** companies share the directory URL → key Qdrant point-id on `slug(name)`, not `suv_url` (Task 8).
- **`canonicalize_entity` does NO fuzzy match** — "Rheinmetall AG" ≠ "Rheinmetall"; the match_report surfaces these for curation (Task 6).
- **crawl4ai** at `http://localhost:11235`, `POST /md {"url":...,"f":"fit"}` → markdown under `markdown`/`fit_markdown` key (fetch.py wraps it). Real crawl saved in local `scratch/suv_dir.json` (gitignored) — usable as a TEST FIXTURE for build/parse integration checks.
- git: `cd <worktree-root>` before `git add`; branch is `worktree-suv-track2-skeleton`, push refspec `worktree-suv-track2-skeleton:feature/suv-track2-companies`.

## Worktree
`/home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/suv-track2-skeleton`. The stale docs-only `feat/suv-track2-companies` (local) is superseded by this branch — ignore/delete it.
