# NotebookLM → ODIN Knowledge Ingestion Pipeline — Design Spec

> Date: 2026-04-03 | Status: Approved | Author: RT + Claude

---

## Overview

Automated pipeline for ingesting NotebookLM artifacts (primarily audio podcasts) into ODIN's Neo4j Knowledge Graph. Audio is transcribed via Voxtral, entities/claims are extracted via Qwen + Claude hybrid, and structured data is written into the existing WorldView graph.

**Source focus:** RAND Corporation, CSIS, military intelligence, geopolitical analyses.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Voxtral deployment | vLLM as second service (port 8010) | Parallel to Qwen, OpenAI-compatible API |
| Entity extraction | Hybrid: Qwen local + Claude for low-confidence | Cost-effective, quality where it matters |
| Neo4j graph | Same graph as WorldView/OSINT | Cross-referencing is the core value |
| Slides | Not in MVP | Audio is the primary content source |
| NotebookLM auth | Manual trigger, no cron | Cookie-auth is fragile, 20-100 notebooks manageable |
| Architecture | Modular CLI pipeline | Phases independently retryable, testable |

---

## Section 1: Project Structure & Integration

The pipeline lives as a new module under the existing `data-ingestion` service:

```
services/data-ingestion/
├── config.py                  # Existing — extended with Voxtral/NLM settings
├── pipeline.py                # Existing — OSINT extraction
├── feeds/                     # Existing — RSS, GDELT, TLE, Hotspots
├── notebooklm/                # NEW
│   ├── __init__.py
│   ├── cli.py                 # Click CLI (odin-ingest-nlm)
│   ├── state.py               # SQLite-based status tracker
│   ├── export.py              # Phase 1: NotebookLM export
│   ├── transcribe.py          # Phase 2: Voxtral vLLM transcription
│   ├── extract.py             # Phase 3: Qwen + Claude hybrid extraction
│   ├── ingest_neo4j.py        # Phase 4: Neo4j ingestion via write templates
│   ├── write_templates.py     # Pinned copy of stable templates + NLM-specific
│   ├── prompts/
│   │   └── extraction_v1.txt  # Versioned extraction prompt
│   └── schemas.py             # Pydantic models
├── pyproject.toml             # Extended with new dependencies
└── tests/
    └── test_notebooklm.py     # NEW
```

### Data Storage (outside repo)

```
/home/deadpool-ultra/ODIN/odin-data/notebooklm/
├── notebooks/       # Raw exports per notebook ID (audio, metadata)
├── transcripts/     # Voxtral output (JSON)
├── extractions/     # LLM extraction output (JSON)
└── state.db         # SQLite status tracker
```

Mounted as Docker volume. Entirely outside the git repo — no .gitignore needed.

### Write Templates

`data-ingestion` cannot import from `services/intelligence/` (separate Docker build context). Stable templates (`UPSERT_ENTITY`, `UPSERT_DOCUMENT`, `LINK_EVENT_SOURCE`) are explicitly pinned in `notebooklm/write_templates.py`. New templates only for `Claim` nodes and provenance relations.

---

## Section 2: Voxtral vLLM Service

### Docker Compose Addition

```yaml
vllm-voxtral:
  image: vllm/vllm-omni:v0.18.0          # Fixed tag, no :latest
  profiles: ["notebooklm"]                 # Own profile, only for NLM runs
  ports:
    - "8010:8000"
  volumes:
    - ${VOXTRAL_MODEL_PATH:-/home/deadpool-ultra/Voxtral/model}:/models/voxtral:ro
  command: >
    --model /models/voxtral
    --served-model-name voxtral
    --tokenizer_mode mistral
    --config_format mistral
    --load_format mistral
    --gpu-memory-utilization 0.25
    --enforce-eager
    --port 8000
  networks:
    default:
      aliases:
        - vllm-voxtral
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 30s
    timeout: 10s
    retries: 10
    start_period: 120s
  restart: unless-stopped
```

### Key Points

- **No `--enable-chunked-prefill false`** — version-dependent instability, omitted until proven necessary.
- **Port mapping:** Container-internal 8000, external **8010**. No alias conflict with `vllm` (Qwen on 8000).
- **VRAM:** ~9.5 GB (bf16). Qwen (0.55 * 32GB ≈ 18GB) + Voxtral (0.25 * 32GB ≈ 8GB) = ~26GB total on RTX 5090 (32GB).
- **`VOXTRAL_MODEL_PATH`** documented in `.env.example`.

### Config Extension

```python
# In config.py
voxtral_url: str = "http://vllm-voxtral:8000"
voxtral_model: str = "voxtral"
```

### Healthcheck

CLI command `odin-ingest-nlm healthcheck` fires a real audio request:
- Primary: `POST /v1/audio/transcriptions`
- Fallback: `POST /v1/chat/completions` with AudioChunk
- Uses a short bundled test WAV

### Fallback Dockerfile

```dockerfile
# Dockerfile.voxtral — if vllm/vllm-omni:v0.18.0 has issues
FROM vllm/vllm-openai:v0.18.0
RUN pip install "vllm[audio]"
```

### odin.sh Integration

```bash
odin nlm up        # docker compose --profile notebooklm up -d vllm-voxtral
odin nlm down      # docker compose stop vllm-voxtral && docker compose rm -f vllm-voxtral
odin nlm smoke     # odin-ingest-nlm healthcheck
odin nlm run       # odin-ingest-nlm run
odin nlm status    # odin-ingest-nlm status
```

`odin nlm down` uses `stop` + `rm -f` instead of `docker compose down` to avoid tearing down the entire stack.

---

## Section 3: Pipeline Phases

### Phase 1: NotebookLM Export (`export.py`)

```python
# Manual trigger: odin-ingest-nlm export
# Uses notebooklm-py (cookie-auth, manual login beforehand)

async def export_all(client: NotebookLMClient, data_dir: Path):
    notebooks = await client.notebooks.list()
    for nb in notebooks:
        nb_dir = data_dir / "notebooks" / nb.id
        nb_dir.mkdir(parents=True, exist_ok=True)
        # 1. Metadata (JSON)
        # 2. Audio download (podcast.mp3) — primary source
        # 3. Mind-map (mindmap.json) — structured data if available
        # State update: phase=export, status=completed
```

No slides download (MVP decision). New dependencies: `notebooklm-py[browser]`, `playwright`.

### Phase 2: Transcription (`transcribe.py`)

**Audio chunking before transcription:** Long podcasts (>10 min) are split into chunks via pydub/ffmpeg to reduce timeouts and VRAM spikes.

```python
async def transcribe(notebook_id: str, audio_path: Path, client: httpx.AsyncClient) -> Transcript:
    chunk_minutes = 10
    chunks = split_audio(audio_path, max_minutes=chunk_minutes)
    chunk_duration_sec = chunk_minutes * 60
    segments = []
    for i, chunk in enumerate(chunks):
        result = await transcribe_chunk(chunk, client)
        offset = i * chunk_duration_sec
        for seg in result.segments:
            seg.start += offset
            seg.end += offset
        segments.extend(result.segments)
    return Transcript(
        notebook_id=notebook_id,
        segments=segments,
        full_text=" ".join(s.text for s in segments),
        duration_seconds=get_original_duration(audio_path),  # From original file
        language=majority_language(chunks),  # Majority vote across chunks
    )
```

**Endpoint:** Primary `POST /v1/audio/transcriptions`, fallback `POST /v1/chat/completions` with AudioChunk.

### Phase 3: Entity & Claim Extraction (`extract.py`)

**Hybrid approach:** Qwen3.5-27B local (bulk) → Claude API (low-confidence review).

```python
# Step 1: Qwen extraction (local, http://vllm:8000)
async def extract_with_qwen(transcript: Transcript, metadata: dict) -> Extraction:
    # System prompt based on existing pipeline.py pattern,
    # extended with Claims + geopolitical focus
    # Confidence threshold: >= 0.7 → accept directly

# Step 2: Claude review (low-confidence only, cost-controlled)
CLAUDE_BUDGET_PER_RUN = 50_000  # Max input tokens per run

async def review_with_claude(extraction: Extraction, transcript: Transcript):
    low_confidence = [item for item in all_items if item.confidence < 0.7]
    token_budget = CLAUDE_BUDGET_PER_RUN
    for item in low_confidence:
        context_window = extract_context(transcript.full_text, item, radius=500)
        estimated_tokens = len(context_window) // 4
        if token_budget - estimated_tokens < 0:
            break  # Budget exhausted
        token_budget -= estimated_tokens
        # Review request to Claude with context window only, not full transcript
```

**Extraction prompt** versioned as separate file (`prompts/extraction_v1.txt`), tracked in provenance.

### Phase 4: Neo4j Ingestion (`ingest_neo4j.py`)

**Execution order per notebook:**
1. Upsert Source with quality tier
2. Upsert Document with `notebook_id` as merge key
3. Link Document → Source (`FROM_SOURCE`)
4. Upsert Entities
5. Upsert Claims with provenance
6. Link Claims → Entities, Claims → Document

**Write Templates (new, NLM-specific):**

```python
UPSERT_DOCUMENT = """
MERGE (d:Document {notebook_id: $notebook_id})
SET d.title = $title, d.source = $source, d.type = $type,
    d.updated_at = datetime()
"""

UPSERT_SOURCE_WITH_TIER = """
MERGE (s:Source {name: $source_name})
SET s.quality_tier = $quality_tier, s.updated_at = datetime()
"""

LINK_DOCUMENT_SOURCE = """
MATCH (d:Document {notebook_id: $notebook_id})
MATCH (s:Source {name: $source_name})
MERGE (d)-[:FROM_SOURCE]->(s)
"""

UPSERT_CLAIM = """
MERGE (c:Claim {statement_hash: $statement_hash})
ON CREATE SET
    c.statement = $statement,
    c.type = $type,
    c.polarity = $polarity,
    c.confidence = $confidence,
    c.temporal_scope = $temporal_scope,
    c.extracted_at = datetime(),
    c.extraction_model = $model,
    c.prompt_version = $prompt_version
ON MATCH SET
    c.confidence = CASE WHEN $confidence > c.confidence THEN $confidence ELSE c.confidence END,
    c.last_seen_at = datetime()
"""

LINK_CLAIM_DOCUMENT = """
MATCH (c:Claim {statement_hash: $statement_hash})
MATCH (d:Document {notebook_id: $notebook_id})
MERGE (c)-[:EXTRACTED_FROM]->(d)
"""

LINK_CLAIM_ENTITY = """
MATCH (c:Claim {statement_hash: $statement_hash})
MATCH (e:Entity {name: $entity_name})
MERGE (c)-[:INVOLVES]->(e)
"""
```

**Source quality tiers:**

```python
SOURCE_TIERS = {
    "RAND": "tier_1",
    "CSIS": "tier_1",
    "Brookings": "tier_1",
    "CNA": "tier_2",
    "IISS": "tier_2",
    # Default: "tier_3"
}
```

---

## Section 4: Schemas

### Pydantic Models (`schemas.py`)

```python
from pydantic import BaseModel
from typing import Literal

# --- Types as Literals (no schema drift) ---

EntityType = Literal[
    "ORGANIZATION", "COUNTRY", "PERSON", "REGION",
    "WEAPON_SYSTEM", "MILITARY_UNIT", "POLICY",
    "TREATY", "CONCEPT", "VESSEL", "AIRCRAFT", "SATELLITE"
]

RelationType = Literal[
    "ALLIED_WITH", "COMPETES_WITH", "SANCTIONS",
    "SUPPLIES_TO", "OPERATES_IN", "MEMBER_OF",
    "COMMANDS", "TARGETS", "NEGOTIATES_WITH"
]

ClaimType = Literal["factual", "assessment", "prediction"]
ClaimPolarity = Literal["positive", "negative", "neutral"]

# --- Transcript ---

class TranscriptSegment(BaseModel):
    start: float
    end: float
    speaker: str | None = None
    text: str

class Transcript(BaseModel):
    notebook_id: str
    duration_seconds: float
    language: str
    segments: list[TranscriptSegment]
    full_text: str

# --- Extraction ---

class Entity(BaseModel):
    name: str
    type: EntityType
    aliases: list[str] = []
    confidence: float

class Relation(BaseModel):
    source: str
    target: str
    type: RelationType
    evidence: str
    confidence: float

class Claim(BaseModel):
    statement: str
    type: ClaimType
    polarity: ClaimPolarity
    entities_involved: list[str]
    confidence: float
    temporal_scope: str

class Extraction(BaseModel):
    notebook_id: str
    entities: list[Entity]
    relations: list[Relation]
    claims: list[Claim]
    extraction_model: str
    prompt_version: str
```

### Claim Dedup

```python
import hashlib
import re
import unicodedata

def claim_hash(statement: str) -> str:
    normalized = unicodedata.normalize("NFKC", statement)
    normalized = re.sub(r'\s+', ' ', normalized.lower().strip())
    normalized = re.sub(r'[^\w\s]', '', normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:24]
```

24 hex chars (96 bits) — collision-safe for this scale.

---

## Section 5: SQLite State Schema

```sql
CREATE TABLE notebooks (
    id TEXT PRIMARY KEY,
    title TEXT,
    source_name TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE phase_status (
    notebook_id TEXT REFERENCES notebooks(id),
    phase TEXT CHECK(phase IN ('export', 'transcribe', 'extract', 'ingest')),
    status TEXT CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    retry_count INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (notebook_id, phase)
);
```

### Phase Gating

```python
PHASE_ORDER = ['export', 'transcribe', 'extract', 'ingest']

def validate_retry(notebook_id: str, phase: str, db: sqlite3.Connection):
    idx = PHASE_ORDER.index(phase)
    for prev_phase in PHASE_ORDER[:idx]:
        status = get_phase_status(db, notebook_id, prev_phase)
        if status != 'completed':
            raise click.UsageError(
                f"Cannot retry '{phase}': prerequisite '{prev_phase}' is '{status}'"
            )
```

### Atomic Retry

```sql
UPDATE phase_status
SET status = 'running',
    retry_count = retry_count + 1,
    started_at = datetime('now'),
    updated_at = datetime('now')
WHERE notebook_id = ? AND phase = ? AND status = 'failed';
```

Single transaction — no race condition. Guard on `status = 'failed'` prevents accidentally re-running completed phases. If zero rows affected, CLI reports "nothing to retry".

---

## Section 6: CLI

```
odin-ingest-nlm export                     # Phase 1
odin-ingest-nlm transcribe [--id ID]       # Phase 2
odin-ingest-nlm extract [--id ID]          # Phase 3
odin-ingest-nlm ingest [--id ID]           # Phase 4
odin-ingest-nlm run [--id ID]              # All phases sequentially
odin-ingest-nlm status                     # Matrix: Notebook x Phase x Status
odin-ingest-nlm healthcheck                # Voxtral audio smoke test
odin-ingest-nlm retry --id ID --phase P    # Retry failed phase (with gating)
```

Without `--id`: processes all notebooks that are `pending` or `failed` for the respective phase.

### Status Output

```
Notebook                    export    transcribe  extract   ingest
─────────────────────────────────────────────────────────────────────
RAND Taiwan Assessment      done      done        done      done
CSIS China Sea Analysis     done      done        FAILED    -
Brookings NATO Outlook      done      running     -         -
```

---

## Section 7: Cross-Referencing Queries

Read-only Cypher queries. No LLM-generated Cypher on write path (Two-Loop Architecture preserved).

### Contradicting Claims

```cypher
MATCH (c1:Claim)-[:INVOLVES]->(e:Entity)<-[:INVOLVES]-(c2:Claim)
WHERE c1 <> c2
  AND c1.type = 'assessment' AND c2.type = 'assessment'
  AND c1.temporal_scope = c2.temporal_scope
  AND c1.polarity <> c2.polarity
  AND c1.polarity <> 'neutral' AND c2.polarity <> 'neutral'
WITH c1, c2, e
MATCH (c1)-[:EXTRACTED_FROM]->(d1:Document)-[:FROM_SOURCE]->(s1:Source)
MATCH (c2)-[:EXTRACTED_FROM]->(d2:Document)-[:FROM_SOURCE]->(s2:Source)
WHERE d1 <> d2
RETURN e.name AS entity,
       c1.statement AS claim_1, s1.name AS source_1, c1.confidence AS conf1,
       c2.statement AS claim_2, s2.name AS source_2, c2.confidence AS conf2
ORDER BY abs(c1.confidence - c2.confidence) DESC
```

### Source-Weighted Confidence

```cypher
MATCH (c:Claim)-[:EXTRACTED_FROM]->(d:Document)-[:FROM_SOURCE]->(s:Source)
WITH c, s,
     CASE s.quality_tier
       WHEN 'tier_1' THEN c.confidence * 1.0
       WHEN 'tier_2' THEN c.confidence * 0.8
       ELSE c.confidence * 0.5
     END AS weighted_confidence
RETURN c.statement, collect(s.name) AS sources,
       avg(weighted_confidence) AS aggregated_confidence
ORDER BY aggregated_confidence DESC
```

### Entity Coverage Across Sources

```cypher
MATCH (e:Entity)<-[:INVOLVES]-(c:Claim)-[:EXTRACTED_FROM]->(d:Document)
      -[:FROM_SOURCE]->(s:Source)
WITH e, collect(DISTINCT s.name) AS sources, count(c) AS claim_count
WHERE size(sources) >= 2
RETURN e.name, e.type, sources, claim_count
ORDER BY claim_count DESC
```

Perspective: Munin (LangGraph Agent) can use these queries as tools for automated analysis.

---

## Dependencies (additions to pyproject.toml)

```toml
[project.optional-dependencies]
notebooklm = [
    "notebooklm-py[browser]",
    "playwright",
    "click>=8.0",
    "anthropic>=0.40",       # Claude API for hybrid extraction
    "pydub>=0.25",           # Audio chunking
]

[project.scripts]
odin-ingest-nlm = "notebooklm.cli:cli"

[tool.hatch.build.targets.wheel]
include = ["*.py", "feeds/**/*.py", "notebooklm/**/*.py", "notebooklm/prompts/*.txt"]
```

> **Note:** The existing `[tool.hatch.build.targets.wheel]` in pyproject.toml must be extended
> to include `notebooklm/**/*.py` and `notebooklm/prompts/*.txt`. The `[project.scripts]` entry
> wires up the CLI entrypoint.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `notebooklm-py` cookie-auth breaks | Export stops | Manual re-login, CLI shows clear error |
| Google changes internal API | Export broken | Apify fallback, community fixes |
| Voxtral hallucinations on jargon | Wrong entities in graph | Confidence threshold + Claude review |
| Extraction LLM invents relations | Poison in knowledge graph | Confidence threshold + human review for low-confidence |
| Duplicate entities (spelling variants) | Graph pollution | Entity resolution layer (fuzzy matching + LLM disambiguation) — future phase |
| vllm-omni image incompatibility | Voxtral won't start | Fallback Dockerfile with vllm[audio] |
| VRAM contention (Qwen + Voxtral) | OOM | Separate profiles, manual trigger, not concurrent |

---

## Review Findings (2026-04-03)

Four issues identified during pre-implementation review. All resolved inline in this spec.

| # | Severity | Finding | Fix applied |
|---|----------|---------|-------------|
| 1 | **HIGH** | `UPSERT_CLAIM` MERGE + SET overwrites `confidence`, `type`, `temporal_scope`, `extraction_model` on re-encounter of same claim | Changed to `ON CREATE SET` (full init) + `ON MATCH SET` (only upgrade confidence if higher, update `last_seen_at`). Immutable fields preserved. |
| 2 | **MEDIUM** | `Transcript` schema requires `notebook_id`, but `transcribe()` signature and return don't provide it | Added `notebook_id: str` parameter to `transcribe()` and passed it into `Transcript(...)` constructor. |
| 3 | **MEDIUM** | Retry SQL has no guard on `status='failed'` — can accidentally re-run completed phases | Added `AND status = 'failed'` WHERE clause. Zero-row update → CLI reports "nothing to retry". |
| 4 | **MEDIUM** | `pyproject.toml` missing `[project.scripts]` entry for `odin-ingest-nlm` and wheel include doesn't cover `notebooklm/` | Documented required additions: `[project.scripts]` entrypoint + extended `[tool.hatch.build.targets.wheel]` include pattern. |
