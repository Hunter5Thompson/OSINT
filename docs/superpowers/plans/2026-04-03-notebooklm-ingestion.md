# NotebookLM → ODIN Knowledge Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 4-phase CLI pipeline that exports NotebookLM podcasts, transcribes audio via Voxtral, extracts entities/claims via hybrid Qwen+Claude, and ingests structured data into the ODIN Neo4j Knowledge Graph.

**Architecture:** Modular CLI (`odin-ingest-nlm`) under `services/data-ingestion/notebooklm/`. Each phase is independently retryable, tracked by SQLite state DB. Audio transcription via Voxtral on vLLM (port 8010). Entity/claim extraction via Qwen (local) with Claude API fallback for low-confidence items. Neo4j ingestion uses pinned write templates with `ON CREATE`/`ON MATCH` semantics.

**Tech Stack:** Python 3.12, Click, Pydantic v2, httpx, pydub, anthropic SDK, SQLite, Neo4j HTTP API, vLLM (Voxtral + Qwen), pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-04-03-notebooklm-odin-ingestion-design.md`

**Base path:** `services/data-ingestion/` (all paths relative unless prefixed with `~/`)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `notebooklm/__init__.py` | Package marker |
| Create | `notebooklm/schemas.py` | Pydantic models + `claim_hash()` |
| Create | `notebooklm/state.py` | SQLite state tracker + phase gating |
| Create | `notebooklm/write_templates.py` | Pinned Neo4j Cypher templates |
| Create | `notebooklm/transcribe.py` | Phase 2: audio chunking + Voxtral |
| Create | `notebooklm/extract.py` | Phase 3: hybrid Qwen + Claude extraction |
| Create | `notebooklm/ingest_neo4j.py` | Phase 4: Neo4j batch write |
| Create | `notebooklm/export.py` | Phase 1: NotebookLM client export |
| Create | `notebooklm/cli.py` | Click CLI wiring all phases |
| Create | `notebooklm/prompts/extraction_v1.txt` | Versioned extraction prompt |
| Create | `tests/test_nlm_schemas.py` | Schema + claim_hash tests |
| Create | `tests/test_nlm_state.py` | State tracker tests |
| Create | `tests/test_nlm_transcribe.py` | Transcription tests |
| Create | `tests/test_nlm_extract.py` | Extraction tests |
| Create | `tests/test_nlm_ingest.py` | Neo4j ingestion tests |
| Create | `tests/test_nlm_cli.py` | CLI integration tests |
| Modify | `config.py:13` | Add `voxtral_url`, `voxtral_model`, `nlm_data_dir` |
| Modify | `docker-compose.yml` | Add `vllm-voxtral` service |
| Modify | `~/ODIN/OSINT/odin.sh` | Add `nlm` subcommands |

---

## Task 1: Pydantic Schemas + claim_hash

**Files:**
- Create: `notebooklm/__init__.py`
- Create: `notebooklm/schemas.py`
- Create: `tests/test_nlm_schemas.py`

This is the foundation — every other module imports from here.

- [ ] **Step 1: Write failing tests for schemas**

```python
# tests/test_nlm_schemas.py
import pytest
from notebooklm.schemas import (
    TranscriptSegment, Transcript, Entity, Relation, Claim,
    Extraction, claim_hash,
)


class TestTranscriptSegment:
    def test_basic(self):
        seg = TranscriptSegment(start=0.0, end=5.3, text="Hello world")
        assert seg.speaker is None
        assert seg.text == "Hello world"

    def test_with_speaker(self):
        seg = TranscriptSegment(start=0.0, end=5.3, speaker="Host", text="Hello")
        assert seg.speaker == "Host"


class TestTranscript:
    def test_requires_notebook_id(self):
        t = Transcript(
            notebook_id="abc123",
            duration_seconds=600.0,
            language="en",
            segments=[],
            full_text="",
        )
        assert t.notebook_id == "abc123"

    def test_missing_notebook_id_raises(self):
        with pytest.raises(Exception):
            Transcript(
                duration_seconds=600.0,
                language="en",
                segments=[],
                full_text="",
            )


class TestEntity:
    def test_valid_type(self):
        e = Entity(name="NATO", type="ORGANIZATION", confidence=0.9)
        assert e.aliases == []

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            Entity(name="NATO", type="INVALID_TYPE", confidence=0.9)


class TestRelation:
    def test_basic(self):
        r = Relation(
            source="USA", target="China",
            type="COMPETES_WITH",
            evidence="trade tensions",
            confidence=0.85,
        )
        assert r.type == "COMPETES_WITH"

    def test_invalid_relation_type_raises(self):
        with pytest.raises(Exception):
            Relation(
                source="A", target="B",
                type="LOVES",
                evidence="x",
                confidence=0.5,
            )


class TestClaim:
    def test_basic(self):
        c = Claim(
            statement="China will invade Taiwan by 2027",
            type="prediction",
            polarity="negative",
            entities_involved=["China", "Taiwan"],
            confidence=0.6,
            temporal_scope="2027",
        )
        assert c.type == "prediction"

    def test_invalid_claim_type_raises(self):
        with pytest.raises(Exception):
            Claim(
                statement="x", type="opinion", polarity="neutral",
                entities_involved=[], confidence=0.5, temporal_scope="",
            )


class TestExtraction:
    def test_basic(self):
        ext = Extraction(
            notebook_id="nb1",
            entities=[],
            relations=[],
            claims=[],
            extraction_model="qwen3.5",
            prompt_version="v1",
        )
        assert ext.extraction_model == "qwen3.5"


class TestClaimHash:
    def test_deterministic(self):
        h1 = claim_hash("China will invade Taiwan by 2027")
        h2 = claim_hash("China will invade Taiwan by 2027")
        assert h1 == h2

    def test_length_24_hex(self):
        h = claim_hash("test statement")
        assert len(h) == 24
        assert all(c in "0123456789abcdef" for c in h)

    def test_case_insensitive(self):
        h1 = claim_hash("NATO expands eastward")
        h2 = claim_hash("nato expands eastward")
        assert h1 == h2

    def test_whitespace_normalized(self):
        h1 = claim_hash("China   will  invade")
        h2 = claim_hash("China will invade")
        assert h1 == h2

    def test_punctuation_ignored(self):
        h1 = claim_hash("China will invade Taiwan.")
        h2 = claim_hash("China will invade Taiwan")
        assert h1 == h2

    def test_unicode_normalized(self):
        # NFKC: ﬁ → fi
        h1 = claim_hash("deﬁnition")
        h2 = claim_hash("definition")
        assert h1 == h2

    def test_different_statements_differ(self):
        h1 = claim_hash("China invades Taiwan")
        h2 = claim_hash("Russia invades Ukraine")
        assert h1 != h2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebooklm'`

- [ ] **Step 3: Create package and implement schemas**

```python
# notebooklm/__init__.py
```

```python
# notebooklm/schemas.py
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel

# --- Constrained types ---

EntityType = Literal[
    "ORGANIZATION", "COUNTRY", "PERSON", "REGION",
    "WEAPON_SYSTEM", "MILITARY_UNIT", "POLICY",
    "TREATY", "CONCEPT", "VESSEL", "AIRCRAFT", "SATELLITE",
]

RelationType = Literal[
    "ALLIED_WITH", "COMPETES_WITH", "SANCTIONS",
    "SUPPLIES_TO", "OPERATES_IN", "MEMBER_OF",
    "COMMANDS", "TARGETS", "NEGOTIATES_WITH",
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


# --- Utilities ---

def claim_hash(statement: str) -> str:
    """Deterministic 24-hex-char hash for claim dedup. Case/whitespace/punctuation insensitive."""
    normalized = unicodedata.normalize("NFKC", statement)
    normalized = re.sub(r"\s+", " ", normalized.lower().strip())
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:24]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_schemas.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/__init__.py \
       services/data-ingestion/notebooklm/schemas.py \
       services/data-ingestion/tests/test_nlm_schemas.py
git commit -m "feat(data-ingestion): add NotebookLM schemas + claim_hash"
```

---

## Task 2: Config Extension

**Files:**
- Modify: `config.py:13` (after last field)

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_nlm_schemas.py (or inline check — config is simple)
# We verify the new fields exist with correct defaults.
```

Actually — config is a 2-line change with Pydantic defaults. No dedicated test needed; the existing `Settings()` instantiation in all downstream tests will validate it.

- [ ] **Step 2: Add fields to config.py**

Add after the last existing field in `Settings`:

```python
    # NotebookLM / Voxtral
    voxtral_url: str = "http://localhost:8010/v1"
    voxtral_model: str = "voxtral"
    nlm_data_dir: str = "/home/deadpool-ultra/ODIN/odin-data/notebooklm"
    claude_model: str = "claude-sonnet-4-20250514"
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest -x -q`
Expected: All existing tests PASS (new fields have defaults, no breakage)

- [ ] **Step 4: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/config.py
git commit -m "feat(data-ingestion): add Voxtral/NLM config fields"
```

---

## Task 3: SQLite State Tracker

**Files:**
- Create: `notebooklm/state.py`
- Create: `tests/test_nlm_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_nlm_state.py
import sqlite3
import pytest
from notebooklm.state import (
    init_db, register_notebook, set_phase_status, get_phase_status,
    get_all_status, validate_retry, PHASE_ORDER,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "state.db"
    conn = init_db(db_path)
    yield conn
    conn.close()


class TestInitDb:
    def test_creates_tables(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        assert "notebooks" in tables
        assert "phase_status" in tables

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "state.db"
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        conn2.close()  # No error on second call


class TestRegisterNotebook:
    def test_insert(self, db):
        register_notebook(db, "nb1", "RAND Taiwan Report", "RAND")
        row = db.execute("SELECT * FROM notebooks WHERE id='nb1'").fetchone()
        assert row is not None

    def test_upsert_same_id(self, db):
        register_notebook(db, "nb1", "Title v1", "RAND")
        register_notebook(db, "nb1", "Title v2", "RAND")
        count = db.execute("SELECT count(*) FROM notebooks").fetchone()[0]
        assert count == 1

    def test_creates_pending_phases(self, db):
        register_notebook(db, "nb1", "Title", "RAND")
        rows = db.execute(
            "SELECT phase, status FROM phase_status WHERE notebook_id='nb1' ORDER BY phase"
        ).fetchall()
        phases = {r[0]: r[1] for r in rows}
        assert phases == {
            "export": "pending",
            "transcribe": "pending",
            "extract": "pending",
            "ingest": "pending",
        }


class TestSetAndGetPhaseStatus:
    def test_set_running(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "running")
        assert get_phase_status(db, "nb1", "export") == "running"

    def test_set_completed(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "completed")
        assert get_phase_status(db, "nb1", "export") == "completed"

    def test_set_failed_with_error(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "failed", error="timeout")
        assert get_phase_status(db, "nb1", "export") == "failed"
        row = db.execute(
            "SELECT error FROM phase_status WHERE notebook_id='nb1' AND phase='export'"
        ).fetchone()
        assert row[0] == "timeout"


class TestGetAllStatus:
    def test_matrix(self, db):
        register_notebook(db, "nb1", "Report A", "RAND")
        set_phase_status(db, "nb1", "export", "completed")
        set_phase_status(db, "nb1", "transcribe", "running")
        matrix = get_all_status(db)
        assert len(matrix) == 1
        assert matrix[0]["notebook_id"] == "nb1"
        assert matrix[0]["export"] == "completed"
        assert matrix[0]["transcribe"] == "running"
        assert matrix[0]["extract"] == "pending"
        assert matrix[0]["ingest"] == "pending"


class TestValidateRetry:
    def test_retry_export_always_ok(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "failed")
        validate_retry(db, "nb1", "export")  # No exception

    def test_retry_transcribe_needs_export_completed(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "failed")
        set_phase_status(db, "nb1", "transcribe", "failed")
        with pytest.raises(ValueError, match="prerequisite 'export'"):
            validate_retry(db, "nb1", "transcribe")

    def test_retry_transcribe_ok_when_export_completed(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "completed")
        set_phase_status(db, "nb1", "transcribe", "failed")
        validate_retry(db, "nb1", "transcribe")  # No exception

    def test_retry_ingest_needs_all_prior_completed(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "completed")
        set_phase_status(db, "nb1", "transcribe", "completed")
        set_phase_status(db, "nb1", "extract", "failed")
        set_phase_status(db, "nb1", "ingest", "failed")
        with pytest.raises(ValueError, match="prerequisite 'extract'"):
            validate_retry(db, "nb1", "ingest")


class TestAtomicRetry:
    def test_retry_only_updates_failed(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "completed")
        # Attempt retry on completed phase — should return 0 rows affected
        from notebooklm.state import attempt_retry
        affected = attempt_retry(db, "nb1", "export")
        assert affected == 0
        assert get_phase_status(db, "nb1", "export") == "completed"

    def test_retry_updates_failed_phase(self, db):
        register_notebook(db, "nb1", "T", "S")
        set_phase_status(db, "nb1", "export", "failed")
        from notebooklm.state import attempt_retry
        affected = attempt_retry(db, "nb1", "export")
        assert affected == 1
        assert get_phase_status(db, "nb1", "export") == "running"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebooklm.state'`

- [ ] **Step 3: Implement state.py**

```python
# notebooklm/state.py
from __future__ import annotations

import sqlite3
from pathlib import Path

PHASE_ORDER = ["export", "transcribe", "extract", "ingest"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    title TEXT,
    source_name TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS phase_status (
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
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def register_notebook(
    db: sqlite3.Connection, notebook_id: str, title: str, source_name: str
) -> None:
    db.execute(
        "INSERT OR IGNORE INTO notebooks (id, title, source_name) VALUES (?, ?, ?)",
        (notebook_id, title, source_name),
    )
    for phase in PHASE_ORDER:
        db.execute(
            "INSERT OR IGNORE INTO phase_status (notebook_id, phase, status) VALUES (?, ?, 'pending')",
            (notebook_id, phase),
        )
    db.commit()


def set_phase_status(
    db: sqlite3.Connection,
    notebook_id: str,
    phase: str,
    status: str,
    *,
    error: str | None = None,
) -> None:
    if status == "running":
        db.execute(
            """UPDATE phase_status
               SET status = ?, started_at = datetime('now'), error = NULL, updated_at = datetime('now')
               WHERE notebook_id = ? AND phase = ?""",
            (status, notebook_id, phase),
        )
    elif status == "completed":
        db.execute(
            """UPDATE phase_status
               SET status = ?, finished_at = datetime('now'), error = NULL, updated_at = datetime('now')
               WHERE notebook_id = ? AND phase = ?""",
            (status, notebook_id, phase),
        )
    elif status == "failed":
        db.execute(
            """UPDATE phase_status
               SET status = ?, finished_at = datetime('now'), error = ?, updated_at = datetime('now')
               WHERE notebook_id = ? AND phase = ?""",
            (status, error, notebook_id, phase),
        )
    else:
        db.execute(
            """UPDATE phase_status SET status = ?, updated_at = datetime('now')
               WHERE notebook_id = ? AND phase = ?""",
            (status, notebook_id, phase),
        )
    db.commit()


def get_phase_status(db: sqlite3.Connection, notebook_id: str, phase: str) -> str:
    row = db.execute(
        "SELECT status FROM phase_status WHERE notebook_id = ? AND phase = ?",
        (notebook_id, phase),
    ).fetchone()
    return row[0] if row else "unknown"


def get_all_status(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute(
        """SELECT n.id, n.title, n.source_name, ps.phase, ps.status
           FROM notebooks n
           JOIN phase_status ps ON n.id = ps.notebook_id
           ORDER BY n.id, ps.phase"""
    ).fetchall()
    notebooks: dict[str, dict] = {}
    for nid, title, source, phase, status in rows:
        if nid not in notebooks:
            notebooks[nid] = {"notebook_id": nid, "title": title, "source": source}
        notebooks[nid][phase] = status
    return list(notebooks.values())


def validate_retry(db: sqlite3.Connection, notebook_id: str, phase: str) -> None:
    idx = PHASE_ORDER.index(phase)
    for prev_phase in PHASE_ORDER[:idx]:
        status = get_phase_status(db, notebook_id, prev_phase)
        if status != "completed":
            raise ValueError(
                f"Cannot retry '{phase}': prerequisite '{prev_phase}' is '{status}'"
            )


def attempt_retry(db: sqlite3.Connection, notebook_id: str, phase: str) -> int:
    cursor = db.execute(
        """UPDATE phase_status
           SET status = 'running',
               retry_count = retry_count + 1,
               started_at = datetime('now'),
               updated_at = datetime('now')
           WHERE notebook_id = ? AND phase = ? AND status = 'failed'""",
        (notebook_id, phase),
    )
    db.commit()
    return cursor.rowcount
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_state.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/state.py \
       services/data-ingestion/tests/test_nlm_state.py
git commit -m "feat(data-ingestion): add SQLite state tracker with phase gating"
```

---

## Task 4: Write Templates

**Files:**
- Create: `notebooklm/write_templates.py`

No tests needed — these are string constants. They'll be validated via the ingestion tests in Task 8.

- [ ] **Step 1: Create write_templates.py**

```python
# notebooklm/write_templates.py
"""
Pinned Neo4j Cypher write templates for NotebookLM ingestion.

Stable templates from intelligence/graph/write_templates.py are copied here
because data-ingestion and intelligence have separate Docker build contexts.
NLM-specific templates (Claim, Source tier) are new.
"""

# --- Pinned from intelligence (stable) ---

UPSERT_ENTITY = """
MERGE (e:Entity {name: $name, type: $type})
SET e.aliases = $aliases,
    e.confidence = $confidence,
    e.last_seen = datetime()
ON CREATE SET e.first_seen = datetime()
"""

UPSERT_DOCUMENT = """
MERGE (d:Document {notebook_id: $notebook_id})
SET d.title = $title,
    d.source = $source,
    d.type = $type,
    d.updated_at = datetime()
"""

# --- NLM-specific ---

UPSERT_SOURCE_WITH_TIER = """
MERGE (s:Source {name: $source_name})
SET s.quality_tier = $quality_tier,
    s.updated_at = datetime()
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

SOURCE_TIERS: dict[str, str] = {
    "RAND": "tier_1",
    "CSIS": "tier_1",
    "Brookings": "tier_1",
    "CNA": "tier_2",
    "IISS": "tier_2",
}


def get_source_tier(source_name: str) -> str:
    """Return quality tier for a source. Default: tier_3."""
    for key, tier in SOURCE_TIERS.items():
        if key.lower() in source_name.lower():
            return tier
    return "tier_3"
```

- [ ] **Step 2: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/write_templates.py
git commit -m "feat(data-ingestion): add pinned Neo4j write templates for NLM"
```

---

## Task 5: Extraction Prompt

**Files:**
- Create: `notebooklm/prompts/extraction_v1.txt`

- [ ] **Step 1: Create the versioned extraction prompt**

```text
You are a geopolitical intelligence analyst. Extract structured information from the following transcript of a think-tank podcast.

## Output Format

Return valid JSON with exactly this structure:

{
  "entities": [
    {
      "name": "string — canonical name",
      "type": "ORGANIZATION | COUNTRY | PERSON | REGION | WEAPON_SYSTEM | MILITARY_UNIT | POLICY | TREATY | CONCEPT | VESSEL | AIRCRAFT | SATELLITE",
      "aliases": ["list of alternative names mentioned"],
      "confidence": 0.0-1.0
    }
  ],
  "relations": [
    {
      "source": "entity name (must match an entity above)",
      "target": "entity name (must match an entity above)",
      "type": "ALLIED_WITH | COMPETES_WITH | SANCTIONS | SUPPLIES_TO | OPERATES_IN | MEMBER_OF | COMMANDS | TARGETS | NEGOTIATES_WITH",
      "evidence": "brief quote or paraphrase from transcript",
      "confidence": 0.0-1.0
    }
  ],
  "claims": [
    {
      "statement": "one clear declarative sentence",
      "type": "factual | assessment | prediction",
      "polarity": "positive | negative | neutral",
      "entities_involved": ["entity names referenced in this claim"],
      "confidence": 0.0-1.0,
      "temporal_scope": "time period this claim applies to (e.g. '2025', '2024-2026', 'ongoing')"
    }
  ]
}

## Rules

1. **Entities**: Use canonical names (e.g., "People's Republic of China" not "China" — but include "China" as alias). Merge co-referent mentions.
2. **Relations**: Only extract relations explicitly stated or strongly implied. Each must reference two entities from your entity list.
3. **Claims**: Distinguish factual (verifiable), assessment (analytical judgment), and prediction (future-oriented). One sentence per claim. No hedging — the confidence score captures uncertainty.
4. **Confidence**: 0.9+ = explicitly stated with evidence. 0.7-0.89 = strongly implied. 0.5-0.69 = weakly implied or ambiguous. Below 0.5 = don't extract.
5. **Temporal scope**: Always provide. Use "ongoing" if no time reference is given.
6. **Do NOT invent** information not present in the transcript. When in doubt, lower confidence rather than omit.

## Source Context

Source: {source_name}
Title: {title}

## Transcript

{transcript_text}
```

- [ ] **Step 2: Commit**

```bash
cd ~/ODIN/OSINT
mkdir -p services/data-ingestion/notebooklm/prompts
git add services/data-ingestion/notebooklm/prompts/extraction_v1.txt
git commit -m "feat(data-ingestion): add versioned extraction prompt v1"
```

---

## Task 6: Phase 2 — Transcription

**Files:**
- Create: `notebooklm/transcribe.py`
- Create: `tests/test_nlm_transcribe.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_nlm_transcribe.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx

from notebooklm.transcribe import transcribe_chunk, transcribe, split_audio


class TestTranscribeChunk:
    @pytest.mark.asyncio
    async def test_returns_segments(self):
        mock_response = httpx.Response(
            200,
            json={
                "text": "Hello world. This is a test.",
                "segments": [
                    {"start": 0.0, "end": 2.5, "text": "Hello world."},
                    {"start": 2.5, "end": 5.0, "text": "This is a test."},
                ],
            },
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        result = await transcribe_chunk(
            audio_path=Path("/fake/audio.wav"),
            client=client,
            voxtral_url="http://localhost:8010/v1",
            voxtral_model="voxtral",
        )
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello world."

    @pytest.mark.asyncio
    async def test_fallback_no_segments(self):
        """When API returns text but no segments, create single segment."""
        mock_response = httpx.Response(
            200,
            json={"text": "Full transcript without segments."},
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        result = await transcribe_chunk(
            audio_path=Path("/fake/audio.wav"),
            client=client,
            voxtral_url="http://localhost:8010/v1",
            voxtral_model="voxtral",
        )
        assert len(result.segments) == 1
        assert result.segments[0].text == "Full transcript without segments."


class TestTranscribe:
    @pytest.mark.asyncio
    async def test_single_chunk_sets_notebook_id(self):
        """Short audio (< chunk size) produces Transcript with correct notebook_id."""
        mock_chunk_result = MagicMock()
        mock_chunk_result.segments = [
            MagicMock(start=0.0, end=10.0, text="Short audio", speaker=None)
        ]

        with patch("notebooklm.transcribe.split_audio", return_value=[Path("/tmp/c0.wav")]), \
             patch("notebooklm.transcribe.transcribe_chunk", new_callable=AsyncMock, return_value=mock_chunk_result), \
             patch("notebooklm.transcribe.get_original_duration", return_value=10.0), \
             patch("notebooklm.transcribe.majority_language", return_value="en"):
            result = await transcribe(
                notebook_id="nb42",
                audio_path=Path("/fake/podcast.mp3"),
                client=AsyncMock(),
                voxtral_url="http://localhost:8010/v1",
                voxtral_model="voxtral",
            )
        assert result.notebook_id == "nb42"
        assert result.language == "en"
        assert "Short audio" in result.full_text

    @pytest.mark.asyncio
    async def test_multi_chunk_offsets(self):
        """Multiple chunks get time offsets applied."""
        seg0 = MagicMock(start=0.0, end=5.0, text="Chunk zero", speaker=None)
        seg1 = MagicMock(start=0.0, end=5.0, text="Chunk one", speaker=None)
        chunk0 = MagicMock(segments=[seg0])
        chunk1 = MagicMock(segments=[seg1])

        with patch("notebooklm.transcribe.split_audio", return_value=[Path("/tmp/c0.wav"), Path("/tmp/c1.wav")]), \
             patch("notebooklm.transcribe.transcribe_chunk", new_callable=AsyncMock, side_effect=[chunk0, chunk1]), \
             patch("notebooklm.transcribe.get_original_duration", return_value=1200.0), \
             patch("notebooklm.transcribe.majority_language", return_value="en"):
            result = await transcribe(
                notebook_id="nb1",
                audio_path=Path("/fake/long.mp3"),
                client=AsyncMock(),
                voxtral_url="http://localhost:8010/v1",
                voxtral_model="voxtral",
            )
        # Second chunk's segment should be offset by 600s (10 min)
        assert result.segments[1].start == 600.0
        assert result.segments[1].end == 605.0


class TestSplitAudio:
    def test_short_audio_returns_single(self, tmp_path):
        """Audio shorter than max_minutes returns the original file."""
        # Create a tiny valid WAV (44 bytes header + silence)
        wav_path = tmp_path / "short.wav"
        _write_silent_wav(wav_path, duration_ms=5000)
        chunks = split_audio(wav_path, max_minutes=10)
        assert len(chunks) == 1


def _write_silent_wav(path: Path, duration_ms: int = 5000):
    """Helper: write a minimal silent WAV file using pydub."""
    from pydub import AudioSegment
    silence = AudioSegment.silent(duration=duration_ms)
    silence.export(str(path), format="wav")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_transcribe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebooklm.transcribe'`

- [ ] **Step 3: Implement transcribe.py**

```python
# notebooklm/transcribe.py
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog
from pydub import AudioSegment

from notebooklm.schemas import Transcript, TranscriptSegment

log = structlog.get_logger()

CHUNK_MINUTES = 10


@dataclass
class ChunkResult:
    segments: list[TranscriptSegment]
    language: str | None = None


def split_audio(audio_path: Path, max_minutes: int = CHUNK_MINUTES) -> list[Path]:
    """Split audio into chunks of max_minutes. Returns list of chunk file paths."""
    audio = AudioSegment.from_file(str(audio_path))
    max_ms = max_minutes * 60 * 1000
    if len(audio) <= max_ms:
        return [audio_path]

    chunks: list[Path] = []
    chunk_dir = audio_path.parent / f"{audio_path.stem}_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    num_chunks = math.ceil(len(audio) / max_ms)
    for i in range(num_chunks):
        start_ms = i * max_ms
        end_ms = min((i + 1) * max_ms, len(audio))
        chunk = audio[start_ms:end_ms]
        chunk_path = chunk_dir / f"chunk_{i:03d}.wav"
        chunk.export(str(chunk_path), format="wav")
        chunks.append(chunk_path)

    log.info("audio_split", path=str(audio_path), chunks=len(chunks))
    return chunks


def get_original_duration(audio_path: Path) -> float:
    """Get duration in seconds from audio file."""
    audio = AudioSegment.from_file(str(audio_path))
    return len(audio) / 1000.0


def majority_language(chunk_results: list[ChunkResult]) -> str:
    """Return most common language across chunks. Default: 'en'."""
    langs = [c.language for c in chunk_results if c.language]
    if not langs:
        return "en"
    counter = Counter(langs)
    return counter.most_common(1)[0][0]


async def transcribe_chunk(
    audio_path: Path,
    client: httpx.AsyncClient,
    voxtral_url: str,
    voxtral_model: str,
) -> ChunkResult:
    """Transcribe a single audio chunk via Voxtral."""
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    response = await client.post(
        f"{voxtral_url}/audio/transcriptions",
        files={"file": (audio_path.name, audio_bytes, "audio/wav")},
        data={"model": voxtral_model, "response_format": "verbose_json"},
        timeout=300.0,
    )
    response.raise_for_status()
    data = response.json()

    text = data.get("text", "")
    raw_segments = data.get("segments", [])
    language = data.get("language")

    if raw_segments:
        segments = [
            TranscriptSegment(
                start=s.get("start", 0.0),
                end=s.get("end", 0.0),
                text=s.get("text", ""),
                speaker=s.get("speaker"),
            )
            for s in raw_segments
        ]
    else:
        segments = [TranscriptSegment(start=0.0, end=0.0, text=text)]

    return ChunkResult(segments=segments, language=language)


async def transcribe(
    notebook_id: str,
    audio_path: Path,
    client: httpx.AsyncClient,
    voxtral_url: str,
    voxtral_model: str,
) -> Transcript:
    """Transcribe full audio file with chunking. Returns Transcript with notebook_id."""
    chunks = split_audio(audio_path)
    chunk_duration_sec = CHUNK_MINUTES * 60

    all_segments: list[TranscriptSegment] = []
    chunk_results: list[ChunkResult] = []

    for i, chunk_path in enumerate(chunks):
        result = await transcribe_chunk(chunk_path, client, voxtral_url, voxtral_model)
        chunk_results.append(result)
        offset = i * chunk_duration_sec
        for seg in result.segments:
            all_segments.append(
                TranscriptSegment(
                    start=seg.start + offset,
                    end=seg.end + offset,
                    text=seg.text,
                    speaker=seg.speaker,
                )
            )

    return Transcript(
        notebook_id=notebook_id,
        segments=all_segments,
        full_text=" ".join(s.text for s in all_segments),
        duration_seconds=get_original_duration(audio_path),
        language=majority_language(chunk_results),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_transcribe.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/transcribe.py \
       services/data-ingestion/tests/test_nlm_transcribe.py
git commit -m "feat(data-ingestion): add Voxtral transcription with audio chunking"
```

---

## Task 7: Phase 3 — Hybrid Extraction

**Files:**
- Create: `notebooklm/extract.py`
- Create: `tests/test_nlm_extract.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_nlm_extract.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx

from notebooklm.extract import (
    extract_with_qwen, review_with_claude, extract_context,
    load_prompt, CLAUDE_BUDGET_PER_RUN,
)
from notebooklm.schemas import Transcript, TranscriptSegment, Extraction


def _make_transcript(text: str = "NATO expanded eastward. China opposes this.") -> Transcript:
    return Transcript(
        notebook_id="nb1",
        duration_seconds=60.0,
        language="en",
        segments=[TranscriptSegment(start=0.0, end=60.0, text=text)],
        full_text=text,
    )


_QWEN_RESPONSE = {
    "entities": [
        {"name": "NATO", "type": "ORGANIZATION", "aliases": [], "confidence": 0.95},
        {"name": "China", "type": "COUNTRY", "aliases": ["PRC"], "confidence": 0.9},
    ],
    "relations": [
        {
            "source": "China", "target": "NATO", "type": "COMPETES_WITH",
            "evidence": "China opposes this", "confidence": 0.75,
        },
    ],
    "claims": [
        {
            "statement": "NATO expanded eastward",
            "type": "factual", "polarity": "neutral",
            "entities_involved": ["NATO"],
            "confidence": 0.95, "temporal_scope": "ongoing",
        },
        {
            "statement": "China opposes NATO expansion",
            "type": "assessment", "polarity": "negative",
            "entities_involved": ["China", "NATO"],
            "confidence": 0.6, "temporal_scope": "ongoing",
        },
    ],
}


class TestLoadPrompt:
    def test_loads_v1(self):
        prompt = load_prompt("v1")
        assert "{source_name}" in prompt
        assert "{transcript_text}" in prompt

    def test_missing_version_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("v999")


class TestExtractWithQwen:
    @pytest.mark.asyncio
    async def test_returns_extraction(self):
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(_QWEN_RESPONSE)}}
                ]
            },
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        extraction = await extract_with_qwen(
            transcript=_make_transcript(),
            metadata={"source_name": "RAND", "title": "Test Report"},
            client=client,
            vllm_url="http://localhost:8000/v1",
            vllm_model="qwen3.5",
        )
        assert extraction.notebook_id == "nb1"
        assert len(extraction.entities) == 2
        assert len(extraction.claims) == 2
        assert extraction.extraction_model == "qwen3.5"
        assert extraction.prompt_version == "v1"

    @pytest.mark.asyncio
    async def test_vllm_error_raises(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await extract_with_qwen(
                transcript=_make_transcript(),
                metadata={"source_name": "X", "title": "Y"},
                client=client,
                vllm_url="http://localhost:8000/v1",
                vllm_model="qwen3.5",
            )


class TestExtractContext:
    def test_extracts_window(self):
        text = "A " * 500 + "TARGET " + "B " * 500
        window = extract_context(text, "TARGET", radius=50)
        assert "TARGET" in window
        assert len(window) < len(text)

    def test_short_text_returns_all(self):
        text = "short text"
        window = extract_context(text, "short", radius=500)
        assert window == text


class TestReviewWithClaude:
    @pytest.mark.asyncio
    async def test_upgrades_low_confidence(self):
        extraction = Extraction(
            notebook_id="nb1",
            entities=[],
            relations=[],
            claims=[
                {
                    "statement": "China opposes NATO expansion",
                    "type": "assessment", "polarity": "negative",
                    "entities_involved": ["China", "NATO"],
                    "confidence": 0.6, "temporal_scope": "ongoing",
                },
            ],
            extraction_model="qwen3.5",
            prompt_version="v1",
        )
        transcript = _make_transcript()

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.85}')]
        mock_client.messages.create.return_value = mock_message

        reviewed = await review_with_claude(
            extraction=extraction,
            transcript=transcript,
            claude_client=mock_client,
            claude_model="claude-sonnet-4-20250514",
        )
        assert reviewed.claims[0].confidence == 0.85

    @pytest.mark.asyncio
    async def test_respects_budget(self):
        """Should stop reviewing when token budget is exhausted."""
        # Create 200 low-confidence claims with long context
        claims = [
            {
                "statement": f"Claim number {i} about geopolitics",
                "type": "assessment", "polarity": "neutral",
                "entities_involved": [], "confidence": 0.5,
                "temporal_scope": "ongoing",
            }
            for i in range(200)
        ]
        extraction = Extraction(
            notebook_id="nb1", entities=[], relations=[],
            claims=claims, extraction_model="qwen3.5", prompt_version="v1",
        )
        # Transcript with 200K chars (~50K tokens) — bigger than budget
        transcript = _make_transcript("word " * 40_000)

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.8}')]
        mock_client.messages.create.return_value = mock_message

        await review_with_claude(
            extraction=extraction,
            transcript=transcript,
            claude_client=mock_client,
            claude_model="claude-sonnet-4-20250514",
        )
        # Should NOT have reviewed all 200 claims — budget caps it
        call_count = mock_client.messages.create.call_count
        assert call_count < 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebooklm.extract'`

- [ ] **Step 3: Implement extract.py**

```python
# notebooklm/extract.py
from __future__ import annotations

import json
from pathlib import Path

import httpx
import structlog

from notebooklm.schemas import (
    Transcript, Extraction, Entity, Relation, Claim,
)

log = structlog.get_logger()

CLAUDE_BUDGET_PER_RUN = 50_000  # Max input tokens per run
PROMPT_DIR = Path(__file__).parent / "prompts"


def load_prompt(version: str) -> str:
    """Load extraction prompt by version string (e.g. 'v1')."""
    path = PROMPT_DIR / f"extraction_{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text()


def extract_context(full_text: str, target: str, radius: int = 500) -> str:
    """Extract a window of `radius` chars around `target` in `full_text`."""
    idx = full_text.find(target)
    if idx == -1:
        return full_text[:radius * 2]
    start = max(0, idx - radius)
    end = min(len(full_text), idx + len(target) + radius)
    return full_text[start:end]


async def extract_with_qwen(
    transcript: Transcript,
    metadata: dict,
    client: httpx.AsyncClient,
    vllm_url: str,
    vllm_model: str,
    prompt_version: str = "v1",
) -> Extraction:
    """Phase 3a: Extract entities, relations, claims via Qwen (local vLLM)."""
    prompt_template = load_prompt(prompt_version)
    prompt = prompt_template.format(
        source_name=metadata.get("source_name", "unknown"),
        title=metadata.get("title", "untitled"),
        transcript_text=transcript.full_text[:16_000],  # Cap context
    )

    payload = {
        "model": vllm_model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4000,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    response = await client.post(
        f"{vllm_url}/chat/completions",
        json=payload,
        timeout=120.0,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(content)

    return Extraction(
        notebook_id=transcript.notebook_id,
        entities=[Entity(**e) for e in data.get("entities", [])],
        relations=[Relation(**r) for r in data.get("relations", [])],
        claims=[Claim(**c) for c in data.get("claims", [])],
        extraction_model=vllm_model,
        prompt_version=prompt_version,
    )


async def review_with_claude(
    extraction: Extraction,
    transcript: Transcript,
    claude_client,  # anthropic.AsyncAnthropic
    claude_model: str,
) -> Extraction:
    """Phase 3b: Review low-confidence items via Claude API. Modifies extraction in place."""
    low_conf_claims = [c for c in extraction.claims if c.confidence < 0.7]
    if not low_conf_claims:
        log.info("claude_review_skip", reason="no low-confidence claims")
        return extraction

    token_budget = CLAUDE_BUDGET_PER_RUN
    reviewed_count = 0

    for claim in low_conf_claims:
        context_window = extract_context(
            transcript.full_text, claim.statement[:80], radius=500
        )
        estimated_tokens = len(context_window) // 4
        if token_budget - estimated_tokens < 0:
            log.info("claude_budget_exhausted", reviewed=reviewed_count)
            break
        token_budget -= estimated_tokens

        try:
            message = await claude_client.messages.create(
                model=claude_model,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Verify this claim extracted from a think-tank podcast transcript.\n\n"
                        f"Claim: \"{claim.statement}\"\n"
                        f"Type: {claim.type} | Polarity: {claim.polarity}\n\n"
                        f"Transcript context:\n{context_window}\n\n"
                        f"Return JSON: {{\"verdict\": \"confirmed|rejected|modified\", \"confidence\": 0.0-1.0}}"
                    ),
                }],
            )
            result = json.loads(message.content[0].text)
            if result.get("verdict") == "rejected":
                claim.confidence = 0.0
            else:
                claim.confidence = result.get("confidence", claim.confidence)
            reviewed_count += 1
        except Exception:
            log.warning("claude_review_failed", claim=claim.statement[:50])
            continue

    log.info("claude_review_done", reviewed=reviewed_count, budget_remaining=token_budget)
    return extraction
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_extract.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/extract.py \
       services/data-ingestion/tests/test_nlm_extract.py
git commit -m "feat(data-ingestion): add hybrid Qwen+Claude extraction"
```

---

## Task 8: Phase 4 — Neo4j Ingestion

**Files:**
- Create: `notebooklm/ingest_neo4j.py`
- Create: `tests/test_nlm_ingest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_nlm_ingest.py
from unittest.mock import AsyncMock, call, patch, MagicMock

import pytest
import httpx

from notebooklm.ingest_neo4j import ingest_extraction
from notebooklm.schemas import Extraction, Entity, Relation, Claim


def _make_extraction() -> Extraction:
    return Extraction(
        notebook_id="nb1",
        entities=[
            Entity(name="NATO", type="ORGANIZATION", aliases=["North Atlantic Treaty Organization"], confidence=0.95),
            Entity(name="China", type="COUNTRY", aliases=["PRC"], confidence=0.9),
        ],
        relations=[
            Relation(source="China", target="NATO", type="COMPETES_WITH", evidence="opposes expansion", confidence=0.75),
        ],
        claims=[
            Claim(
                statement="NATO expanded eastward", type="factual", polarity="neutral",
                entities_involved=["NATO"], confidence=0.95, temporal_scope="ongoing",
            ),
        ],
        extraction_model="qwen3.5",
        prompt_version="v1",
    )


class TestIngestExtraction:
    @pytest.mark.asyncio
    async def test_sends_cypher_statements(self):
        mock_response = httpx.Response(200, json={"results": [], "errors": []})
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        await ingest_extraction(
            extraction=_make_extraction(),
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
        )
        # Should have posted to Neo4j transactional endpoint
        assert client.post.called
        post_call = client.post.call_args
        assert "/db/neo4j/tx/commit" in post_call.args[0]

    @pytest.mark.asyncio
    async def test_batch_contains_source_entity_claim(self):
        mock_response = httpx.Response(200, json={"results": [], "errors": []})
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        await ingest_extraction(
            extraction=_make_extraction(),
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
        )
        # Inspect the statements sent
        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        statements = payload["statements"]
        cypher_texts = [s["statement"] for s in statements]
        joined = " ".join(cypher_texts)
        # Should contain Source, Document, Entity, Claim operations
        assert "Source" in joined
        assert "Document" in joined
        assert "Entity" in joined
        assert "Claim" in joined

    @pytest.mark.asyncio
    async def test_source_tier_applied(self):
        mock_response = httpx.Response(200, json={"results": [], "errors": []})
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        await ingest_extraction(
            extraction=_make_extraction(),
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
        )
        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        statements = payload["statements"]
        # Find source statement and check tier
        source_stmt = next(s for s in statements if "Source" in s["statement"] and "quality_tier" in s["statement"])
        assert source_stmt["parameters"]["quality_tier"] == "tier_1"

    @pytest.mark.asyncio
    async def test_neo4j_error_raises_runtime_error(self):
        mock_response = httpx.Response(
            200,
            json={"results": [], "errors": [{"message": "constraint violation"}]},
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        with pytest.raises(RuntimeError, match="constraint violation"):
            await ingest_extraction(
                extraction=_make_extraction(),
                source_name="RAND",
                client=client,
                neo4j_url="http://localhost:7474",
                neo4j_user="neo4j",
                neo4j_password="odin_yggdrasil",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebooklm.ingest_neo4j'`

- [ ] **Step 3: Implement ingest_neo4j.py**

```python
# notebooklm/ingest_neo4j.py
from __future__ import annotations

import base64

import httpx
import structlog

from notebooklm.schemas import Extraction, claim_hash
from notebooklm.write_templates import (
    UPSERT_SOURCE_WITH_TIER, UPSERT_DOCUMENT, LINK_DOCUMENT_SOURCE,
    UPSERT_ENTITY, UPSERT_CLAIM, LINK_CLAIM_DOCUMENT, LINK_CLAIM_ENTITY,
    get_source_tier,
)

log = structlog.get_logger()


def _build_statements(extraction: Extraction, source_name: str) -> list[dict]:
    """Build ordered list of Cypher statements for a single extraction."""
    statements: list[dict] = []

    # 1. Upsert Source with quality tier
    statements.append({
        "statement": UPSERT_SOURCE_WITH_TIER,
        "parameters": {
            "source_name": source_name,
            "quality_tier": get_source_tier(source_name),
        },
    })

    # 2. Upsert Document
    statements.append({
        "statement": UPSERT_DOCUMENT,
        "parameters": {
            "notebook_id": extraction.notebook_id,
            "title": f"NLM: {source_name}",
            "source": source_name,
            "type": "notebooklm_podcast",
        },
    })

    # 3. Link Document → Source
    statements.append({
        "statement": LINK_DOCUMENT_SOURCE,
        "parameters": {
            "notebook_id": extraction.notebook_id,
            "source_name": source_name,
        },
    })

    # 4. Upsert Entities
    for entity in extraction.entities:
        statements.append({
            "statement": UPSERT_ENTITY,
            "parameters": {
                "name": entity.name,
                "type": entity.type,
                "aliases": entity.aliases,
                "confidence": entity.confidence,
            },
        })

    # 5. Upsert Claims with provenance
    for claim in extraction.claims:
        if claim.confidence <= 0.0:
            continue  # Skip rejected claims
        stmt_hash = claim_hash(claim.statement)
        statements.append({
            "statement": UPSERT_CLAIM,
            "parameters": {
                "statement_hash": stmt_hash,
                "statement": claim.statement,
                "type": claim.type,
                "polarity": claim.polarity,
                "confidence": claim.confidence,
                "temporal_scope": claim.temporal_scope,
                "model": extraction.extraction_model,
                "prompt_version": extraction.prompt_version,
            },
        })

        # 6. Link Claim → Document
        statements.append({
            "statement": LINK_CLAIM_DOCUMENT,
            "parameters": {
                "statement_hash": stmt_hash,
                "notebook_id": extraction.notebook_id,
            },
        })

        # 7. Link Claim → Entities
        for entity_name in claim.entities_involved:
            statements.append({
                "statement": LINK_CLAIM_ENTITY,
                "parameters": {
                    "statement_hash": stmt_hash,
                    "entity_name": entity_name,
                },
            })

    return statements


async def ingest_extraction(
    extraction: Extraction,
    source_name: str,
    client: httpx.AsyncClient,
    neo4j_url: str,
    neo4j_user: str,
    neo4j_password: str,
) -> None:
    """Write extraction results to Neo4j via HTTP transactional API."""
    statements = _build_statements(extraction, source_name)

    auth_str = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Content-Type": "application/json",
    }

    payload = {"statements": statements}

    response = await client.post(
        f"{neo4j_url}/db/neo4j/tx/commit",
        json=payload,
        headers=headers,
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    errors = data.get("errors", [])
    if errors:
        log.warning("neo4j_errors", errors=errors, notebook_id=extraction.notebook_id)
        raise RuntimeError(f"Neo4j returned {len(errors)} error(s): {errors[0].get('message', '')}")
    log.info(
        "neo4j_ingest_ok",
        notebook_id=extraction.notebook_id,
        statements=len(statements),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_ingest.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/ingest_neo4j.py \
       services/data-ingestion/tests/test_nlm_ingest.py
git commit -m "feat(data-ingestion): add Neo4j ingestion with claim provenance"
```

---

## Task 9: Phase 1 — NotebookLM Export

**Files:**
- Create: `notebooklm/export.py`

Export depends on `notebooklm-py` which uses browser automation with cookie auth. Tests are integration-level (require real auth). We write the module with clear error messages and test the helper functions only.

- [ ] **Step 1: Implement export.py**

```python
# notebooklm/export.py
from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()


async def export_all(data_dir: Path, notebook_id: str | None = None) -> list[dict]:
    """
    Export notebooks from NotebookLM.

    Requires prior manual login (cookie-auth via notebooklm-py).
    If notebook_id is given, only that notebook is exported.
    Returns list of {notebook_id, title, source_name, audio_path} dicts.
    """
    try:
        import notebooklm_py
    except ImportError:
        raise ImportError(
            "notebooklm-py not installed. Run: uv pip install 'notebooklm-py[browser]' && playwright install"
        )

    client = notebooklm_py.NotebookLM()
    notebooks = await client.notebooks.list()
    if notebook_id:
        notebooks = [nb for nb in notebooks if nb.id == notebook_id]
    log.info("notebooklm_list", count=len(notebooks))

    exported: list[dict] = []
    for nb in notebooks:
        nb_dir = data_dir / "notebooks" / nb.id
        nb_dir.mkdir(parents=True, exist_ok=True)

        # Metadata
        meta = {
            "id": nb.id,
            "title": getattr(nb, "title", "untitled"),
            "source_name": _infer_source(getattr(nb, "title", "")),
        }
        (nb_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        # Audio (podcast)
        audio_path = nb_dir / "podcast.mp3"
        if not audio_path.exists():
            try:
                audio_data = await client.notebooks.get_audio(nb.id)
                audio_path.write_bytes(audio_data)
                log.info("export_audio", notebook_id=nb.id, size_mb=len(audio_data) / 1e6)
            except Exception:
                log.warning("export_audio_failed", notebook_id=nb.id, exc_info=True)
                continue

        exported.append({
            "notebook_id": nb.id,
            "title": meta["title"],
            "source_name": meta["source_name"],
            "audio_path": str(audio_path),
        })

    return exported


def _infer_source(title: str) -> str:
    """Best-effort source inference from notebook title."""
    known = ["RAND", "CSIS", "Brookings", "CNA", "IISS", "SIPRI", "NATO", "RUSI"]
    title_lower = title.lower()
    for source in known:
        if source.lower() in title_lower:
            return source
    return "unknown"
```

- [ ] **Step 2: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/export.py
git commit -m "feat(data-ingestion): add NotebookLM export module"
```

---

## Task 10: CLI (Click)

**Files:**
- Create: `notebooklm/cli.py`
- Create: `tests/test_nlm_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_nlm_cli.py
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

import pytest
from click.testing import CliRunner

from notebooklm.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestStatus:
    def test_status_empty(self, runner, tmp_path):
        with patch("notebooklm.cli._get_db") as mock_db:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_db.return_value = mock_conn
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "No notebooks" in result.output or "Notebook" in result.output


class TestRetry:
    def test_retry_requires_id_and_phase(self, runner):
        result = runner.invoke(cli, ["retry"])
        assert result.exit_code != 0

    def test_retry_validates_phase(self, runner):
        result = runner.invoke(cli, ["retry", "--id", "nb1", "--phase", "invalid"])
        assert result.exit_code != 0


class TestHealthcheck:
    def test_healthcheck_fails_gracefully(self, runner):
        with patch("notebooklm.cli._check_voxtral", new_callable=AsyncMock, return_value=False):
            result = runner.invoke(cli, ["healthcheck"])
            assert "FAIL" in result.output or "unhealthy" in result.output.lower() or result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notebooklm.cli'`

- [ ] **Step 3: Implement cli.py**

```python
# notebooklm/cli.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
import httpx
import structlog

from config import Settings
from notebooklm.state import (
    init_db, register_notebook, set_phase_status, get_phase_status,
    get_all_status, validate_retry, attempt_retry, PHASE_ORDER,
)
from notebooklm.schemas import Transcript

log = structlog.get_logger()


def _get_settings() -> Settings:
    return Settings()


def _get_db():
    settings = _get_settings()
    db_path = Path(settings.nlm_data_dir) / "state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return init_db(db_path)


async def _check_voxtral(url: str) -> bool:
    """Healthcheck: try real audio transcription, fallback to /models."""
    try:
        async with httpx.AsyncClient() as client:
            # Generate a minimal silent WAV (44-byte header + 1s silence)
            from pydub import AudioSegment
            import io
            silence = AudioSegment.silent(duration=1000)
            buf = io.BytesIO()
            silence.export(buf, format="wav")
            buf.seek(0)

            # Primary: real transcription request
            resp = await client.post(
                f"{url}/audio/transcriptions",
                files={"file": ("test.wav", buf.read(), "audio/wav")},
                data={"model": "voxtral", "response_format": "json"},
                timeout=30.0,
            )
            if resp.status_code == 200:
                return True

            # Fallback: at least check the model is loaded
            resp = await client.get(f"{url}/models", timeout=10.0)
            return resp.status_code == 200
    except Exception:
        return False


@click.group()
def cli():
    """NotebookLM → ODIN Knowledge Ingestion Pipeline."""
    pass


@cli.command()
def status():
    """Show status matrix: Notebook x Phase x Status."""
    db = _get_db()
    matrix = get_all_status(db)
    db.close()

    if not matrix:
        click.echo("No notebooks registered yet.")
        return

    # Header
    click.echo(f"{'Notebook':<35} {'export':<12} {'transcribe':<12} {'extract':<12} {'ingest':<12}")
    click.echo("-" * 83)
    for row in matrix:
        click.echo(
            f"{row.get('title', row['notebook_id'])[:34]:<35} "
            f"{row.get('export', '-'):<12} "
            f"{row.get('transcribe', '-'):<12} "
            f"{row.get('extract', '-'):<12} "
            f"{row.get('ingest', '-'):<12}"
        )


@cli.command()
def healthcheck():
    """Check if Voxtral is reachable and responding."""
    settings = _get_settings()
    ok = asyncio.run(_check_voxtral(settings.voxtral_url))
    if ok:
        click.echo("Voxtral: OK")
    else:
        click.echo("Voxtral: FAIL — is vllm-voxtral running?")
        raise SystemExit(1)


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Process single notebook by ID")
def export(notebook_id: str | None):
    """Phase 1: Export notebooks from NotebookLM."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from notebooklm.export import export_all
        results = await export_all(data_dir, notebook_id=notebook_id)
        db = _get_db()
        for r in results:
            register_notebook(db, r["notebook_id"], r["title"], r["source_name"])
            set_phase_status(db, r["notebook_id"], "export", "completed")
        db.close()
        click.echo(f"Exported {len(results)} notebooks.")

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Transcribe single notebook by ID")
def transcribe(notebook_id: str | None):
    """Phase 2: Transcribe audio via Voxtral."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from notebooklm.transcribe import transcribe as do_transcribe
        db = _get_db()
        matrix = get_all_status(db)
        targets = [
            r for r in matrix
            if r.get("export") == "completed"
            and r.get("transcribe") in ("pending", "failed", "running")
            and (notebook_id is None or r["notebook_id"] == notebook_id)
        ]

        async with httpx.AsyncClient() as client:
            for row in targets:
                nid = row["notebook_id"]
                audio_path = data_dir / "notebooks" / nid / "podcast.mp3"
                if not audio_path.exists():
                    click.echo(f"SKIP {nid}: no audio file")
                    continue

                set_phase_status(db, nid, "transcribe", "running")
                try:
                    result = await do_transcribe(
                        notebook_id=nid,
                        audio_path=audio_path,
                        client=client,
                        voxtral_url=settings.voxtral_url,
                        voxtral_model=settings.voxtral_model,
                    )
                    out_path = data_dir / "transcripts" / f"{nid}.json"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(result.model_dump_json(indent=2))
                    set_phase_status(db, nid, "transcribe", "completed")
                    click.echo(f"OK {nid}: {result.duration_seconds:.0f}s, {len(result.segments)} segments")
                except Exception as e:
                    set_phase_status(db, nid, "transcribe", "failed", error=str(e))
                    click.echo(f"FAIL {nid}: {e}")

        db.close()

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Extract from single notebook by ID")
def extract(notebook_id: str | None):
    """Phase 3: Extract entities/claims via Qwen + Claude."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from notebooklm.extract import extract_with_qwen, review_with_claude
        db = _get_db()
        matrix = get_all_status(db)
        targets = [
            r for r in matrix
            if r.get("transcribe") == "completed"
            and r.get("extract") in ("pending", "failed", "running")
            and (notebook_id is None or r["notebook_id"] == notebook_id)
        ]

        claude_client = None
        try:
            import anthropic
            claude_client = anthropic.AsyncAnthropic()
        except Exception:
            log.warning("anthropic_not_available", msg="Claude review disabled")

        async with httpx.AsyncClient() as client:
            for row in targets:
                nid = row["notebook_id"]
                transcript_path = data_dir / "transcripts" / f"{nid}.json"
                if not transcript_path.exists():
                    click.echo(f"SKIP {nid}: no transcript")
                    continue

                set_phase_status(db, nid, "extract", "running")
                try:
                    transcript = Transcript.model_validate_json(transcript_path.read_text())
                    meta_path = data_dir / "notebooks" / nid / "metadata.json"
                    metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}

                    extraction = await extract_with_qwen(
                        transcript=transcript,
                        metadata=metadata,
                        client=client,
                        vllm_url=settings.vllm_url + "/v1",
                        vllm_model=settings.vllm_model,
                    )

                    if claude_client:
                        extraction = await review_with_claude(
                            extraction=extraction,
                            transcript=transcript,
                            claude_client=claude_client,
                            claude_model=settings.claude_model,
                        )

                    out_path = data_dir / "extractions" / f"{nid}.json"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(extraction.model_dump_json(indent=2))
                    set_phase_status(db, nid, "extract", "completed")
                    click.echo(
                        f"OK {nid}: {len(extraction.entities)} entities, "
                        f"{len(extraction.claims)} claims, "
                        f"{len(extraction.relations)} relations"
                    )
                except Exception as e:
                    set_phase_status(db, nid, "extract", "failed", error=str(e))
                    click.echo(f"FAIL {nid}: {e}")

        db.close()

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Ingest single notebook by ID")
def ingest(notebook_id: str | None):
    """Phase 4: Write extraction results to Neo4j."""
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)

    async def _run():
        from notebooklm.ingest_neo4j import ingest_extraction
        from notebooklm.schemas import Extraction
        db = _get_db()
        matrix = get_all_status(db)
        targets = [
            r for r in matrix
            if r.get("extract") == "completed"
            and r.get("ingest") in ("pending", "failed", "running")
            and (notebook_id is None or r["notebook_id"] == notebook_id)
        ]

        async with httpx.AsyncClient() as client:
            for row in targets:
                nid = row["notebook_id"]
                extraction_path = data_dir / "extractions" / f"{nid}.json"
                if not extraction_path.exists():
                    click.echo(f"SKIP {nid}: no extraction")
                    continue

                set_phase_status(db, nid, "ingest", "running")
                try:
                    extraction = Extraction.model_validate_json(extraction_path.read_text())
                    source_name = row.get("source", "unknown")

                    await ingest_extraction(
                        extraction=extraction,
                        source_name=source_name,
                        client=client,
                        neo4j_url=settings.neo4j_url,
                        neo4j_user=settings.neo4j_user,
                        neo4j_password=settings.neo4j_password,
                    )
                    set_phase_status(db, nid, "ingest", "completed")
                    click.echo(f"OK {nid}: ingested to Neo4j")
                except Exception as e:
                    set_phase_status(db, nid, "ingest", "failed", error=str(e))
                    click.echo(f"FAIL {nid}: {e}")

        db.close()

    asyncio.run(_run())


@cli.command()
@click.option("--id", "notebook_id", default=None, help="Run all phases for single notebook")
def run(notebook_id: str | None):
    """Run all 4 phases sequentially."""
    ctx = click.get_current_context()
    ctx.invoke(export, notebook_id=notebook_id)
    ctx.invoke(transcribe, notebook_id=notebook_id)
    ctx.invoke(extract, notebook_id=notebook_id)
    ctx.invoke(ingest, notebook_id=notebook_id)


@cli.command()
@click.option("--id", "notebook_id", required=True, help="Notebook ID")
@click.option("--phase", required=True, type=click.Choice(PHASE_ORDER), help="Phase to retry")
def retry(notebook_id: str, phase: str):
    """Retry a failed phase (with prerequisite gating)."""
    db = _get_db()
    try:
        validate_retry(db, notebook_id, phase)
    except ValueError as e:
        raise click.UsageError(str(e))

    affected = attempt_retry(db, notebook_id, phase)
    db.close()

    if affected == 0:
        click.echo(f"Nothing to retry: '{phase}' for {notebook_id} is not in 'failed' state.")
        return

    click.echo(f"Retrying '{phase}' for {notebook_id}...")
    ctx = click.get_current_context()
    phase_commands = {"export": export, "transcribe": transcribe, "extract": extract, "ingest": ingest}
    ctx.invoke(phase_commands[phase], notebook_id=notebook_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_cli.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/ODIN/OSINT
git add services/data-ingestion/notebooklm/cli.py \
       services/data-ingestion/tests/test_nlm_cli.py
git commit -m "feat(data-ingestion): add Click CLI for NotebookLM ingestion"
```

---

## Task 11: Docker Compose — Voxtral Service

**Files:**
- Modify: `~/ODIN/OSINT/docker-compose.yml`

- [ ] **Step 1: Add vllm-voxtral service to docker-compose.yml**

Add the following service block (after the existing `vllm-27b` or `vllm-9b` service):

```yaml
  vllm-voxtral:
    image: vllm/vllm-omni:v0.18.0
    profiles: ["notebooklm"]
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

- [ ] **Step 2: Validate compose syntax**

Run: `cd ~/ODIN/OSINT && docker compose config --quiet`
Expected: No errors

- [ ] **Step 3: Add VOXTRAL_MODEL_PATH to .env.example**

Append:

```
# NotebookLM / Voxtral
VOXTRAL_MODEL_PATH=/home/deadpool-ultra/Voxtral/model
```

- [ ] **Step 4: Commit**

```bash
cd ~/ODIN/OSINT
git add docker-compose.yml .env.example
git commit -m "feat(infra): add vllm-voxtral service for NotebookLM transcription"
```

---

## Task 12: odin.sh Integration

**Files:**
- Modify: `~/ODIN/OSINT/odin.sh`

- [ ] **Step 1: Add `nlm` subcommand block to odin.sh**

Add the following case block inside the main case statement, before the `*` catch-all:

```bash
    nlm)
        subcmd="${2:-help}"
        case "$subcmd" in
            up)
                echo "Starting Voxtral for NotebookLM..."
                docker compose --profile notebooklm up -d vllm-voxtral
                ;;
            down)
                echo "Stopping Voxtral..."
                docker compose stop vllm-voxtral && docker compose rm -f vllm-voxtral
                ;;
            smoke)
                echo "Running Voxtral healthcheck..."
                cd services/data-ingestion && uv run odin-ingest-nlm healthcheck
                ;;
            run)
                echo "Running NotebookLM ingestion pipeline..."
                cd services/data-ingestion && uv run odin-ingest-nlm run
                ;;
            status)
                cd services/data-ingestion && uv run odin-ingest-nlm status
                ;;
            *)
                echo "Usage: odin nlm {up|down|smoke|run|status}"
                ;;
        esac
        ;;
```

- [ ] **Step 2: Test help output**

Run: `cd ~/ODIN/OSINT && bash odin.sh nlm`
Expected: `Usage: odin nlm {up|down|smoke|run|status}`

- [ ] **Step 3: Commit**

```bash
cd ~/ODIN/OSINT
git add odin.sh
git commit -m "feat(odin.sh): add nlm subcommands for NotebookLM pipeline"
```

---

## Task 13: Full Test Suite Verification

- [ ] **Step 1: Run all NLM tests**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest tests/test_nlm_*.py -v --tb=short`
Expected: All tests PASS (schemas: 16, state: 14, transcribe: 5, extract: 7, ingest: 4, cli: 3 = ~49 tests)

- [ ] **Step 2: Run full existing test suite to check no regressions**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run pytest -v --tb=short`
Expected: All existing tests + new NLM tests PASS

- [ ] **Step 3: Lint**

Run: `cd ~/ODIN/OSINT/services/data-ingestion && uv run ruff check notebooklm/ tests/test_nlm_*.py`
Expected: No errors (or fix any found)

- [ ] **Step 4: Final commit if fixes needed**

```bash
cd ~/ODIN/OSINT
git add -u
git commit -m "fix(data-ingestion): lint fixes for NLM pipeline"
```

---

## Dependency Graph

```
Task 1 (schemas) ──┬──→ Task 6 (transcribe) ──→ Task 7 (extract) ──→ Task 8 (ingest) ──→ Task 10 (CLI)
                   │                                    ↑                    ↑
Task 2 (config) ───┘                            Task 5 (prompt)      Task 4 (templates)
                                                                           │
Task 3 (state) ────────────────────────────────────────────────────────────→ Task 10 (CLI)
                                                                                │
Task 9 (export) ──────────────────────────────────────────────────────────────→ Task 10 (CLI)

Task 11 (docker) ── independent
Task 12 (odin.sh) ── independent (depends on Task 11 conceptually)
Task 13 (verification) ── after all
```

**Parallelizable groups:**
- **Group A (parallel):** Task 1, Task 2, Task 3, Task 4, Task 5
- **Group B (parallel after A):** Task 6, Task 9, Task 11
- **Group C (sequential after B):** Task 7 → Task 8 → Task 10
- **Group D (parallel with C):** Task 12
- **Final:** Task 13
