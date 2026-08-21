# TASK-104 Phase 2 — Qdrant BM25 Hybrid Search Implementation Plan

- **Date:** 2026-08-10
- **Status:** Review-ready, implementation not started
- **Scope:** Qdrant 1.13.2, `qdrant-client` 1.13.3, native sparse indexing/IDF and
  native RRF fusion; client-side FastEmbed BM25 generation
- **Source:** `odin_intel` (production, dense-only)
- **Target:** `odin_v2` (new collection, named `dense` plus optional named `bm25`)
- **Supersedes where conflicting:**
  `docs/superpowers/specs/2026-05-03-qdrant-v2-hybrid-migration-design.md`
- **Spatial dependency:**
  `docs/superpowers/HANDOFF-spatial-scope-plan07b-2026-08-10.md` and D11
- **Constraint:** This document is a plan only. Writing it must not create, update,
  snapshot, alias, or delete a Qdrant collection.

---

## 1. Outcome and safety decision

Implement the feature, but only as a blue/green collection migration. Never add or
rewrite vectors in `odin_intel` in place. `odin_intel` remains authoritative while
`odin_v2` is built, verified, shadowed, and initially served. After read cutover,
both collections continue receiving writes through a reversible state machine.

This makes the expected database risk **low and bounded**, not zero:

- The implementation never changes the vector schema of `odin_intel`.
- Existing dense vectors are copied, not regenerated.
- `odin_v2` can be abandoned without changing the active read path.
- A downloaded and successfully restored snapshot is mandatory before the first
  production migration mutation.
- Every dual-write is awaited. Partial success is durably recorded and repaired.
- No command in this phase deletes `odin_intel`; retirement is a separate task.

The primary benefit is better candidate recall for exact identifiers, names,
acronyms, titles, model numbers, vessel names, and quoted phrases while preserving
semantic recall through the existing dense embedding lane. Qdrant performs both
retrievals in one Query API request and fuses their ranks with RRF; the existing TEI
reranker remains the final relevance stage.

The implementation proceeds only if the frozen evaluation proves that exact-match
quality improves without material semantic, latency, corpus-policy, or resource
regression. If that gate fails, `odin_v2` stays non-serving and `odin_intel` remains
unchanged.

---

## 2. Scope

### In scope

- Exact Phase 2 collection and encoder contracts.
- Client-side FastEmbed document and query sparse-vector generation.
- Qdrant-side sparse storage, IDF modification, exact sparse search, and RRF fusion.
- A deep write Module that converts the same canonical dense point into the Phase 1
  and Phase 2 representations.
- Coverage of every active Qdrant point writer and payload mutation writer.
- Durable dual-write mutation/repair tracking.
- Snapshot, restore drill, pilot, backfill, convergence, validation, shadowing,
  cutover, and rollback.
- Evaluation at the Qdrant candidate stage and after the existing reranker/tier
  policy.
- Operator runbook, doctor checks, metrics, and final task-registry updates.

### Explicit non-goals

- No Qdrant server upgrade. The server stays at `qdrant/qdrant:v1.13.2`.
- No embedding-model change and no dense re-embedding.
- No weighted RRF, custom RRF `k`, formula query, or score boosting. Those require a
  newer Qdrant and a separate upgrade decision.
- No server-side inference request using `models.Document`; self-hosted 1.13.2 has no
  inference service configured.
- No BM25 vectors for structured/sensor points that the RAG corpus policy excludes.
- No change to corpus allowlists, source credibility, tier boosting, graph context,
  or the TEI reranker.
- No implementation or operational authorization of Spatial Plan 07B, payload-index
  rollout, or re-enrichment; D11 consumes their separately reviewed evidence.
- No activation of the dead GDELT DOC API collector.
- No implementation of the placeholder backend manual-ingest endpoint.
- No collection deletion. In particular, `odin_intel` is not deleted by this plan.
- No collection alias as the schema-mode discriminator.

---

## 3. Verified current baseline (read-only audit, 2026-08-10)

These values are a planning baseline, not permanent constants. The migration
preflight must measure them again immediately before execution.

| Item | Verified state |
|---|---|
| `TASKS.md` | TASK-104 Phase 1 done; Phase 2 hybrid sparse explicitly open |
| Qdrant image | `qdrant/qdrant:v1.13.2` |
| Python client | `qdrant-client==1.13.3` in Intelligence |
| FastEmbed | Not currently installed |
| Active collection | `odin_intel` |
| `odin_v2` | Absent |
| Points | 1,024,135 at initial audit; 1,025,197 at 2026-08-10 01:59 CEST, confirming active writes |
| Dense schema | One unnamed, 1024-dimensional Cosine vector |
| Sparse schema | Absent |
| Shards / replicas | 1 / 1 |
| Qdrant status | Optimizer OK, 8 segments |
| Qdrant storage | Approximately 5.3 GB total at audit time |
| Qdrant RSS | Approximately 2.02 GiB |
| Host headroom | Approximately 267 GB disk free and 25 GiB RAM available; swap nearly full |
| Snapshots | None present |
| Payload indexes | 9 present; 10 spatial indexes required by the current shared validator are still absent |
| Runtime flags | `QDRANT_COLLECTION=odin_intel`, hybrid disabled/default |
| Dominant sources | GDELT GKG 857,610; FIRMS 125,486; RAG prose is a much smaller subset |

The user-facing `qdrant_search` corpus is intentionally restricted to analysis
prose (`rss`, `rss_fulltext`, `suv_structured`, NotebookLM claims) plus allowlisted
Telegram leads. GDELT, FIRMS, UCDP, USGS, GDACS, EONET, and other structured/sensor
sources remain available to dense/structured consumers but are not part of the
BM25 corpus.

The branch now contains the committed Spatial Plan 07A writer
`services/intelligence/rag/spatial_reenrich.py` (`48a72e5`) and its Plan 07B handoff
(`12a7791`). Its apply path scrolls complete points and full-upserts spatially
reprojected replacements, so it is a real Qdrant mutation seam even if it is
operator-triggered rather than scheduler-triggered. These commits are the stable
07A baseline. Plan 07B is not implemented at this HEAD; at final plan review its
uncommitted work is actively changing spatial/retrieval files and will intentionally
change `qdrant_search.py`, state-bound filter ownership, and adjacent seams.
TASK-104's retrieval work therefore starts only on top of a committed, fully
verified 07B result, not in parallel in the same files. The first implementation
task re-runs the writer inventory against that then-current HEAD and must preserve
the spatial contract.

---

## 4. Corrections to the 2026-05-03 design

The older design is useful for intent, but the following details are not safe or
version-correct and are replaced by this plan:

1. `Modifier.IDF` does **not** turn arbitrary payload text into sparse vectors.
   FastEmbed generates document/query sparse vectors client-side; Qdrant stores the
   vectors and applies collection IDF to the query.
2. A plain `models.Document` sent to this self-hosted 1.13.2 instance fails because
   server inference is not initialized. It is not the production path.
3. Only RAG-readable prose receives `bm25`. Every point still receives the named
   dense vector. Requiring `text_for_bm25`, `source`, and `event_type` on all one
   million heterogeneous points is removed.
4. Qdrant 1.13 supports unweighted RRF only through the pinned client shape used
   here. Custom RRF `k` is available from 1.16; weighted RRF from 1.17.
5. Follower writes are never fire-and-forget. The primary result, follower result,
   and repair obligation have explicit durable states.
6. Backfill failures stop at the last acknowledged checkpoint. They are not logged
   and skipped, because silently missing points defeats the cutover proof.
7. A live `+/- 1` point-count comparison is not a valid consistency gate. The final
   gate uses a full ID manifest, mutation high-water mark, bounded writer quiescence,
   and exact delta replay.
8. Backfill covers every source point, not only one recent week. Otherwise backend,
   vision, and structured readers could not move to `odin_v2`.
9. Dense vectors are never regenerated or casually MD5-compared after Cosine
   normalization. They are copied and validated with canonical float hashes,
   tolerance, cosine, and exact-search parity.
10. `odin_intel` does not become unmirrored immediately after the target becomes
    primary. Reverse dual-write is retained for the complete rollback window.

---

## 5. Qdrant documentation verification matrix

Only capabilities available in the pinned 1.13 line are used. Current Qdrant docs
also describe later features; their availability labels are treated as hard version
boundaries.

| Claim | Official verification | Consequence for this plan |
|---|---|---|
| Query API and multi-stage hybrid queries are available from 1.10 | [Hybrid and Multi-Stage Queries](https://qdrant.tech/documentation/search/hybrid-queries/) | 1.13.2 can issue dense and sparse prefetches and fuse them in one query. |
| IDF modifier is available from 1.10 and Qdrant applies shard statistics at query time; 1.13.2 uses total available point count as `N` | [IDF Modifier](https://qdrant.tech/documentation/manage-data/indexing/#idf-modifier) and [Qdrant 1.13.2 query context](https://github.com/qdrant/qdrant/blob/v1.13.2/lib/segment/src/data_types/query_context.rs#L210-L229) | Target `bm25` must declare `Modifier.IDF`; a representative pilot must reproduce the final total point count, not contain only prose. |
| Sparse indexes are exact and immediately indexed | [Sparse Vector Index](https://qdrant.tech/documentation/manage-data/indexing/#sparse-vector-index) | No ANN recall parameter is needed for BM25; sparse score thresholds are not borrowed from dense search. |
| Sparse index `on_disk` is part of the 1.13.2 schema | [Qdrant 1.13.2 `SparseIndexParams`](https://github.com/qdrant/qdrant/blob/v1.13.2/lib/collection/src/operations/types.rs#L1557-L1581) | `bm25.index.on_disk=true` is version-valid and must be verified by target schema preflight. |
| Points may contain only a subset of named vectors | [Has vector filtering](https://qdrant.tech/documentation/search/filtering/#has-vector) | All points carry `dense`; only sparse-eligible prose carries `bm25`. `has_vector` provides an exact coverage audit on 1.13. |
| Named dense and sparse vectors can coexist | [Vectors](https://qdrant.tech/documentation/manage-data/vectors/) and [Points](https://qdrant.tech/documentation/concepts/points/) | `odin_v2` uses the fixed names `dense` and `bm25`. |
| Upsert overwrites an existing point; a disposable 1.13.2 probe confirmed that a full upsert containing only `dense` removes the point's prior `bm25` vector | [Points](https://qdrant.tech/documentation/manage-data/points/) | Full canonical upsert safely handles eligible→ineligible transitions; partial vector updates are not substituted. |
| Self-hosted users should perform client-side inference | [Inference options](https://qdrant.tech/documentation/inference/) | Use pinned FastEmbed in ingestion and Intelligence; do not depend on server inference. |
| FastEmbed BM25 requires Qdrant IDF and has asymmetric document/query encoding | [FastEmbed BM25 v0.5.1 source](https://github.com/qdrant/fastembed/blob/v0.5.1/fastembed/sparse/bm25.py) | Separate `encode_documents` and `encode_query` Interface methods and golden tests are mandatory. |
| `qdrant-client` 1.13.3 declares FastEmbed 0.5.1 | [qdrant-client v1.13.3 dependency metadata](https://github.com/qdrant/qdrant-client/blob/v1.13.3/pyproject.toml) | Pin the client in all services and FastEmbed in the two encoder-owning services. |
| Default unweighted RRF is the safe fusion without calibrated score priors | [Choosing a Fusion Method](https://qdrant.tech/documentation/search/hybrid-queries/#choosing-a-fusion-method) | Use native RRF; never linearly mix unbounded BM25 and bounded cosine scores. |
| Custom RRF `k` starts in 1.16 and weighted RRF in 1.17 | [RRF version annotations](https://qdrant.tech/documentation/search/hybrid-queries/#reciprocal-rank-fusion-rrf) | Do not put weights or `rrf_k=60` in 1.13 code/config/tests. |
| Adding/removing vector definitions on an existing collection starts in 1.18 | [Update Vector Schema](https://qdrant.tech/documentation/manage-data/collections/#update-vector-schema) | The pinned 1.13 source is not changed in place; create `odin_v2`. |
| Collection alias changes are atomic | [Collection Aliases](https://qdrant.tech/documentation/manage-data/collections/#collection-aliases) | Aliases are not used here because an alias cannot atomically switch the application schema mode; config validation is the cutover barrier. |
| Cosine vectors are normalized at upload | [Collections and distance metrics](https://qdrant.tech/documentation/manage-data/collections/) | Copy retrieved dense values; validate numerical parity rather than assuming original input bytes survive. |
| Snapshots include collection data/config but not aliases and restore requires the same minor line | [Snapshots](https://qdrant.tech/documentation/operations/snapshots/) | Download, checksum, and restore into a disposable 1.13.x instance before proceeding. |
| Batch upload should use bounded batches; payload indexes should exist before load | [Bulk Upload](https://qdrant.tech/documentation/database-tutorials/bulk-upload/) | Start with 64 points and one uploader for the one-shard collection; create payload indexes before bulk upload. |
| Indexing may be disabled during initial load and re-enabled afterward | [Optimizer](https://qdrant.tech/documentation/operations/optimizer/) | Target dense indexing can be disabled while it is non-serving, then restored and allowed to reach green before evaluation. |
| Migration can need roughly twice the source RAM/disk on the target | [Migration and Recovery](https://qdrant.tech/documentation/migration-recovery-options/) | Capacity is a hard preflight gate; same-host restored snapshot and target require additional safety margin. |

### Version boundary that must stay visible in review

Current documentation contains server-side BM25 inference and newer fusion options.
Those examples must not be copied into this implementation without their version
and deployment prerequisites. The 1.13-compatible path is explicit sparse-vector
generation plus `FusionQuery(Fusion.RRF)`.

---

## 6. Locked architecture decisions

### D1 — New collection, never in-place migration

`odin_intel` keeps its unnamed dense schema. `odin_v2` is created separately. Qdrant
1.13 cannot safely add the required named-vector schema in place; the current docs'
add/remove-vector API is explicitly a later feature.

The name allowlist contains only `odin_intel` and `odin_v2`; disposable rehearsals
use the same names on a separately marked origin so no pilot-only schema/name branch
can drift into implementation.

### D2 — Server and client versions do not move in this change

- Server: `qdrant/qdrant:v1.13.2`
- All four service clients: `qdrant-client==1.13.3`
- Sparse encoder: `fastembed==0.5.1`

An upgrade would combine two independent risk surfaces and invalidate the request
shapes and rollback proof.

### D3 — Qdrant-native means native index/IDF/fusion, not server tokenization

The document and query tokenization are client-side and versioned. Qdrant owns the
sparse index, live IDF statistics, filtering, and RRF fusion.

### D4 — One multilingual-safe BM25 contract

The first release uses:

| Setting | Fixed value | Rationale |
|---|---:|---|
| Model | `Qdrant/bm25` | Supported FastEmbed 0.5.1 BM25 model |
| `k` | `1.2` | Version-pinned model default |
| `b` | `0.75` | Version-pinned model default |
| `avg_len` | `256.0` | Version-pinned model default; changing it requires a full sparse re-index |
| `language` | `english` | Required constructor value; neutralized below |
| `disable_stemmer` | `true` | Prevent English stemming/stopword policy from damaging German, Russian transliterations, names, and identifiers |
| `token_max_length` | `40` | Version-pinned model default |
| encoder parallelism | one bounded worker per process | Avoid FastEmbed's all-core multiprocessing path competing with Qdrant/LLM services |
| lexical raw scan cap | `64,000` | Bounds quality/regex work before data-URI removal |
| lexical character cap | `12,000` | Bounds CPU/memory and adversarial documents; existing full-text chunks are below it |

With `disable_stemmer=true`, FastEmbed 0.5.1 disables both stemming and stopword
removal. Dense retrieval remains responsible for cross-language semantic matching;
BM25 is deliberately the exact lexical complement.

Changing any encoder, normalization, or lexical-quality value creates a new encoder
revision and requires a new sparse backfill. It is not a runtime tuning knob.

### D5 — Sparse eligibility follows readable prose, not collection size

Every `odin_v2` point has `dense`. A point is considered for `bm25` only if its
payload matches one of these deterministic rules:

1. `notebook_id` is present; or
2. `source` is one of `rss`, `rss_fulltext`, `suv_structured`, `telegram`.

For NotebookLM/RSS/full-text/SUV, the normalized body-or-title fallback used by the
current read guard must also pass the already deployed analysis-prose quality
contract: at least 40 characters and 8 words, no more than 25% raw data-URI
characters, and no 200+-character punctuation-free keyword soup. Data URIs are
stripped from encoded text. Telegram is intentionally only required to be non-empty
because short identifiers and callsigns are a primary reason to add BM25 and the
realtime read lane has no prose-quality gate. These exact rules and constants are
versioned with the encoder.

Telegram is indexed for all configured channels so a future allowlist change does
not require a sparse backfill. The read filter still limits served channels. A
quality-rejected analysis point and every GDELT GKG/structured/sensor point omit
`bm25`; they remain dense and filterable, and the existing read-side quality/corpus
guards remain authoritative.

Qdrant 1.13 computes the IDF `N` from all available points in the shard, including
points without the named sparse vector, while term document frequency comes from
the sparse postings. It also does not scope IDF to the analysis/realtime payload
filter in this version. This heterogeneous-collection effect is therefore part of
the frozen evaluation. The decision-grade pilot must contain every source point
with the same named dense/optional sparse representation intended for production;
a prose-only sample is not representative. If quality fails, the migration stops.

### D6 — Existing dense values and point IDs are authoritative

Backfill reads each source point with payload and vector, reuses the same ID, and
maps the unnamed vector to `dense`. TEI is not called during backfill. Deterministic
IDs preserve payload updates, deduplication, and cross-service references.

### D7 — RRF is unweighted on 1.13

Each query uses equal-weight native RRF. Retrieval quality is controlled by the
existing candidate pools and TEI reranker, not unsupported weights or raw-score
addition.

### D8 — A writer state machine replaces ambiguous booleans

`enable_hybrid` remains the Intelligence **read-path** discriminator required by the
Phase 1 decision. Writers require four states and therefore use a separate enum:

| `QDRANT_WRITE_MODE` | Authoritative write | Awaited follower | Allowed reader rollback |
|---|---|---|---|
| `dense_v1` | `odin_intel` | none | `odin_intel` |
| `dual_v1_primary` | `odin_intel` | `odin_v2` | immediate |
| `dual_v2_primary` | `odin_v2` | `odin_intel` | after follower/journal validation |
| `hybrid_v2` | `odin_v2` | none | snapshot/reconciliation only; not entered during the 30-day window |

Invalid collection/mode combinations fail during startup before any Qdrant write.
The exact shared configuration contract is:

```text
QDRANT_V1_COLLECTION=odin_intel
QDRANT_V2_COLLECTION=odin_v2
QDRANT_WRITE_MODE=dense_v1
QDRANT_MIGRATION_ID=                 # required and immutable in dual modes
QDRANT_WRITE_JOURNAL_PATH=/data/qdrant-migration/hybrid-write-journal.sqlite3
```

Read consumers retain `QDRANT_COLLECTION` and gain an explicit
`QDRANT_SCHEMA_MODE=dense_v1|hybrid_v2`; Intelligence additionally retains
`ENABLE_HYBRID`, which must be false/true respectively. Writer Adapters never infer
authority from `QDRANT_COLLECTION` or `ENABLE_HYBRID`. The intentionally valid
canary state is hybrid reads from v2 while writes remain `dual_v1_primary`; therefore
read schema and write authority are validated separately, not collapsed into one
boolean.

### D9 — No silent fallback for contract errors

Schema, encoder, model-asset, and configuration errors fail health/preflight. During
the canary window only, an explicit transient transport fallback may query
`odin_intel`; it preserves the exact pinned corpus/spatial filter, emits a metric,
and never catches contract errors. Evaluation runs with fallback disabled so defects
cannot be hidden.

### D10 — No automatic deletion

The migration CLI has no source-delete or collection-drop subcommand. Unexpected
target extras fail validation and require an explicit, separately reviewed cleanup.

### D11 — Spatial promotion is a prerequisite, not a side effect

The final read-only audit found only the nine legacy payload indexes on `odin_intel`;
the ten spatial indexes already declared by the current validator are not yet live.
Building them and re-enriching a million-point serving collection have their own
optimizer/resource and semantic risks. Hybrid production execution therefore waits
for Spatial Plan 07B code completion and the spatial promotion runbook to provide:

1. the accepted Plan-07B contract revision and service-local tests;
2. a successful staging index/re-enrichment rehearsal with real coverage;
3. all ten missing live-source payload indexes with exact types;
4. a reviewed, unchanged live full-lane dry-run followed by separately authorized
   apply; and
5. real live Analysis/Realtime coverage snapshots with stale rate `<= 1%` in every
   required lane.

This plan hardens the manually reachable index script and spatial writer for future
dual mode, and creates all required indexes on the empty `odin_v2` target before
upload. It does not execute Plan 07B, create source indexes, authorize spatial apply,
or manufacture coverage evidence. If any prerequisite above is missing, Phase 0
reports the exact state and stops.

---

## 7. Module and Interface design

This design intentionally creates two deep Modules with small Interfaces plus two
service-local mutation Adapters for vision and spatial administration. Their Depth
hides Qdrant schema conversion, BM25 asymmetry, journaling, retries, and version
details from collectors and RAG orchestration. This gives high Leverage: all writer
lanes and both query lanes use the same contracts. Locality is preserved:
source-specific text stays in one lexical policy and Qdrant transport stays in one
Adapter.

### 7.1 Data-ingestion write Module

Create `services/data-ingestion/retrieval_store/`.

Public Interface:

```text
RetrievalStore.upsert_dense_points(points) -> WriteReport
RetrievalStore.patch_nonlexical_payload(point_ids, patch) -> WriteReport
RetrievalStore.contains_authoritative(point_id) -> bool
RetrievalStore.close() -> None
```

Callers continue to provide canonical point ID, 1024-dimensional dense vector, and
payload. They do not know whether a sparse vector is needed and cannot select a
tokenizer. The Module derives lexical text and produces the appropriate
Implementation representation:

- `DenseV1Adapter`: unnamed dense vector, original payload.
- `HybridV2Adapter`: named `dense`, optional named `bm25`, original payload plus
  `_hybrid_*` audit fields.
- `DualWriteCoordinator`: authoritative write, durable mutation state, follower
  write, and repair scheduling.

The Qdrant client is an external dependency behind the Adapter Seam. Unit tests use
an in-memory fake; integration tests use the exact Qdrant 1.13.2 image.

### 7.2 Intelligence retrieval Module

Create `services/intelligence/rag/qdrant_retrieval.py` and keep
`rag/retriever.py` as orchestration for reranking and graph context.

Public Interface:

```text
QdrantRetrieval.retrieve(query, limit, filter, dense_threshold) -> candidates
QdrantRetrieval.validate_contract() -> None
QdrantRetrieval.close() -> None
```

Implementations:

- `DenseV1Retrieval`: current unnamed-vector behavior against `odin_intel`.
- `HybridV2Retrieval`: named dense plus named BM25 prefetch and RRF against
  `odin_v2`.

The FastEmbed query encoder is injected through an Interface. Tests can prove the
request shape without loading model assets. `enhanced_search` remains neutral: it
receives candidates, invokes the existing reranker, tier callback, and graph context.

### 7.3 Vision payload mutation Seam

Create `services/vision-enrichment/qdrant_projection.py`. It implements the same
write-mode and journal protocol for URL lookup plus payload patching without
importing the data-ingestion service. Contract tests prove both services emit the
same journal schema and collection transformations.

### 7.4 Spatial administrative mutation Seam

Keep the existing `ReenrichmentStore` Protocol and spatial projection engine, but
move raw Qdrant transport into an Intelligence-local
`JournaledQdrantReenrichmentStore` Adapter. It follows the same JSON write contract,
write modes, SQLite journal, and per-point leases as data ingestion; it does not
import Python modules from the separately deployed data-ingestion service.

The Adapter:

1. Scrolls only the collection authoritative for the active writer mode.
2. Canonicalizes the returned dense vector: an unnamed list is required from v1;
   named `dense` is required from v2. Existing stored `bm25` is never copied as an
   authority because it is derived data.
3. Preserves the spatial engine's full-payload replacement semantics, including
   removal of stale spatial keys, while holding the shared per-point lease.
4. Submits the canonical ID, dense vector, and complete replacement payload through
   the same v1/v2 projection contract. The v2 representation therefore recomputes
   BM25 only when the resulting point is lexically eligible; the v1 representation
   remains unnamed dense.
5. Advances the spatial page checkpoint only after the primary commit and durable
   journal transition. A failed follower may be `mirror_pending`; it is not allowed
   to disappear from the repair queue.

The spatial JSON checkpoint/file-format contract remains version 1: its
“complete-confirmed-batch” means `ReenrichmentStore.replace_points` returned
success. In dual mode that Adapter returns success only after primary+journal
durability; follower detail belongs to the hybrid journal and is not duplicated in
the spatial checkpoint file. No existing spatial projection or report field changes.

An apply run acquires and renews a journal-backed `admin_batch` lease. That lease is
mutually exclusive with `convergence` and `primary_flip`, so a spatial batch cannot
cross either collection-consistency barrier unnoticed. Dry-run remains strictly
read-only: it opens neither a mutation lease nor journal rows. Cross-service golden
tests prove that data ingestion, vision, and this Adapter agree on collection
projection and journal state semantics.

### 7.5 Legacy seams

- `services/intelligence/rag/indexer.py` has no live caller; the backend endpoint is
  a placeholder. In dual/hybrid modes it fails before Qdrant I/O. Wiring manual
  ingestion is a separate feature.
- `services/data-ingestion/feeds/gdelt_collector.py` is the dead DOC API path and is
  not migrated or registered. It also refuses non-`dense_v1` execution.
- `services/intelligence/scripts/ensure_payload_indexes.py` is a manually reachable
  schema mutation. It requires explicit `--apply`, an allowlisted exact collection,
  and schema preflight in `dense_v1`; it refuses every dual/hybrid writer mode.
  Target-bootstrap index creation remains owned by the migration CLI, and any future
  paired schema change requires a separate migration design.
- An AST-based guard enumerates Qdrant-client `upsert`, payload/vector update,
  schema/alias/snapshot, and delete calls plus raw HTTP `PUT`/`POST`/`PATCH`/`DELETE`
  calls that target Qdrant collection/point routes. Its allowlist is exact
  file+symbol+operation, not a directory wildcard. Runtime mutations outside the
  approved adapters fail CI.

### 7.6 Exhaustive writer classification

The implementation inventory is complete only when every row has an owner and an
automated guard:

| Lane or entry point | Mutation shape | Sparse policy | Hybrid owner |
|---|---|---|---|
| `BaseCollector` and structured subclasses | full point upsert/dedup | dense only unless an explicit prose rule matches | data-ingestion `RetrievalStore` |
| RSS | full point upsert | title + summary | data-ingestion `RetrievalStore` |
| Full-text enrichment | chunk upsert, then teaser status patch | title + content; status patch is non-lexical | data-ingestion `RetrievalStore` |
| Telegram | full point upsert | title | data-ingestion `RetrievalStore` |
| GDELT raw writer | full point upsert | dense only | data-ingestion `RetrievalStore` |
| NotebookLM CLI | full point upsert | title + claim/content | data-ingestion `RetrievalStore` |
| SUV structured CLI | full point upsert | title + content | data-ingestion `RetrievalStore` |
| Vision consumer | URL lookup + non-lexical payload patch | preserve current sparse vector | vision projection Adapter |
| Spatial re-enrichment apply | authoritative scroll + complete point replacement | recompute from replacement payload | Intelligence re-enrichment Adapter |
| Intelligence legacy indexer | full point upsert | not activated | fail closed outside `dense_v1` |
| Dead GDELT DOC collector | full point upsert | not registered | fail closed outside `dense_v1` |
| Payload-index ensure script | schema mutation | not applicable | explicit `dense_v1`-only admin path; fail closed in dual/hybrid |
| Migration/repair CLI | admin create/upsert/read | exact contract projection | allowlisted admin Adapter |

No row may be reclassified as “admin-only” merely to escape dual-write. Manually
reachable mutation paths are guarded just like continuously running services.

---

## 8. Target data contract

### 8.1 Collection schema

`odin_v2` is created only by the migration CLI after exact-name confirmation:

```text
collection: odin_v2
shard_number: 1
replication_factor: 1
write_consistency_factor: 1
on_disk_payload: true

vectors:
  dense:
    size: 1024
    distance: Cosine
    on_disk: false

sparse_vectors:
  bm25:
    modifier: Idf
    index:
      on_disk: true

hnsw_config:
  m: 16
  ef_construct: 100
  full_scan_threshold: 10000
  max_indexing_threads: 0
  on_disk: false

optimizers_config (serving state):
  deleted_threshold: 0.2
  vacuum_min_vector_number: 1000
  default_segment_number: 0
  max_segment_size: null
  memmap_threshold: null
  indexing_threshold: 20000
  flush_interval_sec: 5
  max_optimization_threads: null

wal_config:
  wal_capacity_mb: 32
  wal_segments_ahead: 0

quantization_config: null
```

Rationale:

- One shard matches the source and avoids changing shard-local IDF behavior.
- Dense storage matches the current semantic contract. Capacity rehearsal may stop
  the migration, but it may not silently change this schema.
- HNSW, optimizer, WAL, and no-quantization values exactly match the final read-only
  source audit. Target bootstrap may set only `indexing_threshold=0` while the
  target is non-serving, records that temporary state in its run manifest, and must
  restore the complete serving block above before validation.
- The sparse index is explicitly on disk to bound incremental RAM on the
  swap-pressured host. The pilot must verify latency.
- The following required payload indexes are created before upload. Internal audit
  fields do not receive indexes because no runtime filter uses them.

| Type | Fields |
|---|---|
| `keyword` | `source`, `telegram_channel`, `notebook_id`, `feed_name`, `url`, `fulltext_article_id`, `fulltext_status`, `spatial_about_scope_revision_tokens`, `spatial_occurrence_scope_revision_tokens`, `spatial_basis`, `spatial_precision`, `spatial_catalog_revision`, `spatial_projection_revision`, `spatial_derivation_version`, `spatial_conflict_scope_keys` |
| `bool` | `superseded_by_fulltext`, `spatial_conflict` |
| `float` | `fulltext_retry_epoch` |
| `geo` | `geo` |

This list is frozen into the retrieval contract from the current shared validators.
Task 1 compares it to completed Plan 07B before implementation; any genuine new
required spatial index is an explicit contract diff, not an ad hoc target tweak.

Runtime services may validate this schema but may never create it automatically.
The current generic “at least one sparse vector” validation is tightened to exactly
`dense` and `bm25`, correct dimension/distance, and `Modifier.IDF`.

### 8.2 Canonical lexical text

Normalization is a pure function shared by document ingestion and backfill:

1. Select the lexical fields and separate quality input from the table below;
   convert only contract-permitted values to strings.
2. Bound both the assembled lexical raw input and quality raw input to 64,000 Unicode
   code points before regex work; the lexical budget is consumed in table field
   order including its separator.
3. Measure data-URI character fraction on the bounded quality input, then remove
   `data:<mime>;base64,...` spans from every lexical field and the quality input
   using the existing shared regex.
4. Normalize each field independently with Unicode NFKC, remove NUL/non-whitespace
   controls, collapse Unicode whitespace to one ASCII space, and trim.
5. Join non-empty normalized lexical fields with one newline and truncate both the
   joined lexical text and normalized quality input to 12,000 Unicode code points.
6. Apply the source-specific quality rule to the quality input using its measured
   raw data-URI fraction plus cleaned length/word/structure. Reject rather than emit
   an empty sparse vector.
7. Do not case-fold or stem here; the pinned encoder owns token normalization.

| Point type | Lexical text expression | Quality input |
|---|---|---|
| RSS | `title + "\n" + summary` | `summary`, else `title` |
| RSS full text | `title + "\n" + content` | `content`, else `title` |
| NotebookLM claim | `title + "\n" + content` | `content`, else `title` |
| SUV structured profile/program | `title + "\n" + content` | `content`, else `title` |
| Telegram | `title` only | non-empty `title`; prose thresholds disabled |
| Everything else | no sparse vector | not applicable |

Telegram is title-only because historical payloads do not retain the full message
text. Expanding that payload is a privacy/data-contract change and is not smuggled
into this migration.

No duplicate `text_for_bm25` body is required. The target payload adds only:

```text
_hybrid_contract_revision = "qdrant-hybrid-v1"
_bm25_text_sha256          = hash of normalized lexical text, only when bm25 emitted
_bm25_encoder_revision     = "fastembed-bm25-0.5.1-v1", only when bm25 emitted
```

Payload and dense hashes are calculated in the external migration manifest, not
stored as mutable point metadata. That avoids stale hashes and read-modify-overwrite
races when vision or full-text status patches touch a point. Validation strips
`_hybrid_*` and `_bm25_*` before payload parity comparison. Repair from `odin_v2` to
`odin_intel` strips these fields as well.

### 8.3 Encoder asymmetry

Document writes call the FastEmbed document encoder, which includes term-frequency
and document-length normalization. Queries call the query encoder, whose term values
are different. Calling document encoding for a query is a correctness defect.
Both paths canonicalize to sorted uint32 indices and paired finite float32 values
before hashing or Qdrant I/O.

Golden tests cover:

- English, German, Cyrillic transliteration, acronyms, model numbers, hyphenated
  identifiers, punctuation, repeated terms, empty input, and 12,000-character cap.
- Same token IDs between document/query modes for the same normalized terms.
- Different values where document TF normalization is expected.
- Query values exactly match FastEmbed 0.5.1; the Adapter then sorts index/value
  pairs by index, because FastEmbed's raw set/dict order is not a storage contract.
- Deterministic output across data-ingestion and Intelligence.

---

## 9. Durable dual-write and convergence protocol

### 9.1 Why a journal is required

A primary write can succeed while the follower is unavailable. Logging alone loses
the repair obligation, and collector deduplication can then prevent the point from
ever being retried. Redis is not used as the source of truth because the current
instance has a 512 MB `allkeys-lru` eviction policy.

Use a small SQLite journal on a shared local bind mount:

```text
host:      ${ODIN_DATA_DIR}/qdrant-migration/hybrid-write-journal.sqlite3
container: /data/qdrant-migration/hybrid-write-journal.sqlite3
```

Both data-ingestion profiles, Intelligence, and vision-enrichment mount the same
local directory. Manual NLM/SUV commands and spatial re-enrichment apply runs in
dual modes must point to the same path. A read-only Intelligence process need not
open the journal, but any process configured to mutate Qdrant in a dual mode fails
before Qdrant I/O if the journal cannot be opened, locked, and committed. Network
filesystems are forbidden; SQLite uses WAL mode, foreign keys, and a bounded busy
timeout.

Preflight resolves the canonical host path below `ODIN_DATA_DIR`, rejects symlinks,
non-regular existing files, and world-writable directories, and verifies that every
configured container identity can create, lock, and commit the database plus its
`-wal` and `-shm` siblings. Use a `0700` directory and `0600` files. No cleanup
command may target `ODIN_DATA_DIR` itself or an unresolved environment variable.

The journal stores IDs, state, field names, canonical SHA-256 fingerprints, and
bounded error metadata—never vectors, payload bodies, lexical text, or query text.
The fingerprint proves which intended representation reached the primary without
making the journal a second corpus.

Error metadata is a typed code plus a redacted 300-character transport summary;
serialized request/response bodies and credentials are discarded.

For a full upsert, the fingerprint covers point ID, canonical JSON payload, vector
names, L2-normalized float32 dense values quantized at `1e-6`, and optional sparse
indices/float32 values in sorted-index order. For a patch, it covers point ID and
canonical JSON of only the changed fields. The exact byte framing is part of the JSON
contract rather than implicit string concatenation. A Qdrant 1.13.2 round-trip
golden test must prove that the pre-write and retrieved representations produce the
same fingerprint despite Cosine upload normalization; otherwise dual mode cannot be
enabled.

### 9.2 State model

One row per point mutation:

```text
prepared -> primary_committed -> mirrored
                         \----> mirror_pending -> mirrored
prepared -> recovered_primary_committed -> mirrored/mirror_pending
prepared -> source_retry_required -> superseded/mirrored by a later retry
any nonterminal older row -> superseded (only by a proven later primary commit)
```

Required columns include migration ID, operation ID, point ID, operation kind,
changed field names for a non-lexical patch, primary/follower collection, state,
the SHA-256 fingerprint of the intended authoritative representation (or changed
field subset), timestamps, attempts, and last error. Each state transition also
receives a global, append-only sequence. In particular, `prepared_seq` and
`primary_commit_seq` are different: an operation prepared before a reconciliation
barrier but committed after it must receive a post-barrier commit sequence. Values,
vectors, and payload bodies are not journaled. A batch uses one operation ID and one
child row per point.

Only writes that change the active authority allocate `primary_commit_seq`.
Backfill, reconciliation, delta replay, and repair are follower/admin projections;
they use their resumable run checkpoints and reference the causal primary sequence
without pretending to be new source mutations. Spatial apply is a true authoritative
mutation and therefore does allocate a sequence.

Every coordinator and repair worker uses a journal-backed per-point lease. Batch
leases are acquired in stable point-ID order. Before repairing an older pending row,
the worker checks a materialized `point_watermark` containing the maximum
`primary_commit_seq`, operation ID, and authoritative fingerprint for that point: a
later mirrored mutation supersedes the older obligation; otherwise only the latest
committed mutation is repaired. The watermark is updated in the same SQLite
transaction as each primary-commit transition. This prevents a delayed repair from
overwriting a newer follower value even after old completed event rows are archived.

The same database has renewable operation leases with owner, purpose, start time,
heartbeat, and expiry. `admin_batch` leases may coexist with normal journaled point
writes, but are mutually exclusive with `convergence` and `primary_flip`. The
migrator refuses to enter either barrier until active admin batches finish; a
spatial apply refuses to start while either barrier exists. An expired lease is
reclaimed only after its owning process is proven absent and the operator supplies
the migration confirmation token—timeout alone never authorizes overlapping
administrative writers. Lease time comparisons use SQLite's clock inside the same
transaction, not independently skewable process clocks; the owner record includes
host/container identity, process ID, and process-start token to avoid PID-reuse
mistakes.

Write order:

1. Validate IDs, dense dimension, payload JSON, lexical contract, and both target
   representations in memory; compute their canonical fingerprints.
2. Commit `prepared` rows.
3. Write the authoritative collection with `wait=true`.
4. Commit `primary_committed` and allocate its global `primary_commit_seq`.
5. Write the follower with `wait=true`.
6. Commit `mirrored`, or `mirror_pending` with the typed error.
7. Return `WriteReport(primary_committed=true, follower_committed=...)`.

If journaling fails before step 3, no Qdrant write occurs. If the primary fails, the
source collector sees failure and retains its existing retry semantics. If only the
follower fails, the primary ingestion remains successful and the repair worker owns
the retry. If journal state cannot be committed after primary success, return a
failure to the caller, emit a critical `UnjournaledPrimaryCommit`, retain the
`prepared` row, and make the next dedup check call `ensure_mirrored`.

After a crashed/stale `prepared` lease, recovery reads the current authoritative
point and compares its canonical fingerprint. A match proves the primary commit and
allocates a new recovery `primary_commit_seq` before mirroring. A mismatch or absent
point without a later proven commit becomes `source_retry_required`; it is never
silently abandoned. A later successful retry either mirrors it or marks it
`superseded`. This deliberately prefers a visible ingestion retry/blocker over
inventing data the journal does not store.

`patch_nonlexical_payload` accepts only fields outside the lexical-policy inputs. It
uses Qdrant `set_payload` on the primary and follower, so it cannot overwrite
unrelated concurrent payload fields. The journal stores the field names; repair
retrieves their latest values from the authoritative point and reapplies only those
fields. A caller that changes `title`, `summary`, `content`, `source`, or
`notebook_id` must submit a complete canonical upsert so BM25 is recomputed. Current
full-text status and vision patches are non-lexical. The full-text invariant remains:
chunks are durably written before the teaser is marked superseded.

For a full v2 upsert, the Adapter always supplies the complete vector map: `dense`
plus `bm25` when eligible, or `dense` alone when ineligible. Qdrant 1.13.2 overwrite
semantics then remove a stale prior sparse vector; an integration test freezes this
eligible→ineligible transition.

### 9.3 Repair worker

The repair worker scans stale `prepared`, `source_retry_required`,
`primary_committed`, and `mirror_pending` rows, acquires the per-point lease, and
repairs only the latest provable mutation. It:

1. Re-checks that no later primary-commit sequence already supersedes the row.
2. Resolves a stale `prepared` row using its intended fingerprint as described
   above; it never assumes that an attempted primary call succeeded.
3. For a committed upsert, retrieves the latest authoritative point with payload and dense
   vector, re-runs the version-pinned projection, and upserts the follower.
4. For a committed non-lexical patch, retrieves only the latest authoritative values of the
   journaled field names and applies `set_payload` to the follower.
5. Uses `wait=true`, verifies the affected representation/fields and intended/latest
   fingerprint relationship, and marks the row
   mirrored.

It never replays a stale serialized vector or payload from the journal. Retries use
bounded exponential backoff and expose oldest-pending age, pending count, attempt
count, and permanent-error count.

All completed rows from the initial dual-write barrier are retained through the
first sealed convergence manifest because they define its delta. After that seal,
completed rows are exported as a compressed, checksummed audit artifact and may be
pruned after 72 hours only if no older nonterminal row exists for that point;
pending rows are never pruned. Materialized per-point watermarks, run/barrier
metadata, and daily parity manifests are retained through the 30-day rollback
window. This prevents the high-volume GDELT lane from growing SQLite without bound
without reviving a stale repair after its superseding event was archived.

### 9.4 Final high-water convergence

The journal also solves live-write races during backfill:

1. Record high-water `H0 = max(primary_commit_seq)` and the reconciliation run ID.
2. Perform a full live-source reconciliation into the target while writers continue.
3. Acquire the exclusive `convergence` lease and enter a rehearsed, bounded
   writer-only maintenance window. Reads stay online. Acquisition fails if a
   spatial/admin batch is active.
4. Stop APScheduler/data-ingestion, vision mutations, spatial re-enrichment apply
   jobs, and manual NLM/SUV writers; wait for in-flight operations and journal
   commits.
5. Replay distinct authoritative point IDs with `primary_commit_seq > H0`. An
   operation prepared before H0 but committed later is included by construction.
6. Resolve every stale `prepared`/`source_retry_required` row and drain all
   `primary_committed`/`mirror_pending` rows regardless of sequence. Any unresolved
   row aborts the manifest seal.
7. Build and compare exact source/target manifests.
8. Seal the manifest, release the barrier lease, and resume dual-write.

The rehearsal must prove this pause fits a 20-minute budget. If not, resume writers,
keep `odin_intel` serving, improve the reconciliation process, and repeat; do not
extend an unplanned outage.

No production delete path currently exists. The AST guard makes introduction of one
an explicit design change; target extras therefore fail rather than being pruned.

---

## 10. Hybrid query contract

For each analysis or realtime call, build one Qdrant `query_points` request:

```text
prefetch[0]:
  query: existing 1024-dimensional TEI query embedding
  using: dense
  filter: exact Plan-07B combined corpus + pinned spatial/AOI filter
  limit: existing lane pool (analysis 40, realtime 20)
  score_threshold: existing threshold applied only to dense lane when supplied

prefetch[1]:
  query: FastEmbed query sparse vector
  using: bm25
  filter: the exact same combined filter
  limit: same lane pool
  score_threshold: omitted

top-level query: FusionQuery(Fusion.RRF)
top-level limit: same lane pool
with_payload: true
```

Rules:

- Never submit query text as `models.Document` to the server.
- Never call the document sparse encoder for a query.
- Never apply the current cosine threshold to fused RRF or BM25 scores.
- Never add dense and BM25 raw scores.
- Preserve the fused score as retrieval diagnostics; the existing TEI reranker score
  remains the basis for tier boosting.
- Apply identical filters to both prefetches. Do not claim that a top-level filter
  post-filters `FusionQuery` on the pinned 1.13 client/server path; fusion operates on
  the supplied prefetch result sets. Post-query `validate_lane` remains the second
  corpus-policy barrier.
- Preserve Plan 07B's nested filter structure: do not flatten the outer corpus
  policy or the relation-specific `about|occurrence|either` filter, and do not accept
  model-supplied region/scope overrides. `world` adds no spatial predicate. Empty,
  partial, stale, no-hit, or Qdrant-error paths never retry without the pinned scope.
- Points without `bm25` can still enter through the dense prefetch.
- Analysis failure is surfaced. Realtime remains best-effort exactly as today.

The initial pool sizes are fixed to existing values; no hidden tuning occurs during
implementation. A later pool change requires the frozen evaluation report.

---

## 11. Migration sequence and gates

| Phase | Serving reads | Write mode | Mutation allowed | Exit gate |
|---|---|---|---|---|
| 0. Code/contract | `odin_intel` | `dense_v1` | none on live Qdrant | all tests/inventory green; Plan 07B and spatial promotion evidence satisfy D11 |
| 1. Offline pilot | disposable restored snapshot | none | capacity-gated source snapshot plus disposable instance only | downloaded checksum/restore and quality/performance gates pass |
| 2. Safety backup | `odin_intel` | `dense_v1` | source snapshot only | downloaded SHA-256 and restore drill pass |
| 3. Target bootstrap | `odin_intel` | `dense_v1` | create/index empty `odin_v2` | exact schema and empty target verified |
| 4. Forward mirror | `odin_intel` | `dual_v1_primary` | normal writes to both | every writer lane/journal healthy |
| 5. Consistent baseline | `odin_intel` | `dual_v1_primary` | second source snapshot | snapshot restored on 1.13.x |
| 6. Backfill | `odin_intel` | `dual_v1_primary` | idempotent target upserts | checkpoint complete, optimizer green |
| 7. Convergence | `odin_intel` | `dual_v1_primary` | reconcile + bounded pause | exact manifests, no pending repairs |
| 8. Shadow | dense result served | `dual_v1_primary` | sampled hybrid reads only | shadow/eval/resource gates pass |
| 9. Read cutover | `odin_v2` hybrid | `dual_v1_primary` | normal writes | 48 hours healthy; instant read rollback retained |
| 10. Target primary | `odin_v2` hybrid | `dual_v2_primary` | reverse mirror to v1 | 30-day rollback window healthy |
| 11. Phase complete | `odin_v2` hybrid | still `dual_v2_primary` | no deletion | report archived; retirement task opened |

Aliases are deliberately absent from this table. Qdrant can switch an alias
atomically, but it cannot also atomically change the application's unnamed-vs-named
query shape. The Intelligence deployment changes `QDRANT_COLLECTION` and
`QDRANT_SCHEMA_MODE` plus `ENABLE_HYBRID` together and validates the triple before
becoming healthy.

---

## 12. Acceptance gates

### 12.1 Contract and structural gates

- Source collection is exactly `odin_intel`; target is exactly `odin_v2`; names are
  unequal and allowlisted.
- Server reports 1.13.2 and clients/encoder report the exact pinned versions.
- `odin_intel` still has the Phase 1 unnamed dense schema.
- `odin_v2` has exactly named `dense` and `bm25` with the schema in section 8.
- Runtime writers cannot auto-create a collection.
- AST inventory has no unapproved direct Qdrant mutation.
- Spatial apply resolves the authoritative vector shape through its approved Adapter;
  its domain engine contains no raw collection-selecting upsert.
- Source has the exact required payload-index names/types and accepted spatial
  coverage/stale evidence; preflight reports but does not repair or apply either.
- FastEmbed assets load with outbound network disabled in both production images.

### 12.2 Data parity gates

After the writer pause and delta replay:

- Source ID set equals target ID set exactly; no `+/- 1` tolerance.
- Source count equals target count.
- `has_vector("dense")` count equals target count.
- `has_vector("bm25")` count equals the deterministic sparse-eligible,
  quality-accepted count produced from the source manifest.
- Every ineligible/quality-rejected point lacks `bm25`; every eligible accepted
  point has it.
- Canonical source payload hash equals target payload hash after removing audit keys.
- Source-field distribution, missing-source count, and payload-index schema match.
- Every dense vector is length 1024. The full manifest compares a canonical
  float32 fingerprint quantized at `1e-6`; every fingerprint mismatch receives a
  full component comparison. In addition, a stratified sample of at least 10,000
  points has component max error `<= 1e-6` and cosine `>= 0.999999`.
- Exact dense search on the frozen query set returns the same top-20 relevance set
  and scores (`<= 1e-6` delta) between source unnamed dense and target named dense.
  Boundary ties are expanded and compared as a set rather than relying on arbitrary
  tie ordering. Against each collection's exact result, target ANN Recall@20 must be
  at least `0.95` mean, at least `0.80` at p5, and no more than `0.01` below source
  mean Recall@20 on the same queries.
- Repair pending count and oldest pending age are zero.
- Stale `prepared`, `source_retry_required`, and unjournaled-primary counts are zero.
- Target collection is green, optimizer status is OK, the captured indexing
  threshold is restored, and segment/indexed-vector counters are stable across three
  polls 60 seconds apart before it serves traffic. Qdrant counters are treated as
  approximate; equality with point count is not asserted. ANN overlap/latency gates
  prove the serving index operationally.

The full manifest is disk-streaming, not a million-point in-memory dictionary.
Each side scrolls payload/vectors in bounded pages and writes only canonical ID plus
payload/dense/sparse hashes and eligibility flags into 256 SHA-256 ID buckets in a
run-specific directory. Integer and UUID IDs carry distinct type tags. Each bucket
is externally sorted and compared; the final report contains per-bucket checksums,
counts, mismatch samples, and an overall digest, never payload or vector bodies.
Temporary-space need is included in the capacity ledger, and resume binds the run to
collection/schema/contract/barrier digests.

### 12.3 Frozen relevance evaluation

Create a reviewed JSONL set with at least 160 queries and known-relevant point IDs:

| Slice | Minimum |
|---|---:|
| Exact identifiers/model numbers/acronyms/vessel or organization names | 40 |
| Exact titles/quoted phrases/entities | 25 |
| Semantic paraphrases | 30 |
| German or cross-language questions | 20 |
| Realtime Telegram identifiers/names | 10 |
| Negative/common-term/adversarial noise | 15 |
| Plan-07B world/about/occurrence/either scope enforcement and no-fallback | 20 |

Freeze the set before comparing systems. Report candidate Recall@40 and MRR@10,
then post-reranker Recall@10, MRR@10, and nDCG@10 by slice and overall.

Go criteria:

- Exact-identifier post-reranker MRR@10 is at least `0.85` and improves by at least
  `0.10` absolute over dense-only.
- Overall post-reranker nDCG@10 is no more than `0.02` below dense-only.
- Semantic-paraphrase Recall@10 is no more than `0.02` below dense-only.
- German/cross-language Recall@10 is no more than `0.03` below dense-only.
- Negative/noise queries do not increase false-positive result rate by more than
  `0.02` absolute.
- Corpus-policy leakage is exactly zero for analysis and realtime lanes.
- Spatial-scope leakage and unscoped retry count are exactly zero; `world` hybrid
  results remain equivalent to the same query without a spatial predicate.
- Every result remains reproducibly attributable to the same payload/evidence path.

If exact-match gain is not achieved, stop. Do not compensate by adding unsupported
weights or changing tokenizer values in place.

### 12.4 Performance and resource gates

- Hybrid Qdrant-stage p95 is `<= max(250 ms, 1.75 * dense p95)` on the same replay.
- End-to-end post-reranker p95 increases by no more than 200 ms.
- Dual-write primary ingestion p95 increases by no more than 2x and scheduler jobs
  do not miss their configured interval.
- Qdrant RSS remains below 80% of physical RAM; no sustained swap-in/swap-out or OOM.
- Free disk remains at least 20% throughout.
- Before any snapshot, produce a per-filesystem peak-space ledger covering snapshot
  temp space, retained server snapshot, downloaded copy, disposable restored source,
  and full hybrid target. If they share one filesystem, the first rehearsal reserves
  conservatively `2 * source_bytes` for the two snapshot copies, `source_bytes` for
  restore, `1.5 * source_bytes` for the first target estimate, plus 20 GiB. After the
  pilot, production uses measured snapshot/restore/target bytes rather than that
  estimate. Snapshot compression is never a proxy for restored size.
- Available RAM before a same-host rehearsal must exceed twice current Qdrant RSS
  (the disposable restored source plus target allowance) plus an 8 GiB host reserve;
  the measured pilot peak becomes the production target gate.
- Interactive dense read p95 during backfill regresses by no more than 25%; otherwise
  throttle or pause backfill.

### 12.5 Shadow/cutover gates

- Shadow runs for at least 24 hours plus a controlled replay of at least 1,000
  representative queries.
- Shadow logs only a run-scoped HMAC-SHA-256 query token, point IDs, ranks, latency,
  mode, and typed errors—not raw query text, a dictionary-attackable plain hash, or
  payload bodies. The HMAC key comes from secret configuration and is rotated after
  the evaluation window.
- Hybrid schema/encoder errors are zero.
- Transient fallback rate is below 0.1%; evaluation fallback rate is zero.
- No journal repair is older than 10 minutes and pending count returns to zero.
- Read rollback has been rehearsed against current deployment artifacts.

---

## 13. File plan

### Create

- `contracts/qdrant-hybrid-retrieval-v1.json`
- `contracts/qdrant-hybrid-write-journal-v1.json`
- `services/data-ingestion/retrieval_store/__init__.py`
- `services/data-ingestion/retrieval_store/models.py`
- `services/data-ingestion/retrieval_store/lexical.py`
- `services/data-ingestion/retrieval_store/bm25.py`
- `services/data-ingestion/retrieval_store/adapters.py`
- `services/data-ingestion/retrieval_store/coordinator.py`
- `services/data-ingestion/retrieval_store/journal.py`
- `services/data-ingestion/qdrant_hybrid_migration/__init__.py`
- `services/data-ingestion/qdrant_hybrid_migration/cli.py`
- `services/data-ingestion/qdrant_hybrid_migration/backfill.py`
- `services/data-ingestion/qdrant_hybrid_migration/manifest.py`
- `services/data-ingestion/qdrant_hybrid_migration/validation.py`
- Focused data-ingestion tests for each file above plus writer-inventory and Qdrant
  1.13.2 integration tests.
- `services/intelligence/rag/bm25.py`
- `services/intelligence/rag/qdrant_retrieval.py`
- `services/intelligence/rag/qdrant_reenrichment_store.py`
- `services/intelligence/evals/qdrant_hybrid_v1.jsonl`
- `services/intelligence/evals/run_qdrant_hybrid.py`
- Intelligence encoder, request-shape, filter, fallback, evaluation, and integration
  tests.
- Intelligence spatial dual-write/lease/vector-shape contract tests.
- `services/vision-enrichment/qdrant_projection.py`
- Vision dual-patch/journal contract tests.
- `docs/runbooks/qdrant-hybrid-migration.md`
- Execution report under `docs/reports/` when the migration is actually run.

### Modify

- `services/data-ingestion/pyproject.toml` and tracked
  `services/data-ingestion/uv.lock`
- `services/intelligence/pyproject.toml`
- `services/backend/pyproject.toml`
- `services/vision-enrichment/pyproject.toml`
- `services/data-ingestion/config.py`
- `services/intelligence/config.py`
- `services/backend/app/config.py`
- `services/vision-enrichment/config.py`
- `services/data-ingestion/scheduler.py`
- `services/intelligence/main.py`
- `services/backend/app/main.py`
- `services/vision-enrichment/main.py`
- All four service-local Qdrant schema validators/tests.
- `services/data-ingestion/feeds/base.py`
- `services/data-ingestion/feeds/rss_collector.py`
- `services/data-ingestion/feeds/fulltext_collector.py`
- `services/data-ingestion/feeds/telegram_collector.py`
- `services/data-ingestion/gdelt_raw/writers/qdrant_writer.py`
- `services/data-ingestion/nlm_ingest/ingest_qdrant.py`
- `services/data-ingestion/nlm_ingest/cli.py`
- `services/data-ingestion/suv_structured/cli.py`
- `services/intelligence/rag/retriever.py`
- `services/intelligence/rag/indexer.py`
- `services/intelligence/rag/spatial_reenrich.py`
- `services/intelligence/tests/test_spatial_reenrich.py`
- `services/intelligence/scripts/ensure_payload_indexes.py` and its tests
- `services/vision-enrichment/consumer.py`
- `services/data-ingestion/Dockerfile`
- `services/intelligence/Dockerfile`
- `services/vision-enrichment/Dockerfile`
- `docker-compose.yml` and `.env.example`
- `services/data-ingestion/qdrant_doctor/`
- `docs/runbooks/qdrant-collection-rollback.md`
- `decisions.md`, `architecture.md`, `docs/architecture.md`, and `TASKS.md` only
  after the implementation/cutover evidence exists.

### Explicitly do not modify for the feature

- Dense embedding model or TEI service configuration.
- RAG corpus source/type allowlists.
- Legacy GDELT collector registration.
- Neo4j read/write paths.
- Spatial derivation and payload semantics; only the Qdrant transport/coordination
  Adapter and its checkpoint durability boundary change.

---

## 14. TDD implementation tasks

Every task follows red → minimal green → refactor. Do not combine migration execution
with feature implementation commits.

### Task 1 — Freeze contracts and re-audit seams

**Tests first**

- Add a repository contract test that parses both new JSON contracts.
- Add an AST inventory test that initially fails on every direct Qdrant mutation.
- Assert the active scheduler uses GDELT raw and not the dead DOC collector.
- Assert all service defaults remain Phase 1 (`odin_intel`, hybrid disabled,
  `dense_v1`) before an operator explicitly changes them.
- Add a read-only fixture for the currently missing ten source spatial indexes and
  prove Phase 0 stops with an exact prerequisite report rather than creating them.
- Add fixtures for missing Plan-07B contract revision, unapproved/mismatched dry-run,
  absent real coverage, and stale rate above 1%; every case stops read-only.

**Implementation**

- Write exact version, vector names, encoder settings, lexical policy, audit keys,
  accepted Plan-07B spatial contract revision, journal states, operation leases,
  write modes, and allowed collection names into the contracts.
- Classify every mutation as adapter-owned, legacy-disabled, admin-only, or test-only.
- Reconcile this inventory with completed Plan 07B before changing any overlapping
  file; preserve its pinned runtime-token ownership and fail-closed no-retry rules.

**Gate**

- No unknown mutation seam remains.
- Contract JSON has no placeholder or “TBD”.

**Suggested commit:** `test(data-ingestion): freeze qdrant hybrid contracts`

### Task 2 — Pin and prove the BM25 encoder

**Tests first**

- Data-ingestion and Intelligence golden tests for normalization and document/query
  vectors.
- Cross-service fixture test proving identical query output and document output.
- Test empty, base64-heavy, short, too-few-word, and keyword-soup analysis text
  yields no sparse vector, while short non-empty Telegram identifiers do.
- Boundary tests freeze the 64,000/12,000 caps and every quality threshold.
- Test version/config mismatch fails before encoding.
- Docker smoke test runs with network disabled after image build.

**Implementation**

- Pin `qdrant-client==1.13.3` in data ingestion, Intelligence, backend, and vision;
  pin `fastembed==0.5.1` only in data ingestion and Intelligence.
- Regenerate only the tracked data-ingestion lockfile; do not add ignored lockfiles.
- Implement separate document/query methods and bounded batching.
- Initialize one encoder per process and run its synchronous CPU work through one
  bounded executor/semaphore so async collectors and FastAPI requests never block
  their event loops or invoke all-core multiprocessing.
- Bake/cache the 0.5.1 BM25 assets in both runtime images; set an explicit cache
  path, instantiate with `local_files_only=true` at runtime, and fail startup if
  assets are absent. Network access is allowed only in the image-build prefetch
  stage, not as a production recovery mechanism.

**Gate**

- Exact golden outputs pass in both services and containers without network.

**Suggested commit:** `feat(rag): add versioned fastembed bm25 adapters`

### Task 3 — Make configuration and schema validation exact

**Tests first**

- Table-test all valid and invalid read/write mode combinations.
- Reject same source/target name, unknown names, missing/mismatched migration ID,
  missing journal, missing target, unnamed target dense, wrong dimension/distance,
  wrong sparse name, or missing IDF.
- Reject `ENABLE_HYBRID=true` unless the Intelligence collection/schema mode is v2.
- Prove runtime collectors cannot auto-create a collection in dual/hybrid modes.

**Implementation**

- Add the writer state enum and explicit v1/v2 collection settings.
- Add `qdrant_schema_mode` to non-query services that later read `odin_v2`.
- Tighten all service-local validators to the exact contracts.
- Wire validation into each service lifecycle so an invalid contract never reaches a
  ready/healthy state; manual writer CLIs run the same preflight before work.
- Extend `odin-qdrant-doctor` with read-only source/target/version/schema/resource and
  journal checks.

**Gate**

- A wrong env combination prevents health/startup before Qdrant mutation.

**Suggested commit:** `feat(qdrant): enforce exact hybrid runtime modes`

### Task 4 — Build the deep write Module and journal

**Tests first**

- Pure projection tests for dense v1, hybrid eligible, hybrid ineligible, audit
  hashes, reverse projection, mixed int/UUID IDs, and 1024 finite-component/nonzero-
  norm dense enforcement.
- Sparse canonicalization sorts paired index/value entries; validation rejects
  unequal lengths, duplicate or out-of-uint32 indices, and non-finite/negative
  values. Empty output omits `bm25` entirely.
- Qdrant 1.13.2 integration tests prove eligible→ineligible full upsert removes stale
  `bm25`, and the reverse transition adds it without changing the dense contract.
- State-machine tests for primary failure, follower failure, journal failure at each
  boundary, retry, idempotent replay, batch partial response, and process restart.
- Crash-window tests prove a matching prepared fingerprint recovers/mirrors, a
  mismatch requires source retry, and a later committed mutation safely supersedes
  an older row without replaying stale data.
- Operation-lease tests cover admin/convergence/primary-flip mutual exclusion,
  heartbeat renewal, refused blind expiry takeover, and crash recovery with an
  explicit confirmation token.
- Test that non-lexical patches touch only named fields and lexical-field patches are
  rejected in favor of a complete upsert.
- Dedup test proving a source duplicate with missing follower is repaired.
- Multiprocess SQLite WAL/per-point-lease test, including a delayed older repair
  racing a newer mutation, on a local temp directory.
- Archive/prune test proves a retained point watermark still supersedes an old
  pending repair after the newer completed event row has left the live journal.

**Implementation**

- Implement the Interface, Adapters, coordinator, write reports, and journal.
- Use `AsyncQdrantClient` behind the Adapter and `wait=true` for migration writes.
- Add repair worker and metrics.
- Add the shared local bind mount to both data-ingestion profiles, Intelligence, and
  vision.

**Gate**

- Killing the fake process after every state transition leaves a deterministically
  repairable state.

**Suggested commit:** `feat(data-ingestion): add durable qdrant dual-write seam`

### Task 5 — Route all active point writers through the Interface

**Tests first, lane by lane**

- BaseCollector subclasses: all dense, no accidental BM25 for structured sources.
- RSS: title+summary BM25.
- Fulltext: title+content BM25 and chunk-before-supersede ordering across both stores.
- Telegram: title-only BM25 and primary-success semantics with pending follower.
- GDELT raw: dense-only, same deterministic IDs/payload/spatial fields.
- NotebookLM: title+claim BM25, notebook-ID eligibility, same deterministic IDs.
- SUV company/procurement: title+content BM25.
- Static test fails if these files regain direct mutation calls.

**Implementation**

- Inject/create one `RetrievalStore` per job lifecycle; close it deterministically.
- Replace direct upsert/retrieve-dedup/payload-patch calls with the Interface.
- Preserve each collector's existing upstream failure, retry, and Neo4j ordering.
- Keep source-specific point builders pure; sparse policy stays in the Module.

**Gate**

- Existing dense-v1 test behavior is unchanged when `QDRANT_WRITE_MODE=dense_v1`.
- All dual-mode lane tests prove both representations and journal state.

**Suggested commit:** `refactor(data-ingestion): route qdrant writers through store`

### Task 6 — Cover vision, spatial apply, and hidden legacy writes

**Tests first**

- Vision URL lookup uses the authoritative collection for the active write mode.
- Vision patch mirrors, journals follower failure, ACKs only after primary+journal
  durability, and does not rerun expensive inference merely for a pending mirror.
- Spatial dry-run performs zero mutation/journal/lease writes.
- Spatial apply reads only the authoritative collection, accepts unnamed-v1 and
  named-v2 vector shapes, rejects ambiguous/missing dense vectors, strips stored
  sparse vectors as an authority, and generates the correct v1/v2 replacements.
- Spatial full-payload replacement preserves intentional removal of stale spatial
  fields while per-point leases serialize it with concurrent collector/vision
  mutations.
- A page checkpoint advances after primary+journal durability, survives a pending
  follower repair, and never advances after primary or journal failure.
- `admin_batch` blocks and is blocked by convergence/primary-flip leases; its crash
  and recovery paths are deterministic.
- The payload-index ensure script performs no mutation without explicit `--apply`
  and exact schema/name validation, and refuses all dual/hybrid modes before I/O.
- Intelligence legacy indexer and dead GDELT collector refuse dual/hybrid mode before
  network I/O.
- Final AST inventory contains only approved adapter/admin mutations.

**Implementation**

- Add the vision projection Adapter and shared journal mount/protocol.
- Extract Qdrant transport from the spatial domain engine into the Intelligence-local
  journaled re-enrichment Adapter; retain its existing `ReenrichmentStore` Protocol,
  dry-run report, full replacement, and projection semantics.
- Implement the authoritative list/dict dense-vector normalization, shared
  projection contract, repair behavior, operation lease, and Intelligence mount.
- Guard the payload-index admin script with dry-run-by-default, explicit apply,
  collection allowlist/schema validation, and a dual/hybrid fail-closed check.
- Add explicit legacy guards and documentation.

**Gate**

- No active or manually reachable unguarded writer can bypass dual-write.

**Suggested commit:** `fix(qdrant): close payload and admin writer bypasses`

### Task 7 — Build the resumable migration CLI

**Tests first**

- All commands default to dry-run/read-only.
- Mutating commands require `--apply`, exact source/target, migration ID, schema
  digest, and interactive-independent confirmation token suitable for automation.
- Confirmation binds normalized source/target endpoint origins, collection names,
  migration ID, contract digest, and command; credentials are never printed or
  included in the token material.
- Reject an identical source/target `(normalized origin, collection)` tuple, aliases,
  unknown collection, nonempty wrong-schema target, wrong Qdrant minor, changed
  snapshot SHA, or changed contract digest.
- Backfill rejects a live-source endpoint or a restored source without the expected
  snapshot SHA/run marker. Reconcile rejects a disposable source when a live
  authority is required.
- Backfill checkpoint advances only after acknowledged batch.
- Restart resumes the same snapshot/contract and rejects a different one.
- Manifest detects missing, extra, payload-drift, dense-drift, sparse-coverage, and
  journal-pending cases.
- Bounded-memory manifest tests cover all 256 buckets, mixed integer/UUID IDs,
  interrupted external sort/resume, tampered bucket checksum, and zero raw payload or
  vector material in artifacts.

**Implementation**

Add `odin-qdrant-hybrid` subcommands:

```text
plan                 # read-only inventory/capacity/version report
snapshot-manifest    # inspect existing; --apply create/download/checksum; never delete
create-target        # exact empty odin_v2 schema and indexes
backfill             # restored-snapshot source -> target; resumable
reconcile            # live authoritative source -> follower
replay-delta         # journal high-water replay
validate             # full manifest/schema/search/resource report
repair               # drain recorded pending mutations
```

There is deliberately no `drop`, `delete-source`, or `prune-extra` command.

Use separate typed clients: `ReadOnlySnapshotSource`, `ReadOnlyLiveAuthority`, and
`TargetWriter`. The two source Interfaces expose only `get/scroll/count/query`; no
mutation method exists. Snapshot backfill reads an explicitly named restored
collection on the disposable Qdrant origin and writes `odin_v2` on the production
origin. Live reconciliation is the only command that reads the live authority, and
it still cannot write to that source client.

Backfill starts at batch 64 and one worker because the collection has one shard. It
halts on the first unclassified error, backs off on transient errors, and never
skips a point. Dense HNSW indexing is disabled only on the non-serving target and
restored to the captured setting after upload.

**Gate**

- A kill/restart integration test against Qdrant 1.13.2 completes with exact parity.

**Suggested commit:** `feat(data-ingestion): add resumable qdrant hybrid migrator`

### Task 8 — Implement native hybrid retrieval behind the Interface

**Tests first**

- Request-shape test asserts two prefetches, fixed vector names, equal limits,
  identical per-prefetch filters, unweighted RRF, no misleading top-level filter,
  no top-level score threshold, and payloads on.
- Assert query encoder—not document encoder—is called exactly once.
- Analysis and realtime filters cannot leak into the other lane.
- Plan-07B nested corpus/spatial filters are structurally identical on both
  prefetches; world/about/occurrence/either and partial/stale/no-hit cases never
  issue an unscoped retry. Typed canary fallback preserves the same filter on v1.
- Points without BM25 remain reachable through dense prefetch.
- Contract errors fail closed; only typed transient transport errors use explicit
  canary fallback.
- Lifecycle tests close Qdrant/FastEmbed resources and reset preflight state.
- Integration fixture proves an exact identifier recovered by BM25 and a semantic
  paraphrase recovered by dense are both present after RRF.

**Implementation**

- Implement dense-v1 and hybrid-v2 Adapters with `AsyncQdrantClient`.
- Move Qdrant request construction out of `retriever.py`.
- Remove the current warning-and-silent-dense behavior for enabled hybrid mode.
- Keep reranker, post-rerank tiering, lane validation, and graph context unchanged.
- Add HMAC-tokenized shadow metrics and typed fallback counters.

**Gate**

- All existing dense tests stay green; new hybrid integration passes on 1.13.2.

**Suggested commit:** `feat(intelligence): add qdrant native bm25 rrf retrieval`

### Task 9 — Freeze evaluation and operational observability

**Tests first**

- Evaluation fixture schema/duplicate-ID/query-slice validation.
- Metric computation golden tests for Recall, MRR, nDCG, latency, leakage, and
  fallback.
- Shadow logger test proves raw query/payload and plain query hashes are never logged;
  deterministic same-run and rotated-key HMAC behavior is covered.
- Alert tests for schema mismatch, encoder mismatch, pending repair age/count,
  backfill stall, optimizer error, disk/RAM threshold, and fallback rate.

**Implementation**

- Build and review the 160+ query set against fixed point IDs.
- Add dense-vs-hybrid replay and canonical JSON plus rendered Markdown output. Store
  the JSON SHA-256 and explicit reviewer/timestamp/commit sign-off fields; no
  unspecified cryptographic-signing system is introduced.
- Add the run-scoped HMAC secret setting with startup validation and redaction.
- Add Qdrant-stage, encoder, reranker, end-to-end, dual-write, repair, and resource
  metrics, including sparse emitted/omitted counts by fixed canonical lane and
  bounded omission reason (never raw source labels or lexical text).

**Gate**

- Offline pilot meets every section 12 quality/performance gate.

**Suggested commit:** `test(intelligence): add frozen hybrid retrieval evaluation`

### Task 10 — Rehearse the complete migration off production

**Procedure**

1. Run the read-only doctor/capacity preflight, then explicitly create/download a
   fresh `odin_intel` snapshot without modifying collection points or schema.
2. Verify SHA-256 and restore it at disposable-container startup with
   `--snapshot <mounted-file>:odin_intel` into an empty Qdrant 1.13.2 storage
   directory on a separate port. The target collection must be absent; never use
   `--force_snapshot`.
3. Create empty disposable `odin_v2` through the migration CLI and build it with the
   actual resumable backfill, including at least one forced process kill/resume.
   Copy every source ID, payload, and dense vector into the named representation and
   add `bm25` only to sparse-eligible prose. A prose-only or vectorless-padding
   shortcut is not an acceptance pilot because Qdrant 1.13 IDF uses total shard
   point count and the dense/hybrid performance profile must also be representative.
4. Run frozen relevance/performance evaluation.
5. Continue on that exact disposable schema to rehearse dual-write fault injection,
   a concurrent spatial replacement, admin/convergence lease exclusion, backfill
   stale-write races, full reconcile, journal delta replay, manifest validation,
   read cutover, writer primary reversal, and rollback.
6. Measure the final writer pause. It must remain within 20 minutes.
7. Destroy only the explicitly created disposable storage after retaining the
   report; never point cleanup at a workspace root or production volume.

**Gate**

- Checksummed, reviewer-approved rehearsal report contains exact versions, commands,
  durations, resource peaks, counts, hashes, evaluation metrics, injected failures,
  and rollback result.

**Suggested commit:** `docs(qdrant): record hybrid migration rehearsal`

### Task 11 — Execute production bootstrap and backfill

No code changes are made during this task.

1. Re-run read-only doctor/capacity report and compare to baseline. Stop if the
   separately reviewed D11 spatial promotion evidence is incomplete or stale.
2. Take safety snapshot S0, download it outside the Qdrant volume, SHA-256 it, and
   restore it using the rehearsed empty-storage startup procedure in a disposable
   1.13.2 instance.
3. Create/index empty `odin_v2`; verify exact schema and count zero.
4. Deploy all writer services and approved admin Adapters in `dual_v1_primary`; keep
   readers on `odin_intel`.
5. Exercise one preselected real/idempotently replayable point in every active
   lane—including a spatial replacement—and verify mirrored fingerprints/checkpoint
   behavior. Do not inject a live Qdrant outage (both collections share the same
   server) or insert synthetic production-only test IDs. Follower fault/repair was
   already proven against the same artifacts in the disposable rehearsal.
6. Take/download consistent baseline snapshot S1 after the dual-write barrier and
   restore it as `odin_intel` on the explicitly marked disposable same-minor origin.
7. Backfill from that read-only disposable origin into production `odin_v2`; monitor
   and throttle against live-read/resource gates.
8. Restore target optimizer settings and wait for green/OK plus stable
   segment/indexed-vector counters; do not invent an exact counter-equality gate.
9. Record `H0 = max(primary_commit_seq)`, reconcile live source, acquire the
   convergence lease, enter the bounded writer pause (including admin apply jobs),
   replay the post-H0 commit delta, drain repairs, and seal exact manifests.
10. Resume `dual_v1_primary`; do not enable hybrid reads yet.
11. Retain downloaded, checksummed S0/S1 and their restore reports through the full
    30-day rollback window. Removing server-side or external snapshot files is a
    separately confirmed retention action and is already budgeted in the disk
    ledger.

**Stop conditions**

- Any unexpected source schema/count regression, snapshot failure, journal
  durability failure, target red optimizer, disk below gate, OOM/sustained swap,
  unclassified backfill error, target extra ID, or parity failure.

Stopping leaves dense reads on `odin_intel`; it does not trigger target deletion.

### Task 12 — Shadow, cut over reads, then reverse the primary

1. Enable deterministic 10% run-scoped HMAC sampling while serving dense results.
2. Run for at least 24 hours plus controlled replay; complete the checksummed report
   and reviewer sign-off fields.
3. In one Intelligence deployment, set `QDRANT_COLLECTION=odin_v2` and
   `QDRANT_SCHEMA_MODE=hybrid_v2`, `ENABLE_HYBRID=true`; startup validates before
   health. Keep the explicit transient fallback to `odin_intel` available during
   this window.
4. Monitor 48 hours. Roll back reads immediately on any gate breach.
5. Switch backend read-only stats/scroll to the v2 schema only after its schema tests
   and parity check pass. Vision lookup remains on the v1 write authority.
6. Acquire the `primary_flip` lease, enter a short writer-only pause, drain the
   journal, deploy every writer and admin Adapter as `dual_v2_primary`, verify their
   preflights, switch vision/spatial authoritative lookup with that same deployment,
   and then resume/release the lease. A rolling interval with mixed authoritative
   collections is forbidden. Verify v1 follower parity before declaring the switch
   healthy. If any writer fails preflight, redeploy every writer in the prior mode
   while still paused; never resume a mixed set.
7. Retain reverse dual-write for at least 30 days. Daily, require schema/count/vector-
   coverage parity, zero unresolved journal rows, and a rotating stratified 10,000-
   point payload/dense fingerprint sample. Run the full streaming manifest weekly
   and immediately before any writer rollback or retirement decision, using the same
   rehearsed journal high-water and bounded writer barrier so live races are not
   reported as parity.
8. Mark TASK-104 Phase 2 complete while still in `dual_v2_primary`.
9. Open a separate retirement task for `hybrid_v2`, v1 archival, and any eventual
   deletion approval.

**Suggested commits:**

- `docs(qdrant): record hybrid read cutover`
- `docs(tasks): complete task 104 phase 2`

---

## 15. Verification commands

Run commands from the service directories as required by `AGENTS.md`.

### Data ingestion

```bash
cd services/data-ingestion
uv sync
uv run pytest
uv run ruff check .
```

The tracked `uv.lock` must be updated and `uv sync --locked` must pass in the Docker
build.

### Intelligence

```bash
cd services/intelligence
uv sync
uv run pytest
uv run ruff check .
```

### Vision enrichment

```bash
cd services/vision-enrichment
uv sync --extra dev
uv run pytest
```

### Backend, if config/schema files change

```bash
cd services/backend
uv sync
uv run pytest
uv run ruff check app/
uv run mypy app/
```

### Repository/containers

```bash
docker compose config
docker compose build data-ingestion intelligence vision-enrichment backend
./odin.sh smoke
```

Integration tests create only temporary, explicitly named Qdrant 1.13.2 containers
and `mktemp` storage directories. They must assert the target path before cleanup.
Production migration commands are not part of the default test suite and require the
explicit `--apply` contract.

---

## 16. Rollback matrix

| Failure point | Reader action | Writer action | Data action |
|---|---|---|---|
| Before target creation | none | stay `dense_v1` | none |
| Target creation/backfill | keep `odin_intel` | `dense_v1` or healthy `dual_v1_primary` | stop/resume target; never touch source vectors |
| Dual-write follower outage | keep `odin_intel` | keep v1 primary, repair journal | re-read current v1 points into v2 |
| Shadow failure | dense remains served | keep v1 primary dual | retain target for diagnosis |
| Hybrid read failure | set `QDRANT_COLLECTION=odin_intel`, `QDRANT_SCHEMA_MODE=dense_v1`, `ENABLE_HYBRID=false` together | keep dual v1 primary | no restore needed |
| After v2 becomes writer primary | point readers back only after v1 parity check | writer-only pause; if v1 lags reconcile v2→v1, then deploy all as `dual_v1_primary` before resume | keep both collections |
| Source corruption (last resort) | isolate affected collection | stop all writers | restore verified same-minor snapshot into a new name; never overwrite active collection casually |

Snapshot restoration is disaster recovery, not routine feature rollback. Routine
rollback is a mode/config change because both collections remain current.

Read rollback is complete only when:

- Intelligence health validates the Phase 1 schema.
- A known dense query returns expected IDs.
- Corpus-policy and graph-context smoke tests pass.
- Writer state and journal show which collection is authoritative.

---

## 17. Risk register

| Risk | Prevention | Detection | Recovery |
|---|---|---|---|
| Accidental source schema mutation | no runtime create/update-schema; exact allowlist | schema doctor before/after every phase | abort; source snapshot available |
| Incomplete Plan 07B/index/re-enrichment/coverage work gets hidden inside hybrid migration | D11 makes the full spatial promotion a separate prerequisite; hybrid preflight is read-only | contract revision, exact nine-present/ten-missing baseline diff, dry-run approval, coverage and stale checks | stop before snapshot/target work; complete the spatial runbook separately |
| Disk/RAM exhaustion from second collection/restored snapshot | hard capacity gates, on-disk sparse, throttled one-shard upload | disk, RSS, swap, optimizer metrics | pause backfill; keep v1 serving |
| Tokenizer drift between write/query | exact pins, JSON contract, cross-service golden tests | encoder revision/hash at startup and payload | rebuild non-serving target sparse vectors |
| Query encoded with document method | separate Interface methods and call assertions | golden/integration exact-ID failure | fix before cutover; v1 still serving |
| Partial dual-write | awaited follower plus durable journal | pending count/age and fingerprint checks | repair from latest authoritative point |
| Stale snapshot overwrites newer target point | v2 not serving during load; full live reconcile and journal high-water replay | exact manifest/fingerprint mismatch | replay current authoritative point |
| Migrator points a mutating client at the snapshot source or wrong origin | role-restricted clients plus endpoint/name/SHA-bound confirmation token | preflight/typed-interface test | abort before I/O; credentials/token never authorize another origin |
| Dedup suppresses follower repair | `contains_authoritative` calls `ensure_mirrored` in dual mode | missing follower integration test/metric | repair worker/full reconcile |
| Filter leakage between dense/sparse lanes | same filter on both prefetches; do not rely on Fusion top-level filtering; post-validation retained | zero-tolerance lane tests/eval | read rollback |
| Dense threshold misapplied to BM25/RRF | typed `dense_threshold`, no fused threshold | request-shape tests | fix before cutover |
| Common-term BM25 noise | bounded text, no raw-score mixing, TEI reranker, negative eval slice | false-positive/noise metrics | do not cut over |
| IDF is global to all one-shard points rather than the filtered prose lane on 1.13 | full-copy decision pilot and frozen evaluation; no false claim of filter-scoped IDF | per-slice quality report on final-like point count | do not cut over; evaluate separate RAG collection or later Qdrant capability in a new design |
| English stemming harms multilingual identifiers | stemming and stopwords disabled | multilingual golden/eval slices | new encoder revision/target rebuild, not live tweak |
| FastEmbed runtime network dependency | model assets baked and offline smoke tested | startup health | rebuild image; dense remains active |
| Hidden writer bypass | AST mutation inventory and legacy guards | CI failure, journal/source delta anomalies | stop offending writer and reconcile |
| Vision patch divergence | authoritative lookup + journaled full-point reprojection | vision contract test/pending metrics | replay current point |
| Spatial full-point replacement copies the wrong vector shape or clobbers a newer payload | authoritative list/dict normalization, derived sparse recomputation, shared per-point lease | cross-mode contract/race tests and manifest drift | stop batch; repair latest authoritative points through the Adapter |
| Spatial/admin batch crosses convergence or primary reversal | mutually exclusive renewable operation leases and explicit writer inventory | lease/preflight failure and barrier audit | abort barrier, retain v1 reads, reconcile after the batch is closed |
| Qdrant-doc examples from newer versions copied into code | verification matrix and exact dependency pins | request model/version tests | reject review/change |
| Alias switches schema without application mode | no alias cutover | alias doctor reports unexpected aliases | remove unexpected alias only via reviewed admin action |
| Spatial contract regresses during hybrid refactor | committed `48a72e5`/`12a7791` baseline, Protocol preservation, and writer re-audit | existing spatial contract/report tests plus hybrid Adapter tests | stop/rebase; restore transport compatibility without changing projection semantics |

---

## 18. Review checklist designed to avoid follow-up loops

A reviewer should be able to answer every item without making a new architecture
choice:

- [ ] New collection rather than in-place mutation accepted.
- [ ] Exact Qdrant/client/FastEmbed versions accepted.
- [ ] Client-side encoder plus Qdrant-side IDF/index/fusion terminology accepted.
- [ ] Exact encoder settings and multilingual no-stemming decision accepted.
- [ ] Sparse eligibility and every lexical field mapping accepted.
- [ ] Plan-07B ordering and separate spatial-promotion prerequisite accepted.
- [ ] Every active point/payload writer is classified.
- [ ] Spatial full-replacement vector normalization, checkpoint boundary, and
  admin/barrier lease behavior accepted.
- [ ] Four-state writer transition and authoritative collection per phase accepted.
- [ ] Durable journal path/protocol and failure semantics accepted.
- [ ] Backfill source, checkpoint, stale-write convergence, and maintenance budget
  accepted.
- [ ] Exact schema, payload/dense/sparse parity gates accepted.
- [ ] Frozen query slices and numerical go/no-go thresholds accepted.
- [ ] Unweighted RRF and score-threshold semantics accepted.
- [ ] Identical nested corpus/spatial filters on both prefetches and fallback accepted.
- [ ] Shadow logging/privacy and fallback behavior accepted.
- [ ] Snapshot/restore drill, capacity gates, stop conditions, and rollback matrix
  accepted.
- [ ] Thirty-day reverse dual-write and separate deletion task accepted.
- [ ] No task contains an implicit server upgrade, dense re-embedding, source
  deletion, or legacy collector activation.

Any requested change to a locked item above is a deliberate design change to this
plan, not an implementation detail to improvise during review.

---

## 19. Definition of done

TASK-104 Phase 2 is complete when all of the following are true:

1. `odin_v2` serves named dense plus native-Qdrant BM25/RRF hybrid retrieval on
   Qdrant 1.13.2 while preserving Plan-07B pinned spatial scope with zero unscoped
   retry.
2. All source IDs/payloads/dense vectors are proven present and equivalent; sparse
   coverage exactly matches the lexical contract.
3. Frozen evaluation and operational gates pass and reports are archived.
4. Every active or operator-reachable writer—including vision and spatial
   re-enrichment—uses the durable contract, and v2 is authoritative with v1 as an
   awaited, validated follower.
5. Hybrid read rollback and writer-primary rollback have both been rehearsed.
6. Production has remained healthy for 48 hours after read cutover and completed the
   full 30-day reverse dual-write window with its daily/weekly parity gates.
7. Documentation, architecture decisions, runbooks, container status, and `TASKS.md`
   reflect observed—not anticipated—state.
8. `odin_intel` still exists. Its eventual retirement/deletion has a separate task,
   snapshot, retention decision, and explicit approval.
