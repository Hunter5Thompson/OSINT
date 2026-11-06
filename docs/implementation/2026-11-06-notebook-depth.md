# Notebook depth: implementation and acceptance

Scope: make the 84 selected new NotebookLM source texts reachable by every
started intelligence report. Keep the existing 47 reviewed claims reachable.
Use the previously tested evidence/result contract on main `fe15309` as the
baseline; preserve both original worktrees and all original source files.

## Interface decision

Three designs were compared: one search operation, a declarative research plan,
and automatic briefing preparation. Use one `NotebookResearch.search(question)`
operation, called automatically before report research. An explicit notebook
tool can reuse the same operation for follow-up questions. No public filter DSL.

An immutable local catalog contains allowlisted original text passages and their
embeddings. The selected corpus is only 3.1 million characters; a local index
avoids extra Qdrant collections, cross-store transactions, and arbitrary file
reads in the runtime. TEI is the owned remote dependency with an injected test
adapter. SQLite and temporary files are the real local test dependency.

## Invariants and TDD acceptance

1. Retrieve a relevant passage outside the old editorial anchor, with exact
   source hash and character range; source descriptions do not become fact reviews.
2. Reject changed source/package files and disallowed candidates before writing
   a catalog; originals and previous catalogs remain unchanged.
3. Preserve background/method roles, original URL, unknown dates, review limits,
   and independent origin. Distinct passages have distinct citation IDs.
4. Bound context fairly and carry exactly the same selected passages in model
   text, API response, saved reports, and UI. Methods alone cannot prove events.
5. Every started report performs the catalog lookup; failed mandatory retrieval
   is a visible technical failure. Empty search is a normal evidence gap.
6. Real RSS examples, counterexamples, retrieval misses and technical failures
   exercise the complete path. A citation validates lineage, not factual truth.

Implement each behavior as a red test, minimal green implementation, then
refactor. Run focused tests during work and full affected suites after changes.

## Delivery

Build a hash-bound catalog under `/data`, qualify a candidate instance against
the existing single local LLM, then roll out the qualified application modules
with recorded image/config revisions and a rollback plan. Preserve original
database collections and running ingestion/model services. No model training,
automatic mass-report generation, or import of the 29 deferred notebooks.

Evidence directory: `/data/odin-notebook-depth/20261106`.

## Implemented pipeline

`run_intelligence_query` searches the pinned archive before research starts.
`notebook_search` reuses that operation for narrower follow-up questions. Only
whole selected evidence blocks enter synthesis; the same artifact supplies the
HTTP response, SSE stream, saved Neo4j report and source cards after reload.
Catalog failure is a visible pipeline failure; a search miss is an evidence gap.

The selected full source texts are segmented into 2,351 overlapping passages:
725 background passages from 30 sources and 1,626 method passages from 54 sources.
The independent audit covers all 3,148,647 source characters. Files and extracted
text are hash-checked; source dates remain unknown and factual verification is
explicitly absent. The 29 deferred notebooks remain excluded. Existing reviewed
claims retain their separate review contract and search path.

The archive uses Qwen3-Embedding-0.6B / 1,024 dimensions. Queries carry the
[model's retrieval instruction](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
documents do not. Search selects up to three background passages and one method
passage, with at most two passages per independent origin and cosine >= 0.45.
Matched slices include one neighbour on either side, with exact reconstructed
text ranges and hashes. This prevents a quoted view and the author's rebuttal
from being separated at the retrieval boundary. Overlapping windows are not
repeated; a relevant method follows the first background window so it can fit
inside the shared 14,000-character archive context budget.
These are bounded retrieval defaults, not calibrated factual confidence scores.

For original passages, synthesis uses the already loaded base model with
reasoning enabled and a 5,000-token generation allowance including reasoning.
The final source-check pass reserves 2,000 tokens for direct report output;
it does not open another reasoning block. The deployed vLLM 0.18.1 has no
separate thinking-token budget, and the earlier two-reasoning-pass experiment
exhausted generation without returning report text. Truncated final revisions
fail explicitly. The archive Compose overlay allows 220 seconds for the graph,
within the existing 240-second query and 300-second backend deadlines.
The existing short-summary adapter remains the legacy path. A live
counterexample exposed attribution inversion with both the summary adapter and
non-reasoning base generation; the reasoning comparison corrected that case.
This is bounded qualification, not proof of general semantic correctness.
No reasoning text is included in the report response.

Citation identity is checked against the consumed artifact; formatting of exact
IDs is normalized. Every draft gets one source-check and revision pass before
publication, including attribution, negations and date limits. Unknown/missing identities
fail visibly. This guard does not prove that every paraphrase follows from its
citation. Method-only input produces abstention; archive-only input cannot
declare a current threat assessment. Literal original passages remain available
for the analyst to check interpretations.

The obsolete GDELT DOC tool is disabled by default after a live HTTP 429 caused
an avoidable report failure. Canonical raw-file ingestion remains active.

## Build and operate

From `services/intelligence`, with TEI configured and the same locked environment:

```bash
uv run python scripts/build_notebook_catalog.py \
  --intel /data/odin-notebooklm-ingest/20261105-triage-delta/packages/intel \
  --methods /data/odin-notebooklm-ingest/20261105-triage-delta/packages/methods \
  --output /data/odin-notebook-depth/next/catalog.sqlite
sha256sum /data/odin-notebook-depth/next/catalog.sqlite
```

Create the output parent directory first. Existing catalogs are never overwritten.
Use `docker-compose.notebooks.yml` after the chosen application configuration;
set `ODIN_NOTEBOOK_CATALOG` and `ODIN_NOTEBOOK_CATALOG_SHA256`. `/health` exposes
archive coverage/hash and fails if a configured archive cannot be validated.
Unsetting the catalog path disables archive enrichment for recovery; keep the
new backend/frontend schema so stored passage metadata survives later updates.

## Validation and handoff

TDD red/green evidence is recorded for 27 implementation steps. Final affected
suites: Intelligence 899, Backend 1,204, Frontend 961; all passed. Backend mypy,
both Python linters, frontend lint/typecheck, browser typecheck and production
build passed. A disposable Neo4j instance passed all 12 persistence integration
cases and was removed after confirming only its marker remained. Three browser
cases passed, including notebook background/method provenance after reload;
the screenshot was visually inspected.

The full catalog audit, real RSS requests/responses, failed comparisons, image
receipts, protected-worktree checks and runtime/rollback record live in the
external evidence directory. Original worktrees and source archives are preserved.
External fact checks, broad model accuracy evaluation and human acceptance of
analytical interpretations remain separate from these pipeline checks.
