# Qdrant v2 Hybrid Migration Design Spec

**Date:** 2026-05-03  
**Status:** Decision-ready — implementation requires a follow-up plan  
**Scope:** Phase 2 sparse-vector generation, named dense+sparse schema, RRF retriever, backfill, dual-write, validation, cutover sequence, and rollback windows

**Cross-reference:** [Qdrant Collection Source-of-Truth Sync - Design Spec](./2026-04-30-qdrant-collection-sot-design.md) — Phase 1 established `odin_intel` as current runtime and documented the Phase 2 target state in §6.

---

## 1. Motivation

The Qdrant Collection SoT Phase 1 audit (2026-04-30) established that `odin_intel` is the current production collection with dense vectors only (1024-dim cosine). Phase 1 locked runtime defaults and defenses in place. Phase 2 upgrades to **hybrid retrieval** — dense vectors plus sparse/BM25 vectors — to improve recall and retrieval quality for OSINT queries.

The Phase 1 design spec (§6) outlined the target schema and cutover phases. This document elaborates the Phase 2 migration as a separate design, capturing decisions on tokenizer choice, backfill strategy, dual-write ordering, validation gates, and rollback windows. The implementation-level task breakdown is deferred to a follow-up plan after this spec is approved.

**Why hybrid retrieval?**
- Dense retrieval (current) captures semantic similarity but misses exact entity/keyword matches.
- Sparse/BM25 retrieval excels at exact term matching, especially for geopolitical entities, vessel names, and supply-chain references.
- Hybrid scoring via Reciprocal Rank Fusion (RRF) combines both signals, improving recall@k for intelligence queries.
- Live OSINT feeds (RSS, GDELT, AIS) are term-heavy; hybrid is a natural fit.

---

## 2. Decision: `enable_hybrid` as Architectural Discriminator

**Non-negotiable rule:** Code paths for Phase 1 (dense-only) vs Phase 2 (hybrid) are selected by the explicit `enable_hybrid` boolean flag, NOT by collection name alone.

This is a hard architectural boundary:

- `enable_hybrid=False` (Phase 1 default):
  - Reads/writes to `odin_intel` (or configured collection).
  - Expects unnamed dense vector `size=1024, distance=Cosine`.
  - Refuses to serve named vectors or sparse vectors.
  - Startup schema check fails if sparse config is present in the configured collection.

- `enable_hybrid=True` (Phase 2):
  - Reads/writes to `odin_v2` (or configured collection).
  - Expects named dense vector `"dense"` and named sparse vector `"bm25"`.
  - Requires sparse vector payload generation (via client or server-side tokenizer).
  - Startup schema check fails if dense or sparse config is missing.

**Consequence:** Rollback is explicit:
- Disable `enable_hybrid`, point all services back to `odin_intel`.
- Silent default flips via collection-name-only logic are forbidden.

This rule is enforced in:
- Service startup/preflight schema checks.
- Qdrant writer branching logic (unnamed vectors vs named vectors).
- Retriever query builder (dense search vs hybrid RRF search).
- Test suites (separate test fixtures for Phase 1 and Phase 2 modes).

---

## 3. Sparse-Vector Generation Strategy

### Tokenizer Choice

Two candidate tokenizers exist for sparse-vector generation:

#### Option A: Qdrant Native BM25 (Recommended)

**How it works:**
- Qdrant 1.13+ exposes a `Modifier.IDF` sparse-vector modifier.
- Client submits plain text in the payload; Qdrant tokenizes and computes IDF weights at write time.
- Query side: client submits plain query text; Qdrant tokenizes and ranks via BM25.
- No client-side tokenizer dependency.

**Pros:**
- Single source of truth: Qdrant owns tokenization, no drift between client and server.
- Simpler ingestion pipeline (no pre-compute step).
- Qdrant's BM25 tuning (k1, b parameters) is centralized.
- Scales naturally with new data (IDF updates automatically).

**Cons:**
- Requires text payload field (must be included with every point).
- IDF computation happens at write time (slight ingestion latency bump).
- Qdrant version dependency (1.13+ with native BM25 support).

#### Option B: Client-Side Tokenizer (NLTK / SpaCy)

**How it works:**
- Data-ingestion pre-tokenizes text offline (NLTK, SpaCy, or HuggingFace tokenizer).
- Generates sparse vector (token ID → TF-IDF weight) as part of the ingestion payload.
- Qdrant stores pre-computed sparse vectors; no server-side tokenization.
- Query side: client tokenizes the query text the same way, submits sparse tokens to Qdrant.

**Pros:**
- Flexible tokenization (can use domain-specific or multilingual tokenizers).
- No Qdrant version dependency; compatible with older Qdrant servers.
- Tokenization is predictable and testable offline.

**Cons:**
- Client tokenizer must match between ingestion and query (drift risk).
- Pre-compute step adds complexity to data-ingestion pipeline.
- Offline tokenizer adds dependency (NLTK, SpaCy).
- Query-side tokenizer must be deployed separately.

### **Recommended Choice: Option A (Qdrant Native BM25)**

**Rationale:**
- Odin already requires Qdrant 1.13+ for other features.
- The corpus is multilingual (English + geopolitical entities); Qdrant's BM25 is standard and reliable.
- Single source of truth (no client/server tokenization drift).
- Simpler data-ingestion pipeline (no pre-compute).
- Lower operational complexity.

**Decision:**
- Write strategy: client sends plain text in a dedicated payload field (e.g., `"text_for_bm25"`); Qdrant indexes and computes sparse vectors via `Modifier.IDF`.
- Query strategy: client submits query text to Qdrant's native BM25 query API.
- Tokenizer parameter: documented in Qdrant config and config tests, not hidden.

**If Option A becomes blocked** (Qdrant version incompatibility, licensing issues):
- Fall back to Option B with NLTK's `word_tokenize` and a TF-IDF matrix stored as a sparse vector.
- This requires a follow-up design doc; do not mix strategies mid-migration.

---

## 4. Schema Design

### Target `odin_v2` Collection Schema

```python
# Schema definition (Qdrant Python API)

vectors_config = {
    "dense": VectorParams(
        size=1024,
        distance=Distance.COSINE,
        on_disk=False,
    ),
}

sparse_vectors_config = {
    "bm25": SparseVectorParams(
        modifier=Modifier.IDF,
    ),
}

# Payload schema (Pydantic for ingestion, schema doc for validation)
class Odin_V2_Point(BaseModel):
    id: int
    vector: List[float]  # dense vector (1024 dim)
    sparse_vectors: Dict[str, SparseVector]  # sparse BM25 vectors (client-generated or server-side)
    payload: Dict[str, Any] = {
        "text_for_bm25": str,  # Required: plain text for BM25 indexing
        "source": str,
        "event_type": str,
        "entity_ids": List[str],
        "temporal": {"timestamp": float, "day_of_week": int},
        "geospatial": {"location": [float, float], "region": str},
        "metadata": {
            "confidence": float,
            "feed": str,
            "url": Optional[str],
        },
    }
```

### Compatibility with Phase 1 Payloads

- `odin_intel` payloads are **fully preserved** in `odin_v2`.
- `odin_v2` adds a `text_for_bm25` field (concatenation of event description, entities, and source).
- **No payload fields are dropped** during backfill; existing payloads are extended.
- Retriever query side always returns the full payload (both dense and sparse match metadata).

---

## 5. Backfill Strategy

### Data Source

- **Snapshot source:** A consistent snapshot of `odin_intel` taken at the start of the backfill window.
- **Point selection:** All points with `timestamp >= cutover_start_minus_1_week` (include recent history for validation).
- **Payload validation:** Ensure every point has required fields (`text_for_bm25`, `source`, `event_type`).

### Backfill Process

1. **Export Phase:**
   - Query `odin_intel` for all active points (count and sample).
   - Export payloads as JSONL (one point per line).
   - Compute MD5 checksums for point count and payload hash (for parity validation).

2. **Enrich Phase:**
   - For each exported point, compute sparse vectors via Qdrant BM25 (or pre-compute if client-side).
   - Optionally regenerate or validate dense vectors (depends on whether embeddings have drifted).
   - **Default:** reuse existing dense vectors; regenerate only if embedding model changed.

3. **Write Phase:**
   - Create `odin_v2` collection with named dense+sparse schema (if not already present).
   - Batch insert all points into `odin_v2` with both dense and sparse vectors.
   - Log progress: every N points, log count and estimated time.
   - On error: log point ID, error message, and continue (or fail-fast based on error severity).

4. **Validation Phase:**
   - Assert point count in `odin_v2` == point count in snapshot (within +/- 1).
   - Assert source distribution is unchanged (sample 1000 random points and check source field).
   - Assert payload field presence: 100% of `odin_v2` points have `text_for_bm25`.
   - Compare dense vectors (MD5 hash of vector bytes) with originals; allow for floating-point drift <= 1e-6 per dimension.

### Rollback Windows

- **During Export:** No writes have happened yet. Safe to abort.
- **During Enrich:** Abort and discard. No changes to `odin_intel` or `odin_v2`.
- **During Write:** If insertion fails, log the error and **do not retry automatically**. Operator must inspect and manually decide whether to drop `odin_v2` and restart.
- **After Validation:** Point count and payload parity are the gates. If validation fails, do not proceed to dual-write. Keep `odin_intel` active as fallback.

---

## 6. Dual-Write Transition

### Order of Operations (Critical)

**Prerequisite:** Backfill is complete, `odin_v2` point count and payloads are validated.

1. **Enable dual-write in data-ingestion:**
   - Modify the feed collectors (RSS, GDELT, AIS, Hotspots) and ingestion pipeline to write BOTH `odin_intel` and `odin_v2`.
   - **New points:** insert to both collections with appropriate vector schema (unnamed for `odin_intel`, named for `odin_v2`).
   - **Errors:** log write errors per collection; do not fail the entire ingest if one collection has a transient failure (graceful degradation).
   - **Order:** write to `odin_intel` first (authoritative), then `odin_v2` (follower). If `odin_v2` write fails after `odin_intel` succeeds, log and alert but continue.

2. **Monitor dual-write window:**
   - Agreed window: e.g., 7 days or until point count in `odin_v2` reaches X and source distribution is stable.
   - Metrics:
     - Point count growth (should match between collections).
     - Write error rates per collection.
     - Qdrant API latency per collection.
     - Payload field presence (100% of new points have `text_for_bm25`).

3. **Readers remain on `odin_intel`:**
   - Backend `/intelligence` endpoints, graph-RAG retriever, vision-enrichment queries all read from `odin_intel`.
   - No reader switches until validation is complete (step 8 below).

4. **Validation gates:**
   - Point count in `odin_v2` == point count in `odin_intel` (within +/- 0.1%, accounting for deletions).
   - Source distribution matches (KL divergence < 0.01).
   - Sample 100 random recent points from both; compare payloads (all expected fields present).
   - Dual-write error rate < 0.1% (alerting threshold: > 0.5%).

---

## 7. Retriever Changes (RRF Query Fusion)

### Transport: SDK Adoption

Phase 2 introduces the `qdrant_client` Python SDK on the read path. The current retriever (`services/intelligence/rag/retriever.py`) uses raw httpx POST to `/points/search`, which works for unnamed dense vectors but does not idiomatically support named-vector queries, prefetch, or RRF fusion. Phase 2 migrates to `qdrant_client.AsyncQdrantClient` for read paths. Pseudocode below assumes the SDK; the writer path (already using `qdrant_client` per `services/data-ingestion/feeds/base.py`) requires no transport change.

### Current State (Phase 1)

`services/intelligence/rag/retriever.py` — functions `search` and `enhanced_search`:
- `search()` — executes dense vector search on `odin_intel` via raw httpx POST to `/points/search`.
- `enhanced_search()` — dispatches based on `enable_hybrid` flag; gracefully falls back to dense-only when hybrid is unavailable (Phase 2 raises `NotImplementedError` internally and logs a warning).

### Target State (Phase 2)

1. **Dense search (unchanged):**
   ```python
   def search_dense(query_text: str, top_k: int = 10) -> List[ScoredPoint]:
       """
       Query `odin_intel` or configured collection with dense vector only.
       Used when enable_hybrid=False.
       """
       embedding = embedding_model.encode(query_text)  # 1024-dim
       results = qdrant_client.search(
           collection_name=self.collection_name,
           query_vector=embedding,
           query_filter=...,  # existing filters (temporal, geospatial)
           limit=top_k,
       )
       return results
   ```

2. **Sparse search (new):**
   ```python
   def search_sparse(query_text: str, top_k: int = 10) -> List[ScoredPoint]:
       """
       Query `odin_v2` with BM25 sparse vectors.
       Used as one signal in hybrid fusion.
       """
       # Query tokenizer (must match ingestion tokenizer)
       # Option A: Qdrant native BM25
       results = qdrant_client.search(
           collection_name="odin_v2",
           query_vector=query_text,  # Qdrant parses and tokenizes
           vector_name="bm25",  # sparse vector name
           limit=top_k,
       )
       # Option B: client-side tokenization
       # tokens = nltk.word_tokenize(query_text)
       # sparse_vector = sparse_encoder.encode(tokens)
       # results = qdrant_client.search(..., query_vector=sparse_vector, ...)
       return results
   ```

3. **Hybrid RRF fusion (new):**
   ```python
   def search_hybrid(query_text: str, top_k: int = 10, rrf_k: int = 60) -> List[ScoredPoint]:
       """
       Query both dense and sparse, fuse results via Reciprocal Rank Fusion.
       Used when enable_hybrid=True and odin_v2 is available.
       
       RRF formula (for each result point):
           rrf_score = 1 / (rrf_k + rank_in_result_set)
           final_score = w_dense * rrf_score_dense + w_sparse * rrf_score_sparse
       
       Default: w_dense=0.5, w_sparse=0.5 (equal weights; tunable per deployment).
       """
       # Prefetch: retrieve top_k * prefetch_factor from each signal
       dense_results = self.search_dense(query_text, top_k=top_k * 2)
       sparse_results = self.search_sparse(query_text, top_k=top_k * 2)
       
       # Combine: deduplicate by point ID, fuse scores
       combined = {}
       for rank, result in enumerate(dense_results):
           if result.id not in combined:
               combined[result.id] = {}
           combined[result.id]["dense_rank"] = rank
       
       for rank, result in enumerate(sparse_results):
           if result.id not in combined:
               combined[result.id] = {}
           combined[result.id]["sparse_rank"] = rank
       
       # RRF score
       fused_scores = []
       for point_id, ranks in combined.items():
           dense_rrf = 1 / (rrf_k + ranks.get("dense_rank", len(dense_results)))
           sparse_rrf = 1 / (rrf_k + ranks.get("sparse_rank", len(sparse_results)))
           final_score = 0.5 * dense_rrf + 0.5 * sparse_rrf  # weights configurable, defaults shown
           fused_scores.append((point_id, final_score))
       
       # Return top_k by fused score
       fused_scores.sort(key=lambda x: x[1], reverse=True)
       final_results = [qdrant_client.retrieve(point_id) for point_id, _ in fused_scores[:top_k]]
       return final_results
   ```

4. **RRF Parameter Tuning:**
   - `rrf_k`: controls the balance between ranking positions. Default 60 (empirically good for Web search). Tunable at deployment time.
   - `w_dense`, `w_sparse`: fusion weights. Default 0.5 each (equal importance). Adjust based on query analysis (more entity-heavy → increase `w_sparse`).
   - Prefetch factor: retrieve 2x top_k from each signal to account for potential rank differences. Tunable.

5. **Dispatcher logic:**
   ```python
   def query(query_text: str, top_k: int = 10) -> List[ScoredPoint]:
       """Main entry point."""
       if not self.enable_hybrid:
           return self.search_dense(query_text, top_k)
       
       try:
           # Check schema: sparse vectors must exist
           collection_info = qdrant_client.get_collection(self.collection_name)
           if not collection_info.config.sparse_vectors_config:
               # Graceful fallback: hybrid disabled but collection is v1
               return self.search_dense(query_text, top_k)
           
           return self.search_hybrid(query_text, top_k)
       except Exception as e:
           # Fallback: if hybrid fails, serve dense results
           logger.warning(f"Hybrid search failed: {e}. Falling back to dense.")
           return self.search_dense(query_text, top_k)
   ```

### Reference to Existing Code

- Retriever module: `services/intelligence/rag/retriever.py` — see `search` (dense httpx path) and `enhanced_search` (graceful hybrid fallback with warning log).
- The graceful-fallback path is present and will be hardened into a real hybrid query in Phase 2 using `AsyncQdrantClient`.
- Config flag: `services/intelligence/config.py` already exposes `enable_hybrid: bool = False`.

---

## 8. Validation Gates

Before proceeding from dual-write (step 5) to atomic reader switch (step 6), all gates must pass:

### Point Count Validation

- **Assertion:** `odin_v2.point_count == odin_intel.point_count ± 1`
- **Rationale:** Accounts for points added/deleted during the check window.
- **Failure mode:** If counts diverge > 1%, investigate write error logs. Do not switch readers.

### Source Distribution Validation

- **Assertion:** For each source (RSS feed, GDELT, AIS, hotspots, etc.), the proportion of points in `odin_v2` matches `odin_intel` within ±2%.
- **Method:** Sample 1000 random points from each collection; compute source histogram; Kullback-Leibler divergence KL(P || Q) < 0.01.
- **Failure mode:** If distribution is skewed, identify which source is missing or overrepresented. Do not switch until root cause is fixed (e.g., a feed collector not dual-writing).

### Payload Parity Validation

- **Assertion:** 100% of points in `odin_v2` have required fields: `text_for_bm25`, `source`, `event_type`.
- **Method:** Sample 100 random recent points; inspect payload structure.
- **Failure mode:** If any field is missing, backfill or reject the point. Do not switch if payload is incomplete.

### Recall@k Validation (Accuracy)

- **Assertion:** Hybrid recall@10 >= dense recall@10 on a sample query set.
- **Sample set:** 200 human-labeled relevance judgments (queries + known-relevant documents), stratified across the 65+ event types in the codebook. A 50-query set yields ±13pp 95% CI on recall@10 — wider than the 10pp threshold; 200 queries tightens this to ±7pp and makes the gate decision-ready.
- **Metric:** recall@10 = (# relevant docs retrieved in top 10) / (# known relevant docs).
- **Threshold:** Hybrid recall@10 >= 90% of dense recall@10 (allow up to 10% regression for now; expect improvement with tuning).
- **Failure mode:** If recall@10 drops below threshold, tune RRF weights or prefetch factor. Do not switch until threshold is met.
- **Note:** This is a manual gate; no automated evaluation harness exists yet (see Non-Goals).

### Latency Validation (Performance)

- **Assertion:** Hybrid p50 latency <= 150ms, p95 latency <= 300ms (on-disk embeddings, no cache).
- **Method:** Execute 100 diverse queries; measure round-trip time from query submission to result return (excluding client deserialization).
- **Breakdown:** dense search, sparse search, RRF fusion.
- **Threshold:** Hybrid total latency should not exceed dense-only latency by more than 1.5x (acceptable tradeoff for improved quality).
- **Failure mode:** If latency exceeds budget, optimize sparse search (prefetch, filtering, network calls) or implement result caching. Do not switch until latency is acceptable.

---

## 9. Rollback Windows

Each cutover step has different reversibility:

| Step | Action | Reversible? | Notes |
|---|---|---|---|
| 1 | Data-ingestion dual-writes to `odin_intel` and `odin_v2` | Yes (stop dual-write) | If stopped, new points go to `odin_intel` only; `odin_v2` becomes stale. |
| 2 | Backfill `odin_v2` from `odin_intel` snapshot | Yes (drop `odin_v2`) | Loss of backfill effort, but `odin_intel` is untouched. |
| 3 | Validate point counts, source distribution, payloads | Yes (fail validation, retry tuning) | No permanent changes if validation fails. |
| 4 | **Atomically switch readers via `enable_hybrid=True`** | **Limited** | Reversible via `enable_hybrid=False` during Step 5 window; after Step 6 requires manual write replay and reconciliation. |
| 5 | Continue dual-write through validation | Yes (stop dual-write if needed) | Can revert to single-write to `odin_intel` if hybrid queries show issues. |
| 6 | Switch writes to `odin_v2` only | **Very limited** (restore dual-write) | Requires re-enabling writes to `odin_intel`; new points written to `odin_v2` are not backfilled to `odin_intel`. |
| 7 | Keep `odin_intel` read-only as emergency snapshot | Yes (restore writes to `odin_intel`) | `odin_intel` remains available for ad-hoc queries and rollback. |
| 8 | Drop `odin_intel` | **Not reversible** | Requires full backfill from `odin_v2` if recovery is needed. Only after explicit joint approval from engineering lead + operations lead. |

**Critical decision point:** Step 4 is the architectural commit point. Rollback by flipping `enable_hybrid=False` remains available throughout the Step 5 dual-write validation window. After Step 6 (writes-to-v2-only), rollback requires manual write replay from logs and is high-risk. Before flipping `enable_hybrid=True`, ensure all validation gates pass AND engineering lead approval is obtained.

---

## 10. Required Cutover Sequence

The 8-step cutover from Phase 1 (plan ref: `2026-04-30-qdrant-collection-sot.md` Task 4):

### Sequence Mapping

The Phase 1 design spec (`2026-04-30-qdrant-collection-sot-design.md` §6) uses "Phase 0..5" terminology. This spec uses "Step 0..8". The table below bridges the two numbering systems so readers holding both documents can navigate without confusion.

| Phase 1 Spec §6 Phase | This Spec Step | Label |
|---|---|---|
| Phase 0: Phase 1 hardening | (Phase 1 plan, complete) | Phase 1 contract enforcement |
| Phase 1: Build odin_v2 | Step 2 + Step 3 | Schema creation, backfill, and validation |
| Phase 2: Dual-write transition | Step 1 (dual-write enable) + Step 5 (dual-write validation window) | Dual-write transition |
| Phase 3: Atomic read switch | Step 4 | Reader cutover |
| Phase 4: v2-only writes | Step 6 | Writer cutover |
| Phase 5: Retirement | Step 7 + Step 8 | v1 read-only snapshot, then drop |

### Step 0: Preconditions (Before Starting)
- [x] Phase 1 plan is complete (documentation updated, schema checks in place, `enable_hybrid=False` enforced).
- [x] `enable_hybrid=True` code paths exist in all services (retriever, ingestion, vision).
- [x] Data-ingestion can switch collection names (via config, not env var).
- [x] Qdrant doctor command shows schema details for both collections.

Preconditions marked [x] are completed by Phase 1 plan tasks on this branch (`feature/qdrant-sot-phase1`).

### Step 1: Data-Ingestion Dual-Writes to `odin_intel` and `odin_v2`
- **Action:** Enable dual-write in feed collectors and ingestion pipeline.
- **Precondition:** `odin_v2` exists with named dense+sparse schema; backfill is complete; validation gates pass.
- **Behavior:** Every new point is written to BOTH collections with correct schema (unnamed vectors for `odin_intel`, named for `odin_v2`).
- **Error handling:** Log per-collection errors; do not fail ingestion if one collection has a transient failure.
- **Duration:** Agreed window, e.g., 7 days or until point count stability is confirmed.
- **Owner:** Data-ingestion team. Decision: engineering lead.

### Step 2: Backfill `odin_v2` from `odin_intel` Snapshot
- **Action:** Export all existing points from `odin_intel`; enrich with sparse vectors; write to `odin_v2`.
- **Precondition:** `odin_intel` is live and stable; `odin_v2` collection schema is ready.
- **Validation:** Point count, source distribution, payload parity, MD5 hash of dense vectors.
- **Rollback:** Drop `odin_v2` if validation fails; no changes to `odin_intel`.
- **Duration:** 1–2 hours (depends on corpus size and network).
- **Owner:** Data-ingestion team. Decision: engineering lead.

### Step 3: Validate Point Counts, Source Distribution, Payload Parity, Recall@k, and Latency
- **Action:** Run validation suite (automated + manual).
- **Automated gates:**
  - Point count: `odin_v2 == odin_intel ± 1`
  - Source distribution: KL divergence < 0.01
  - Payload presence: 100% of points have required fields
  - Latency: p50 <= 150ms, p95 <= 300ms
- **Manual gate:**
  - Recall@k: human review of 200-query stratified sample set; hybrid recall@10 >= 90% of dense recall@10
- **Decision:** Must pass all gates before proceeding to step 4. Engineering lead approves the recall@k and latency results at this boundary.
- **Owner:** QA + engineering. Decision: engineering lead.

### Step 4: Atomically Switch All Readers via Feature/Deployment Flag
- **Action:** Enable `enable_hybrid=True` in backend, intelligence, vision-enrichment services. Deploy simultaneously across all readers.
- **Precondition:** All validation gates from step 3 pass. Dual-write is healthy (< 0.1% error rate).
- **Behavior:** All queries now use hybrid RRF fusion; sparse search is live.
- **Monitoring:** Real-time alerts for query latency, error rates, result quality (sample queries).
- **Duration:** 1 deployment cycle (minutes to hours, depends on infrastructure).
- **Rollback trigger:** If query error rate > 1% or latency spike > 2x baseline, disable hybrid immediately by flipping `enable_hybrid=False`. Rollback is bounded by the duration of Step 5 (default: 7 days). After Step 6, rollback requires manual write replay from logs and is high-risk.
- **Owner:** DevOps executes the deployment / flag flip. Joint decision: engineering lead + operations lead.

### Step 5: Continue Dual-Write Through Validation Window
- **Action:** Keep data-ingestion writing to BOTH `odin_intel` and `odin_v2` while readers are on `odin_v2`.
- **Precondition:** Step 4 switch completed; queries are stable.
- **Duration:** Agreed window, e.g., 7 days post-switch or until point counts are within 0.1%.
- **Monitoring:** Write error rates, point count growth, source distribution stability.
- **Rationale:** Protects against hybrid query issues; if hybrid fails catastrophically, can revert readers to `odin_intel` while writes continue.
- **Owner:** Data-ingestion + backend team. Decision: engineering lead.

### Step 6: Switch Writes to `odin_v2` Only (Stop `odin_intel` Writes)
- **Action:** Disable writes to `odin_intel` in data-ingestion; enable writes to `odin_v2` only.
- **Precondition:** Step 5 validation window complete; no anomalies detected in hybrid queries.
- **Behavior:** New points go to `odin_v2` only; `odin_intel` becomes read-only snapshot.
- **Rollback:** Restore dual-write or single-write to `odin_intel` (manual operation); note that points written to `odin_v2` during this step are not automatically backfilled to `odin_intel`.
- **Duration:** 1 deployment cycle.
- **Owner:** Data-ingestion team executes. Joint decision: engineering lead + operations lead.

### Step 7: Keep `odin_intel` Read-Only as Emergency Snapshot
- **Action:** Prevent any writes to `odin_intel`; maintain as fallback for emergency queries.
- **Precondition:** Step 6 complete; writes are exclusively to `odin_v2`.
- **Monitoring:** Periodically compare point counts (should remain static).
- **Use case:** If `odin_v2` becomes corrupted or unavailable, operations lead can manually point readers back to `odin_intel` to restore service.
- **Duration:** Indefinite (until step 8).
- **Owner:** DevOps. Decision: operations lead.

### Step 8: Drop `odin_intel` Only After Full Validation Window and Explicit Approval
- **Action:** Delete `odin_intel` collection from Qdrant.
- **Precondition:**
  - Minimum 30 days post-switch (step 4) without major incidents.
  - Explicit approval from both engineering lead and operations lead (joint decision).
  - Backup/archive of `odin_intel` taken and stored off-cluster (if required by policy).
- **Behavior:** `odin_v2` becomes the sole production collection; no rollback possible without re-ingestion.
- **Duration:** 1 admin operation (seconds).
- **Owner:** DevOps executes. Joint decision: engineering lead + operations lead.

---

## 11. Non-Goals

This spec intentionally does NOT cover:

- **New feed sources** — Qdrant v2 is not the trigger for adding RSS feeds, GDELT queries, or external data sources. Feed expansion is a separate initiative.
- **Retriever caching** — Hybrid migration does not include query result caching or memoization. Caching is deferred to a follow-up performance optimization plan.
- **Evaluation harness automation** — Recall@k validation in step 3 is manual (human-labeled judgments). Automated test set generation is not in scope.
- **Vector model upgrades** — Dense embedding model remains Qwen3-Embedding-0.6B throughout Phase 2. Model updates are a separate initiative.
- **Sparse model innovation** — This spec uses Qdrant's native BM25. Custom sparse embedding models (ColBERT, SPLADE) are deferred to Phase 3.
- **Neo4j graph integration** — Hybrid retrieval is Qdrant-only. Graph-RAG enhancements (entity linking, graph traversal) are separate.
- **Frontend UI changes** — No changes to the Worldview UI to reflect hybrid retrieval. UI display remains the same.

---

## 12. Risks and Mitigation

### Risk 1: Split-Brain Retrieval (Readers on `odin_v2`, Writes on `odin_intel`)

**Scenario:** Step 4 (reader switch) happens before dual-write is healthy, or dual-write is disabled prematurely.

**Consequence:** Readers query `odin_v2`, but writers update `odin_intel`. New OSINT data is invisible to hybrid queries; users see stale results.

**Mitigation:**
- Enforce hard dependency: readers must NOT switch to `odin_v2` while data-ingestion writes only to `odin_intel`.
- Automated check in step 3 validation: verify dual-write is active and healthy before proceeding to step 4.
- Dual-write must remain active through step 5; only disable after validation window (step 6).

---

### Risk 2: Sparse Tokenizer Mismatch (Client vs Server)

**Scenario:** Query tokenizer (client-side, Option B) diverges from ingestion tokenizer. A query token ID is missing from the ingestion dictionary.

**Consequence:** Sparse queries return empty or irrelevant results.

**Mitigation:**
- Use Qdrant native BM25 (Option A, recommended) to eliminate client/server drift.
- If Option B is chosen, enforce tokenizer versioning: every point includes metadata `tokenizer_version: str`. Query side checks that query tokenizer version matches point tokenizer.
- Test suite: verify that tokenizer(query_text) produces consistent tokens across all ingestion and query code paths.

---

### Risk 3: Dense Vector Drift During Backfill

**Scenario:** Embedding model is updated between the snapshot of `odin_intel` and the backfill into `odin_v2`. Backfilled dense vectors do not match queries encoded with the new model.

**Consequence:** Hybrid retrieval quality degrades because dense signal is out-of-distribution.

**Mitigation:**
- Freeze embedding model version during Phase 2 migration (step 0–8). No model updates until Phase 2 is complete.
- Backfill validation includes MD5 hash check of dense vectors vs original.
- If embedding model must be updated mid-migration, regenerate ALL dense vectors in `odin_v2` before switching readers (step 4).

---

### Risk 4: RRF Weight Imbalance

**Scenario:** Default RRF weights (0.5 dense, 0.5 sparse) are not optimal for OSINT queries. Sparse signal dominates (or vice versa), and recall@k regression occurs.

**Consequence:** Hybrid retrieval is worse than dense-only on certain query types (e.g., low-frequency entities).

**Mitigation:**
- Validation step 3 includes manual human evaluation on a diverse query set.
- Allow tuning of `w_dense` and `w_sparse` at deployment time (not hard-coded).
- If recall@k regression is detected, do NOT proceed to step 4. Tune weights and re-validate.
- Post-launch monitoring: track query performance by query type (entity-heavy vs semantic-heavy); adjust weights if needed.

---

### Risk 5: Qdrant Native BM25 Unavailable or Broken

**Scenario:** Qdrant version deployed does not support `Modifier.IDF` BM25, or the feature has a critical bug.

**Consequence:** Sparse vectors cannot be generated; Phase 2 is blocked.

**Mitigation:**
- Pre-migration check (step 0): verify Qdrant version >= 1.13 and test native BM25 on a small collection.
- If BM25 is unavailable, fall back to Option B (client-side NLTK tokenizer) and re-plan Phase 2 with that approach.
- Maintain documentation of Qdrant version requirements and known limitations.

---

### Risk 6: Dual-Write Latency Spike

**Scenario:** Writing to two collections simultaneously doubles ingestion latency or causes timeouts.

**Consequence:** Feed collectors fall behind; new OSINT data is delayed.

**Mitigation:**
- Implement async dual-write: submit write to `odin_intel` (blocking), then fire-and-forget write to `odin_v2` (async with retry logic).
- Set async write timeout: if `odin_v2` write does not complete within T seconds, log and continue (do not block ingestion).
- Monitor ingestion latency and throughput during step 1. If latency > baseline * 1.5, optimize or scale horizontally.

---

### Risk 7: Approval Bottleneck at Joint Decision Points

**Scenario:** Engineering lead or operations lead is unavailable at a critical cutover step (step 4 reader switch, step 6 writer cutover, or step 8 retirement). Migration is blocked.

**Consequence:** Schedule slips; team morale impact.

**Mitigation:**
- Pre-migration planning: identify named backups for both engineering lead and operations lead before the cutover window opens.
- Use feature flags (not manual config) for steps that require atomic decisions (steps 4, 6, 8). Allow automated rollback if latency/error thresholds are breached.
- Document approval criteria in this spec so that any authorized named backup can make an informed decision.
- Decision model summary: engineering lead approves validation gate results (Step 3 → Step 4 boundary); DevOps executes deployments; engineering lead + operations lead give joint approval at Step 4 commit, Step 6 writer cutover, and Step 8 retirement.

---

## Appendix: Related Documents

- **Phase 1 Plan:** `docs/superpowers/plans/2026-04-30-qdrant-collection-sot.md`
- **Phase 1 Spec:** `docs/superpowers/specs/2026-04-30-qdrant-collection-sot-design.md` (§6 Phase 2 Target Contract, §5 Hybrid Activation Flag)
- **Config Defaults:** `services/backend/app/config.py`, `services/intelligence/config.py`, `services/data-ingestion/config.py`
- **Retriever Implementation:** `services/intelligence/rag/retriever.py` — see `search` (dense httpx path) and `enhanced_search` (graceful hybrid fallback)
- **Qdrant Native BM25 Docs:** https://qdrant.tech/documentation/concepts/sparse-vectors/ (check latest)
