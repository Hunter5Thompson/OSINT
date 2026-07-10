# Tree Search Retrieval Design Spec

**Date:** 2026-05-17

**Status:** Revised draft — reviewed against `origin/main` on 2026-06-29;
implementation requires a follow-up plan

**Scope:** PageIndex-inspired document-tree retrieval for ODIN's longform RAG path, with optional hybrid Qdrant scoring and Neo4j context expansion.

**Registry:** `TASKS.md` → TASK-117.

**External reference:** PageIndex Tree Search tutorials:
- https://docs.pageindex.ai/tutorials/tree-search/llm
- https://docs.pageindex.ai/tutorials/tree-search/hybrid

**Related ODIN specs:**
- [NotebookLM ODIN Ingestion Design](./2026-04-03-notebooklm-odin-ingestion-design.md)
- [Qdrant v2 Hybrid Migration Design Spec](./2026-05-03-qdrant-v2-hybrid-migration-design.md)
- [Qdrant Collection Source-of-Truth Sync](./2026-04-30-qdrant-collection-sot-design.md)

---

## 1. Motivation

ODIN already has dense-vector retrieval, reranking, and optional Neo4j graph context in `services/intelligence/rag/retriever.py`. That is useful for short feed items and entity-heavy OSINT snippets, but it loses structure when the source is a long document: NotebookLM transcripts, reports, PDF exports, dossiers, intelligence assessments, or long GDELT-linked articles.

The PageIndex Tree Search pattern is valuable because it treats documents as structured trees rather than flat chunk bags. A query can select the relevant chapter, section, subsection, and only then the evidence chunks. The hybrid PageIndex variant additionally combines vector scores with tree-level traversal, which maps cleanly to ODIN's existing Qdrant + TEI rerank + Neo4j setup.

**Target outcome:** ODIN gains a tree-aware retrieval path that returns ranked sections and evidence chunks with stable source paths, improving longform answer quality and source traceability without adding PageIndex as a runtime dependency.

---

## 2. Decision Summary

### Chosen Approach: Internal Tree Retrieval, PageIndex-Inspired

Do not run PageIndex as a new service. Implement the pattern inside ODIN:

1. Build a `DocumentTree` during longform ingestion.
2. Store chunk payloads in Qdrant with `doc_id`, `node_id`, `parent_id`, `tree_path`, `heading`, and `depth`.
3. Keep Phase 1 tree metadata in Qdrant payloads only; add Neo4j `DocumentSection` writes in Phase 2 if retrieval evaluation justifies it.
4. Add `tree_search()` in `services/intelligence/rag/`.
5. Route eligible longform queries through:
   `dense retrieval -> node-score aggregation -> LLM node selection -> evidence chunk expansion -> TEI rerank -> Neo4j context`.
6. Preserve the current analysis/realtime lane policy and emit section metadata
   through ODIN's structured `[EVIDENCE]` contract.

### Why Not Use PageIndex Directly?

- ODIN already owns Qdrant, Neo4j, TEI, LangGraph, and local vLLM infrastructure.
- Introducing a new indexing abstraction would duplicate payload contracts and retrieval controls.
- ODIN needs deterministic graph writes and strict schema validation; a thin internal implementation fits those rules better.
- The key value is the retrieval algorithm, not the library dependency.

---

## 3. Design Alternatives

### Option A: Flat Retrieval Only

Keep the current retriever and add better reranking prompts.

**Pros:**
- Lowest implementation cost.
- No ingestion schema change.
- No additional LLM traversal call.

**Cons:**
- Still loses document hierarchy.
- Hard to cite sections instead of isolated chunks.
- Poor fit for long reports and transcripts.

**Decision:** Reject. This does not solve the core problem.

### Option B: Adopt PageIndex as a Runtime Dependency

Use PageIndex APIs directly to index and query long documents.

**Pros:**
- Fastest way to mirror the tutorial.
- Good reference implementation for tree traversal.

**Cons:**
- Adds a new runtime component and storage abstraction.
- Creates overlap with Qdrant payload schema and Neo4j source graph.
- Harder to enforce ODIN's schema checks, feature flags, and local inference controls.

**Decision:** Reject for production; acceptable as a throwaway benchmark only.

### Option C: Internal Tree Retrieval Layer

Implement a minimal ODIN-native tree retriever using existing Qdrant, TEI, Neo4j, and vLLM clients.

**Pros:**
- Keeps ODIN's current storage and operational model.
- Works with dense-only `odin_intel` first, then with `odin_v2` hybrid retrieval later.
- Improves citations and section-level reasoning.
- Can be feature-flagged and rolled back cleanly.

**Cons:**
- Requires ingestion payload changes.
- Adds one LLM call for tree node selection.
- Needs evaluation fixtures to prevent prompt-driven retrieval drift.

**Decision:** Choose Option C.

---

## 4. Scope

### Phase 1 Scope

Phase 1 is intentionally narrow:

- Report/manual longform ingestion through `rag/indexer.py`.
- NotebookLM transcripts only after a separate longform writer exists. The
  current NLM Qdrant path stores one point per extracted claim and must remain
  unchanged in Phase 1.
- Dense-only Qdrant search using the current `odin_intel` collection.
- A lightweight document tree generated by deterministic text structure parsing.
- Tree-aware retrieval available behind `enable_tree_search=false` by default.
- No frontend changes.

### Phase 2 Scope

After Qdrant v2 hybrid migration is complete:

- Use hybrid dense + BM25 score aggregation.
- Add tree-search as an optional mode to `qdrant_search`.
- Apply to long RSS/GDELT documents where headings or extracted sections exist.
- Add tree-path citations to report generation.

### Non-Goals

- Do not replace existing dense retrieval for short feed items.
- Do not write LLM-generated Cypher for Neo4j writes.
- Do not add PageIndex as a service dependency.
- Do not re-chunk the entire historic corpus in Phase 1.
- Do not modify WorldView globe layers.

---

## 5. Current System Fit

### Existing Relevant Components

- `services/intelligence/rag/retriever.py`
  Current dense retrieval, rerank, graph context flow.

- `services/intelligence/rag/chunker.py`
  Existing chunking boundary. Tree-aware chunking should live beside or behind this.

- `services/intelligence/rag/indexer.py`
  Manual/RAG indexing path. Phase 1 tree ingestion should target this path first.

- `services/data-ingestion/nlm_ingest/`
  NotebookLM transcript, extraction, and Neo4j ingestion path.

- `services/data-ingestion/feeds/base.py`
  Shared collector point builder for Hugin feeds. Phase 2 payload fields should be added here only after the longform path is stable.

- `services/data-ingestion/gdelt_raw/writers/qdrant_writer.py`
  GDELT GKG Qdrant writer. It should remain unchanged in Phase 1.

- `services/intelligence/agents/tools/qdrant_search.py`
  Tool entrypoint used by the ReAct agent. It currently retrieves separate
  analysis and realtime lanes, applies tier boosting, and emits budgeted
  `[EVIDENCE]` blocks. Tree search must preserve those contracts and apply only
  to eligible longform analysis points.

- `services/intelligence/rag/evidence.py`
  Canonical evidence codec and provenance boundary. `tree_path`, `heading`,
  `node_id`, and `chunk_id` must be modeled here before section citations can
  reach synthesis safely.

### Compatibility With Qdrant v2 Hybrid Migration

Tree Search is orthogonal to Qdrant v2:

- `enable_hybrid` controls dense-only vs dense+sparse Qdrant schema.
- `enable_tree_search` controls whether retrieval aggregates by document tree nodes.

The flags must remain independent:

| Mode | `enable_hybrid` | `enable_tree_search` | Behavior |
|---|---:|---:|---|
| Current default | false | false | Dense search -> rerank -> graph context |
| Phase 1 tree | false | true | Dense search -> node aggregation -> LLM tree selection -> rerank |
| Future hybrid | true | false | Hybrid search -> rerank -> graph context |
| Future full | true | true | Hybrid search -> node aggregation -> LLM tree selection -> rerank |

---

## 6. Data Model

### Document Tree Node

Create the Phase 1 Pydantic model in
`services/intelligence/rag/tree_models.py`. Extract a shared contract only when
a second production writer needs it; do not add an unused NLM-side duplicate.

```python
class DocumentTreeNode(BaseModel):
    doc_id: str
    document_version: str
    node_id: str
    parent_id: str | None
    depth: int
    ordinal: int
    ordinal_path: str
    heading: str
    summary: str
    start_char: int
    end_char: int
    child_ids: list[str]
    chunk_ids: list[str]
```

### Qdrant Payload Extensions

Every tree-aware chunk receives these payload fields:

```json
{
  "doc_id": "report:2026-04-03:iran-report",
  "document_version": "sha256:...",
  "chunk_id": "report:2026-04-03:iran-report:chunk:0007",
  "node_id": "report:2026-04-03:iran-report:node:02.03",
  "parent_node_id": "report:2026-04-03:iran-report:node:02",
  "tree_path": ["Report", "Military Activity", "Air Defense"],
  "tree_depth": 2,
  "heading": "Air Defense",
  "section_summary": "Discussion of Iranian air-defense posture and recent interceptions.",
  "content": "chunk text used for answer generation",
  "source": "manual_report",
  "url": "optional source url",
  "published_at": "2026-04-03T00:00:00+00:00"
}
```

Payload rules:

- Existing payload fields stay intact.
- `doc_id`, `chunk_id`, and `node_id` are required for tree-aware chunks.
- `document_version` is the hash of normalized full-document content.
- `tree_path` must be ordered root-to-node.
- `content` must contain the exact chunk text used for embedding.
- `section_summary` must be deterministic in Phase 1. LLM summaries are allowed only if stored with `summary_model` and `summary_prompt_version`.

### Neo4j Representation

Phase 1 avoids graph writes by keeping tree metadata in Qdrant payloads. Phase 2 should add deterministic Cypher writes only after the retriever has passed evaluation:

```cypher
(:Document {doc_id})
(:DocumentSection {node_id, heading, depth, ordinal, summary})
(:DocumentChunk {chunk_id})

(:Document)-[:HAS_SECTION]->(:DocumentSection)
(:DocumentSection)-[:HAS_CHILD]->(:DocumentSection)
(:DocumentSection)-[:HAS_CHUNK]->(:DocumentChunk)
(:DocumentChunk)-[:MENTIONS]->(:Entity)
```

All writes must use static Cypher templates and parameter binding.

---

## 7. Ingestion Design

### Tree Construction

Add a deterministic tree builder:

```text
raw document
  -> normalize whitespace
  -> detect headings
  -> build section nodes
  -> chunk section bodies
  -> assign chunk IDs
  -> embed chunks
  -> write Qdrant points with tree payload
```

Heading detection order:

1. Markdown headings: `#`, `##`, `###`.
2. Numbered headings: `1.`, `1.2`, `1.2.3`.
3. Transcript time blocks for NotebookLM: group by speaker/time windows if no headings exist.
4. Fallback: fixed-size synthetic sections every 2,000 to 3,000 characters.

### Stable IDs

IDs must be deterministic:

```text
doc_id = source + ":" + sha256(canonical_source_url_or_notebook_id)[:16]
node_id = doc_id + ":node:" + dotted_ordinal
chunk_id = doc_id + ":chunk:" + zero_padded_chunk_ordinal
point_id = uuid5(ODIN_TREE_NAMESPACE, chunk_id)
document_version = sha256(normalized_full_document)
```

Re-ingesting the same document and content must be idempotent. If content or
structure changes, the writer computes the complete expected point-ID set,
deletes obsolete points for that `doc_id`, and then upserts the new set. Without
this replace-set step, shortened documents leave stale chunks searchable.

### Initial Integration Point

Start with `services/intelligence/rag/indexer.py` and manual longform ingestion.
Do not route `nlm_ingest/ingest_qdrant.py` through the tree builder: that module
indexes extracted claims, not transcript chunks. A later NotebookLM longform
writer may share the builder while retaining the claim index.

Rationale:

- It limits blast radius.
- It avoids rewriting live RSS/GDELT/Hugin collectors before the retrieval quality is proven.
- It creates clean fixtures for tests.

---

## 8. Retrieval Design

### New Module

Create `services/intelligence/rag/tree_retriever.py`.

Public API:

```python
async def tree_search(
    query: str,
    *,
    limit: int = 5,
    source: str | None = None,
    doc_id: str | None = None,
    max_candidate_chunks: int = 30,
    max_candidate_nodes: int = 8,
    enable_llm_node_select: bool = True,
    enable_rerank: bool = True,
    enable_graph_context: bool = True,
    graph_client=None,
) -> list[dict]:
    ...
```

### Algorithm

1. **Candidate chunk retrieval**
   - Call existing `search()` with overfetch `max_candidate_chunks`.
   - In future hybrid mode, call the hybrid retriever instead.

2. **Node score aggregation**
   - Group chunks by `node_id`.
   - Score each node from:
     - max chunk score,
     - average top-3 chunk score,
     - number of matching chunks,
     - section depth penalty for overly broad root nodes.

3. **LLM node selection**
   - Build a compact candidate list:
     `node_id`, `tree_path`, `heading`, `section_summary`, top chunk snippets.
   - Ask the local vLLM to select node IDs relevant to the query.
   - Output must be strict JSON:

```json
{
  "selected_node_ids": ["doc:node:02.03"],
  "rejected_node_ids": ["doc:node:01"],
  "rationale": "short explanation"
}
```

4. **Evidence expansion**
   - Fetch all candidate chunks under selected nodes, capped by budget.
   - Preserve `tree_path`, `heading`, `chunk_id`, and URL/source metadata.

5. **Rerank**
   - Use existing TEI reranker on evidence chunks.
   - Return top `limit`.

6. **Graph context**
   - Reuse existing graph context injection by extracted entities.
   - Do not generate write Cypher.

### Failure Behavior

Tree search must degrade cleanly:

- If candidates have no `node_id`, call an internal dense/rerank pipeline with
  tree dispatch explicitly disabled. Never call tree-dispatching
  `enhanced_search()` recursively.
- If the LLM selection call times out, use top aggregated nodes.
- If rerank fails, preserve node-score order.
- If Neo4j is unavailable, return evidence without graph context.
- If Qdrant schema validation fails, fail closed using existing `QdrantSchemaMismatch`.

---

## 9. Feature Flags and Configuration

Add to `services/intelligence/config.py`:

```python
enable_tree_search: bool = False
tree_search_llm_timeout_s: int = 20
tree_search_max_candidate_chunks: int = 30
tree_search_max_candidate_nodes: int = 8
tree_search_max_evidence_chunks: int = 12
```

Add matching environment variables:

```env
ENABLE_TREE_SEARCH=false
TREE_SEARCH_LLM_TIMEOUT_S=20
TREE_SEARCH_MAX_CANDIDATE_CHUNKS=30
TREE_SEARCH_MAX_CANDIDATE_NODES=8
TREE_SEARCH_MAX_EVIDENCE_CHUNKS=12
```

The default remains off until tests and a small evaluation set pass.
The selector timeout must also fit inside the ReAct tool and total-request
budgets; implementation planning must reconcile these values instead of adding
an independent latency ceiling.

---

## 10. API and Agent Integration

### Internal Retriever

Extract the existing dense -> rerank -> graph flow into a non-dispatching
internal primitive, then extend `enhanced_search()` with an optional flag:

```python
enable_tree_search: bool | None = None
```

If `enable_tree_search` is true:

- Call `tree_search()`.
- If it returns no results, call the non-dispatching dense primitive.
- Forward `query_filter`, `post_rerank`, score threshold, and lane limits so the
  current corpus policy cannot be bypassed.

### ReAct Tool

Do not add a new tool in Phase 1. Extend `EvidenceItem` and the `[EVIDENCE]`
codec with optional section fields, then let `qdrant_search` render them. The
analysis/realtime merge order, provenance parsing, deduplication, and output
budget remain unchanged.

Output format example:

```text
[EVIDENCE] {"credibility_score":0.8,"heading":"Air Defense","provider":"report:iran","provenance_inferred":false,"published_at":null,"relevance_score":0.83,"source_ref_id":"abc123","source_type":"dataset","tree_path":["Strategic Overview","Air Defense"],"url":null}
Title: Iran Report
Section: Military Activity > Air Defense
Excerpt: ...
```

After Phase 1, consider a separate `document_tree_search` tool only if agent traces show the model needs explicit tool selection.

---

## 11. Prompt Contract

The LLM node selector must be conservative. It selects sections, not answers the question.

System prompt requirements:

- Return JSON only.
- Select up to `max_selected_nodes`.
- Prefer specific child sections over broad parents.
- Reject nodes whose snippets do not contain direct evidence.
- Do not infer facts outside provided snippets.
- If no node is relevant, return an empty list.

The implementation must parse JSON strictly. Invalid JSON triggers fallback to score-based node order.

---

## 12. Observability

Log these structured events:

- `tree_ingest_started`
- `tree_ingest_completed`
- `tree_node_built`
- `tree_search_started`
- `tree_candidates_retrieved`
- `tree_nodes_aggregated`
- `tree_llm_selection_completed`
- `tree_llm_selection_failed`
- `tree_search_fallback_dense`
- `tree_search_completed`

Metrics to expose later:

- candidate chunk count,
- candidate node count,
- selected node count,
- LLM selection latency,
- fallback rate,
- average result depth,
- answer citation coverage.

---

## 13. Testing Strategy

### Unit Tests

Add tests under `services/intelligence/tests/`:

- `test_tree_models.py`
  - validates required fields and deterministic paths.

- `test_tree_builder.py`
  - markdown headings produce expected hierarchy.
  - numbered headings produce expected hierarchy.
  - no headings produces synthetic sections.
  - stable IDs are unchanged across re-runs.
  - changed/shortened documents remove obsolete Qdrant points.
  - deterministic point IDs prevent duplicate chunks on re-ingest.

- `test_tree_retriever.py`
  - groups chunks by `node_id`.
  - aggregates scores correctly.
  - prefers specific nodes over root nodes.
  - falls back when no tree metadata exists.
  - falls back when LLM selector returns invalid JSON.

- `test_qdrant_search_tool.py`
  - renders tree-path citations when present.
  - preserves current output for old payloads.
  - preserves analysis/realtime lane filters and evidence ordering.
  - section metadata round-trips through `[EVIDENCE]` parsing.

### Integration Tests

Add one small fixture document:

```text
# Strategic Overview
General background.

## Air Defense
Specific evidence about radar and interceptor deployments.

## Maritime Activity
Specific evidence about vessel movements.
```

Test query:

```text
What evidence exists about Iranian air defense readiness?
```

Expected:

- selected path includes `Strategic Overview > Air Defense`;
- maritime section is not selected;
- returned result contains `tree_path`, `node_id`, and evidence text.

### Evaluation Set

Create a small manual eval file later:

```text
services/intelligence/tests/fixtures/tree_search_eval.yaml
```

Minimum eval before enabling by default:

- 20 longform queries.
- At least 80% section-hit accuracy.
- No worse than current dense retrieval on top-5 answerable evidence.

---

## 14. Rollout Plan

### Stage 0: Spec Approval

Review this design and confirm Phase 1 scope.

### Stage 1: Models and Builder

Implement tree models and deterministic tree builder with tests.

### Stage 2: Longform Indexing

Extend manual report indexing to attach tree payload fields and replace stale
points deterministically. NotebookLM remains out of this stage.

### Stage 3: Retriever

Add `tree_retriever.py`, feature flag, fallback behavior, and tests.

### Stage 4: Agent Output

Render tree-path citations in `qdrant_search`.

### Stage 5: Evaluation and Opt-In

Run eval fixtures. Enable `ENABLE_TREE_SEARCH=true` only for the intelligence service in development.

### Stage 6: Broader Corpus

After Qdrant v2 hybrid migration, expand to long RSS/GDELT documents and add optional Neo4j `DocumentSection` writes.

---

## 15. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Extra LLM call increases latency | Default off, timeout 20s, fallback to score aggregation |
| LLM selects wrong sections | Strict JSON, candidate snippets only, eval set, fallback ranking |
| Payload drift between ingestion paths | Shared Pydantic model and tests for required fields |
| Confusion with Qdrant hybrid migration | Independent `enable_tree_search` flag |
| Historic corpus lacks tree fields | Fallback to current dense search |
| Neo4j write risk | Phase 1 avoids graph writes; Phase 2 uses deterministic Cypher only |

---

## 16. Acceptance Criteria

Phase 1 is complete when:

1. Longform documents can be indexed with deterministic tree metadata.
2. Tree-aware chunks in Qdrant include `doc_id`, `chunk_id`, `node_id`, `tree_path`, `heading`, and `content`.
3. Re-ingestion uses deterministic point IDs and removes stale chunks for the
   same `doc_id`.
4. `tree_search()` returns section-aware evidence for tree-enabled documents.
5. Old dense-only documents still work unchanged.
6. `qdrant_search` preserves corpus lanes and includes structured section
   citations when tree fields are present.
7. Unit tests cover builder, aggregation, LLM fallback, replacement semantics,
   evidence encoding, and output formatting.
8. `uv run pytest` passes in `services/intelligence`.
9. The feature remains disabled by default.

---

## 17. Open Decisions for Implementation Plan

These are implementation-planning decisions, not design blockers:

1. Whether tree sidecar metadata lives only in Qdrant payloads in Phase 1 or also in a local JSONL file.
2. Whether the first ingestion target is `rag/indexer.py` only or a new
   intelligence-owned report import command around it.
3. Whether section summaries are deterministic extractive snippets or generated by vLLM with versioned prompt metadata.

Recommended defaults:

- Store tree metadata in Qdrant payload only for Phase 1.
- Start with `rag/indexer.py` and one committed manual-report fixture.
- Use deterministic extractive summaries until retrieval behavior is stable.
