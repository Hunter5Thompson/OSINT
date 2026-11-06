# Packages A/B: result states and reviewed evidence

Base: fe1530942218510e2ac6913bd06ab38d2fce3853 (verified remote main).
Isolated integration worktree; production runtime, data and models unchanged.

Acceptance:
- Inner research/synthesis exceptions become explicit HTTP errors and SSE error events.
- Empty structural evidence never invokes normal synthesis or emits an assessment.
- Tool execution has requested/started/succeeded/failed/blocked events; only starts consume budget.
- All 47 frozen curated statements retain claim/parent/origin identity, qualifications,
  anchors, date semantics and original date precision through prompt/artifact/API/display.
- Whole evidence blocks survive budgeting, with matching public citation IDs.
- Parameter-bound reviewed Claim reads are reachable without bypassing spatial restrictions.
- Existing parser tests and historical response replay stay green.

Sequence: regression tests (red), minimal contracts/workflow/adapters (green), backend/UI,
service checks and evidence report. Search ranking, inference verification, model training,
release and live factual acceptance are separate work packages.

## Implemented contract

- `/query`: internal exceptions (including caught node failures and empty synthesis)
  produce HTTP 502 with `status=failed`, `code=INTEL_PIPELINE_FAILED` and a safe
  user-facing message. The backend forwards this as an SSE `error`, never a `result`.
- Successful execution without consumed structural evidence returns
  `status=completed|partial`, `answerability=insufficient_evidence`, null threat and
  confidence, `assessment_status.{threat,confidence}=not_assessed`, and a deterministic
  German abstention limited to this research run. The synthesis model is not invoked.
- Evidence-bearing runs have `answerability=undetermined`: transport success is not
  a factual answerability certificate. Blocked budgets and partial source markers
  produce `status=partial` and a visible limitation in generated reports.
- The existing declared-field parser remains in use. Compatibility defaults for
  malformed fields remain explicitly marked `default`; UI suppresses these metrics.
- `tool_trace` remains the backward-compatible list of starts; additive `tool_events`
  and immediate structured logs distinguish requested, started, succeeded, failed and
  blocked proposals by call ID. RSS/GDELT/vision exceptions now remain technical failures.
- `use_legacy=true` is a grounded compatibility path through the same evidence gate.
  The former knowledge-only multi-LLM chain is retired from public execution. Old
  node helpers remain for replay tests; no automatic fallback is introduced.
- `evidence_id` identifies one claim; `source_ref_id` continues to identify its stored
  parent. The typed `review` preserves original source ID, original investigations,
  independent lineage, qualification, evidence URLs, review date and text anchor.
  Local filesystem paths and write authorization fields are deliberately not public.
- `publication_or_reference_date` remains verbatim with `date_precision=as_recorded`.
  No ambiguous date is promoted to `published_at` or assigned an invented day.
- Whole evidence blocks travel through researcher history and synthesis budgets.
  Research history remains capped at 12,000 characters and synthesis research at
  18,000; the individual history slot is 6,000 to fit reviewed metadata. Repeated
  claim IDs do not consume the synthesis budget again.
- Reviewed claim summaries survive backend SSE, report persistence, hydration and
  source cards. Confidence can be null in saved reports, and explicitly clears an
  earlier score. Links accept HTTP(S) without embedded credentials.
- `reviewed claims about "RUSI"` (also candidate ID, statement hash or exact evidence
  URL) routes to a deterministic, bound Neo4j Claim/EXTRACTED_FROM template. It is
  deliberately unsupported in non-global scopes until reviewed spatial derivation
  exists. It creates no new factual relations.

## Additional defect found by integration tests

The read-side prose-length guard rejected C019, C055 and C029 although their curated
claim contracts were present. A narrow exception now accepts short statements only
when the typed Notebook review matches the statement, notebook and package. Empty,
base64-heavy, malformed, foreign-lane and spatially excluded hits stay excluded.
This is not a new factual review or a relaxation of ingestion rules.

## Review corrections and integration (2026-11-01)

- R01: all five report Cypher projections preserve null confidence. Real isolated
  Neo4j tests cover create/update returns, list, get-by-id, get-by-scope and an
  unrelated later edit. Explicit 0.0 and 0.73 remain unchanged.
- R02: both country briefing save routes preserve assessment status,
  verification status and reviewed evidence on their chat copy. A real database
  test saves a reviewed answer followed by an abstention, then reloads both
  messages to verify that each retains its own original metadata.
- R03: live and reloaded chat abstentions say no model assessment. Ordinary
  model replies and legacy unknown metadata remain distinct.
- The complete candidate was integrated onto fe15309 without committing or
  modifying main. Current operator authorization, admission, deadlines,
  disconnect cancellation and UI error handling remain. Pipeline 502 errors
  coexist with MODEL_BUSY/429 and MODEL_TIMEOUT/504; response bodies cannot
  override those HTTP status classifications. Source cards retain main's contrast.

## Verification (integrated worktree, 2026-11-01)

- Intelligence: 861 tests; Ruff.
- Backend: 1,203 tests; Ruff; strict mypy, 97 source files.
- Real isolated Neo4j: 11 persistence tests.
- Frontend: 959 tests; ESLint; full TypeScript check; browser TypeScript check; build.
- Built SPA: two Chromium tests for separated original sources/dates and persisted
  no-evidence state, including chat after reload. Screenshots inspected; no native
  GPU or human acceptance claim.
- Total: 3,036 passing tests. `git diff --check` passes.
- All 47 frozen reviewed payloads traverse the actual Qdrant tool, ToolNode,
  researcher compaction, synthesis call boundary and FastAPI route with mocked
  providers. Their metadata also passes actual backend SSE and frontend formatting.
- All twelve historical reports reproduce the previous corrected parser values;
  the four false CRITICAL cases remain corrected. Eleven original parser tests pass
  as part of the complete service suite.
- No live model generation or retrieval-quality evaluation was performed. The
  captured model inputs are real application inputs delivered to test doubles.
- Nonblocking existing diagnostics: Starlette/httpx deprecation, jsdom canvas
  limitation and Vite chunk-size warning. Browser runner setup failures were fixed
  (service working directory, JSON import attributes, browser binary, query-string
  fixture matching); failed-attempt logs remain in the evidence archive.

## Release boundary and restart

Active delivery: `/data/odin-worktrees/intel-evidence-integrated-20261101`.
Detached HEAD: `fe1530942218510e2ac6913bd06ab38d2fce3853`; changes uncommitted.
The original candidate on c003ed6 also contains R01-R03 fixes and is preserved.
The protected original checkout remains at 813594a with its foreign changes.
No commit, push, merge into main, rollout, production restart, import or live
model generation occurred. Database writes were confined to a newly created,
network-isolated, temporary Neo4j test container; it was removed after testing.

Evidence: `/data/odin-intel-relation-evaluation/20261101-review-fixes-200754Z/`.
Red/green logs, final integrated patch and new files, provenance hashes, browser
images and cleanup receipt are retained. The review findings and local integration
are complete. A coordinated release still needs an authorized clean commit/build,
image digests, CI and an approved data-compatible rollback; older readers do not
understand the new persisted metadata. Search and factual live evaluation remain
separate packages. Technical transport success is not a factual acceptance.
