# Current research for ODIN

Status: implementation in progress. Baseline: `39b79dd1ce7d8d93a175a0fa35c7cb46206c028a`.

The accepted requirement is current, source-grounded analysis with bounded scenario
assessment. The specification and initial live failures are preserved under
`/data/odin-agent-enablement/20261106-plan` and
`/data/odin-iran-assessment/20261106T143306Z`. Runtime evidence and red/green logs
belong under `/data/odin-agent-enablement/20261106-implementation`.

## Interface decision

Three independent designs considered a minimal one-shot interface, an explicit
research session, and a trivial default caller. Use a run-scoped deep module with
one `search(question)` operation. Its immutable run pins and shared budget give
session semantics without a second lifecycle interface. Inject the instance via
LangGraph runtime context, never as an object in serialized state. Current
research is the analysis endpoint's conservative default; an explicit historical
request opts out. Language recognition cannot remove the research requirement.

## Invariants and test seams

1. A current report performs baseline research even when the model emits no tool call.
2. Follow-up queries cannot reset as-of time, scope, deadline, or request/credit budget.
3. Search, extraction, publication, event, and ingestion times keep distinct meanings.
4. Search relevance, matching citations, and multiple publications never certify truth.
5. Failed/empty/blocked retrievals have distinct receipts; cancellation propagates.
6. Current evidence precedes archive context in a bounded prompt; summaries describe
   only evidence actually passed to synthesis.
7. Public web context is not spatial occurrence evidence without a scoped source.
8. Private archive content and credentials never enter external search requests.
9. Research does not write to the curated corpus or mutate source archives.

Tests cross the public research interface, the `/query` interface, and report
create/read plus browser rendering. External HTTP, the owned corpus, time and the
model are injected adapters; pure selection and provenance logic remain real.

## Implementation sequence

- Preserve baseline and failure reproduction; qualify dependency update separately.
- Build Tavily search/extract with source metadata and bounded failure handling.
- Add mandatory research and a follow-up tool sharing one run context.
- Propagate coverage and web evidence through saved reports and the UI.
- Run contract, service, database, browser and live-source checks independently.
- Review standards and spec against the baseline; prepare a pinned release and rollback.

Baseline intelligence suite: 900 tests passed on the original lockfile.
The Tavily credential is outside the worktree in a private runtime file.

## Implemented candidate

The candidate uses Tavily Search/Extract plus publication-filtered local corpus
reads, a deterministic research stage and focused follow-up queries in one
runtime context. A local, time-limited query planner sees only the user's question
and translates it into short English discovery terms; it never sees archive text.
The first live German query exposed unrelated news selection and is retained as
failed content qualification, not a success metric.

The API defaults to current research. Historical requests opt out explicitly;
the dossier chat exposes that choice. Original reads, snippets, stored original
chunks, publication, observation and retrieval time remain separate through
report persistence. Scenario discussion is conditional; forecast assessment and
external fact verification remain unavailable.

Maintenance update was tested independently before graph integration: LangGraph
1.2.20, langchain-core 1.7.6 and langchain-openai 1.7.4, locked with uv 0.10.0;
907 tests passed at that checkpoint. No framework replacement was needed.

Technical evidence so far: 916 intelligence tests (plus a subsequent local
original provenance regression), 1,206 backend tests, 962 frontend tests,
13 isolated Neo4j tests and four browser tests. Further review and live content
qualification are in progress. Production containers have not been changed.
