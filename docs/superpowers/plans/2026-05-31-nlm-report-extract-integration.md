# NotebookLM Report Extract/Ingest Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** NotebookLM-Reports als eigenständige Extraktionsquelle (neben dem Audio-Transkript) durch `export → extract → ingest` führen — mit Provenance in Neo4j und Sichtbarkeit im Qdrant-RAG-Pfad.

**Architecture:** Quell-Abstraktion `ExtractionSource(source_kind, source_id, text)` ersetzt das `Transcript`-zentrische Extract. Pro Notebook werden alle Quellen aus `load_sources()` extrahiert (je eine `Extraction`), nach Neo4j (`EXTRACTED_FROM {source_kind, source_id}`) **und** Qdrant (`odin_intel`, 1 Point/Claim, UUIDv5-ID) geschrieben. Phasen-Gating wird von linear auf ein explizites DAG umgestellt; ein Export-Reconciler hält die Phasen mit dem Quell-Inventar konsistent. Eine einmalige Migration überführt Alt-Daten.

**Tech Stack:** Python 3.12, Pydantic v2, SQLite (`phase_status`), Neo4j HTTP-Tx-API, Qdrant (`qdrant_client`), TEI `/embed` (1024-dim), pytest + pytest-asyncio, `uv`.

**Spec:** [`docs/superpowers/specs/2026-05-31-nlm-report-extract-integration-design.md`](../specs/2026-05-31-nlm-report-extract-integration-design.md)

**Etappenschnitt:** Stage 1 Migration/State → Stage 2 Sources/Extract → Stage 3 Graph/Qdrant → Stage 4 CLI/E2E. Jede Stage ist für sich testbar.

**Befehle (aus `services/data-ingestion/`):**
- Tests: `uv run pytest tests/<file> -q`
- Lint: `uvx ruff check <pfad>`

---

## File Structure

| Datei | Verantwortung | Aktion |
|---|---|---|
| `nlm_ingest/state.py` | Phasen-Status, `skipped`-Enum, DAG-`validate_retry`, `reconcile_phases` | Modify |
| `nlm_ingest/migrate.py` | Einmalige Migration: SQLite-Rebuild, Datei-Rename+Backfill, `ingest→pending`, Neo4j-Kanten-Backfill | Create |
| `nlm_ingest/schemas.py` | `ExtractionSource`, `Extraction.source_kind/source_id` | Modify |
| `nlm_ingest/sources.py` | `load_sources()` — extrahierbare Quellen eines Notebooks | Create |
| `nlm_ingest/extract.py` | `extract_with_qwen`/`review_with_claude` auf `ExtractionSource` | Modify |
| `nlm_ingest/export.py` | `audio_status` (absent/failed/downloaded), `report_status` | Modify |
| `nlm_ingest/write_templates.py` | `LINK_CLAIM_DOCUMENT` Rel-Props, `BACKFILL_EXTRACTED_FROM`, Document-Type | Modify |
| `nlm_ingest/ingest_neo4j.py` | `source_kind`/`source_id` durchreichen | Modify |
| `nlm_ingest/ingest_qdrant.py` | Embed→`odin_intel`, UUIDv5-Points, Collection-Preflight | Create |
| `nlm_ingest/cli.py` | `export`-Reconciliation, `extract`/`ingest` Multi-Source + Aggregation, Migrationsaufruf | Modify |
| `tests/test_nlm_*.py` | Tests je Einheit inkl. Migrationstest | Create/Modify |

---

# Stage 1 — Migration / State

## Task 1: Status `skipped` ins Enum + DB-Schema

**Files:**
- Modify: `nlm_ingest/state.py:9-28` (`_SCHEMA`)
- Test: `tests/test_nlm_state.py`

- [ ] **Step 1: Failing test — `skipped` ist als Status erlaubt**

```python
# tests/test_nlm_state.py  (ergänzen)
from nlm_ingest.state import init_db, register_notebook, set_phase_status, get_phase_status

def test_skipped_status_is_accepted(tmp_path):
    db = init_db(tmp_path / "s.db")
    register_notebook(db, "nb1", "T", "RAND")
    set_phase_status(db, "nb1", "transcribe", "skipped")
    assert get_phase_status(db, "nb1", "transcribe") == "skipped"
    db.close()
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_state.py::test_skipped_status_is_accepted -q`
Expected: FAIL — `sqlite3.IntegrityError: CHECK constraint failed` (status `skipped` nicht erlaubt).

- [ ] **Step 3: Enum erweitern**

In `nlm_ingest/state.py` die `status`-CHECK-Zeile in `_SCHEMA` ändern:

```python
    status TEXT CHECK(status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
```

(Frische DBs bekommen das neue Schema direkt; bestehende DBs migriert Task 3.)

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_state.py::test_skipped_status_is_accepted -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/state.py tests/test_nlm_state.py
git commit -m "feat(nlm-state): allow 'skipped' phase status"
```

---

## Task 2: DAG-basiertes `validate_retry`

**Files:**
- Modify: `nlm_ingest/state.py:108-115`
- Test: `tests/test_nlm_state.py`

- [ ] **Step 1: Failing tests — DAG-Regeln**

```python
# tests/test_nlm_state.py  (ergänzen)
import pytest
from nlm_ingest.state import validate_retry

def test_extract_retry_allowed_when_transcribe_failed(tmp_path):
    db = init_db(tmp_path / "s.db")
    register_notebook(db, "nb1", "T", "RAND")
    set_phase_status(db, "nb1", "export", "completed")
    set_phase_status(db, "nb1", "transcribe", "failed")
    # transcribe ist KEINE Vorbedingung von extract -> kein Raise
    validate_retry(db, "nb1", "extract")
    db.close()

def test_skipped_prereq_is_non_blocking(tmp_path):
    db = init_db(tmp_path / "s.db")
    register_notebook(db, "nb1", "T", "RAND")
    set_phase_status(db, "nb1", "export", "completed")
    set_phase_status(db, "nb1", "extract", "skipped")
    validate_retry(db, "nb1", "ingest")  # extract=skipped erfüllt Vorbedingung
    db.close()

def test_ingest_retry_blocked_when_extract_pending(tmp_path):
    db = init_db(tmp_path / "s.db")
    register_notebook(db, "nb1", "T", "RAND")
    set_phase_status(db, "nb1", "export", "completed")
    # extract bleibt 'pending'
    with pytest.raises(ValueError, match="extract"):
        validate_retry(db, "nb1", "ingest")
    db.close()
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_state.py -q -k "retry or prereq"`
Expected: FAIL — `test_extract_retry_allowed_when_transcribe_failed` wirft `ValueError` (linearer Check verlangt transcribe=completed).

- [ ] **Step 3: `validate_retry` auf DAG umstellen**

In `nlm_ingest/state.py` ersetzen:

```python
# Explizites Phasen-DAG statt linearer PHASE_ORDER-Reihenfolge.
# transcribe ist NICHT Vorbedingung von extract (Reports sind audio-unabhängig).
PHASE_PREREQS = {
    "transcribe": ["export"],
    "extract": ["export"],
    "ingest": ["extract"],
}

_SATISFIED = {"completed", "skipped"}


def validate_retry(db, notebook_id, phase):
    for prev_phase in PHASE_PREREQS.get(phase, []):
        status = get_phase_status(db, notebook_id, prev_phase)
        if status not in _SATISFIED:
            raise ValueError(
                f"Cannot retry '{phase}': prerequisite '{prev_phase}' is '{status}'"
            )
```

`PHASE_ORDER` bleibt für `register_notebook`/CLI-Anzeige erhalten.

- [ ] **Step 4: Run — verify PASS (inkl. bestehende state-Tests)**

Run: `uv run pytest tests/test_nlm_state.py -q`
Expected: PASS. Falls ein **bestehender** Test die alte lineare Semantik fixiert (z. B. „extract retry blocked when transcribe pending"), gilt er als überholt: an die neue DAG-Regel anpassen (transcribe ist kein extract-Prereq) und im Commit vermerken.

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/state.py tests/test_nlm_state.py
git commit -m "feat(nlm-state): DAG-based validate_retry (extract no longer gated on transcribe)"
```

---

## Task 3: Lokale Migration — SQLite-Rebuild + Datei-Rename/Backfill + `ingest→pending`

**Files:**
- Create: `nlm_ingest/migrate.py`
- Test: `tests/test_nlm_migrate.py`

**Hintergrund:** Alt-DBs haben den `CHECK` ohne `skipped`; SQLite kann den `CHECK` nicht per `ALTER` erweitern → Tabellen-Rebuild. Alte `extractions/{nid}.json` müssen zu `{nid}.transcript.json` werden + `source_kind/source_id` backfillen; betroffene Notebooks `ingest→pending` (sonst nie nach Qdrant).

- [ ] **Step 1: Failing test — lokale Migration**

```python
# tests/test_nlm_migrate.py
import json
import sqlite3
from pathlib import Path

from nlm_ingest.migrate import migrate_local

_OLD_SCHEMA = """
CREATE TABLE notebooks (id TEXT PRIMARY KEY, title TEXT, source_name TEXT, created_at TEXT);
CREATE TABLE phase_status (
    notebook_id TEXT, phase TEXT,
    status TEXT CHECK(status IN ('pending','running','completed','failed')),
    error TEXT, started_at TEXT, finished_at TEXT, retry_count INTEGER DEFAULT 0,
    updated_at TEXT, PRIMARY KEY (notebook_id, phase)
);
"""

def _old_db(path):
    db = sqlite3.connect(str(path))
    db.executescript(_OLD_SCHEMA)
    db.execute("INSERT INTO notebooks VALUES ('nb1','T','RAND','x')")
    for ph, st in [("export","completed"),("transcribe","completed"),
                   ("extract","completed"),("ingest","completed")]:
        db.execute("INSERT INTO phase_status (notebook_id,phase,status) VALUES (?,?,?)",
                   ("nb1", ph, st))
    db.commit()
    return db

def test_migrate_local_rebuilds_and_reactivates_ingest(tmp_path):
    db_path = tmp_path / "state.db"
    db = _old_db(db_path); db.close()

    data_dir = tmp_path / "data"
    (data_dir / "extractions").mkdir(parents=True)
    old_extraction = {
        "notebook_id": "nb1", "entities": [], "relations": [], "claims": [],
        "extraction_model": "qwen", "prompt_version": "v1",
    }
    (data_dir / "extractions" / "nb1.json").write_text(json.dumps(old_extraction))

    db = sqlite3.connect(str(db_path))
    migrate_local(db, data_dir)

    # skipped jetzt erlaubt
    db.execute("UPDATE phase_status SET status='skipped' WHERE notebook_id='nb1' AND phase='transcribe'")
    # Datei umbenannt + backfilled
    new = json.loads((data_dir / "extractions" / "nb1.transcript.json").read_text())
    assert new["source_kind"] == "transcript" and new["source_id"] == "transcript"
    assert not (data_dir / "extractions" / "nb1.json").exists()
    # ingest reaktiviert
    row = db.execute("SELECT status FROM phase_status WHERE notebook_id='nb1' AND phase='ingest'").fetchone()
    assert row[0] == "pending"
    db.close()

def test_migrate_local_is_idempotent(tmp_path):
    db_path = tmp_path / "state.db"; db = _old_db(db_path); db.close()
    data_dir = tmp_path / "data"; (data_dir / "extractions").mkdir(parents=True)
    db = sqlite3.connect(str(db_path))
    migrate_local(db, data_dir)
    migrate_local(db, data_dir)  # zweiter Lauf darf nicht werfen
    db.close()
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_migrate.py -q`
Expected: FAIL — `ModuleNotFoundError: nlm_ingest.migrate`.

- [ ] **Step 3: `migrate.py` (lokaler Teil)**

```python
# nlm_ingest/migrate.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import structlog

log = structlog.get_logger()

_NEW_PHASE_STATUS = """
CREATE TABLE phase_status_new (
    notebook_id TEXT REFERENCES notebooks(id),
    phase TEXT CHECK(phase IN ('export', 'transcribe', 'extract', 'ingest')),
    status TEXT CHECK(status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    retry_count INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (notebook_id, phase)
);
"""


def _needs_status_rebuild(db: sqlite3.Connection) -> bool:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='phase_status'"
    ).fetchone()
    return bool(row) and "skipped" not in row[0]


def migrate_local(db: sqlite3.Connection, data_dir: Path) -> None:
    """Idempotente lokale Migration: SQLite-Rebuild + Extraktions-Datei-Rename/Backfill
    + ingest-Reaktivierung. Neo4j wird NICHT berührt (siehe migrate_neo4j_edges)."""
    # 1. SQLite phase_status rebuild (CHECK kann nicht per ALTER erweitert werden)
    if _needs_status_rebuild(db):
        db.execute("BEGIN")
        db.executescript(_NEW_PHASE_STATUS)
        db.execute(
            "INSERT INTO phase_status_new SELECT notebook_id, phase, status, error, "
            "started_at, finished_at, retry_count, updated_at FROM phase_status"
        )
        db.execute("DROP TABLE phase_status")
        db.execute("ALTER TABLE phase_status_new RENAME TO phase_status")
        db.commit()
        log.info("migrate_sqlite_rebuilt")

    # 2. Alte Extraktionsdateien {nid}.json -> {nid}.transcript.json + Backfill
    ext_dir = data_dir / "extractions"
    reactivated: list[str] = []
    if ext_dir.exists():
        for old in sorted(ext_dir.glob("*.json")):
            # neue Dateien tragen das Muster {nid}.{source_id}.json -> Punkte im Stamm.
            # Alt-Dateien sind {nid}.json (genau ein Segment vor .json).
            if old.stem.count(".") > 0:
                continue
            nid = old.stem
            data = json.loads(old.read_text())
            data.setdefault("source_kind", "transcript")
            data.setdefault("source_id", "transcript")
            new = ext_dir / f"{nid}.transcript.json"
            new.write_text(json.dumps(data, indent=2))
            old.unlink()
            reactivated.append(nid)
            log.info("migrate_extraction_renamed", notebook_id=nid)

    # 3. ingest reaktivieren (damit der neue Qdrant-Write nachgeholt wird)
    for nid in reactivated:
        db.execute(
            "UPDATE phase_status SET status='pending', updated_at=datetime('now') "
            "WHERE notebook_id=? AND phase='ingest' AND status='completed'",
            (nid,),
        )
    db.commit()
    if reactivated:
        log.info("migrate_ingest_reactivated", count=len(reactivated))
```

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_migrate.py -q`
Expected: PASS (beide Tests).

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/migrate.py tests/test_nlm_migrate.py
git commit -m "feat(nlm-migrate): local migration — sqlite rebuild, extraction rename/backfill, ingest reactivation"
```

---

## Task 4: Neo4j-Kanten-Backfill (separat, parametergebunden)

**Files:**
- Modify: `nlm_ingest/write_templates.py` (neues Template `BACKFILL_EXTRACTED_FROM`)
- Modify: `nlm_ingest/migrate.py` (`migrate_neo4j_edges`)
- Test: `tests/test_nlm_migrate.py`

- [ ] **Step 1: Failing test — Backfill-Statement (gescopt, parametergebunden)**

```python
# tests/test_nlm_migrate.py  (ergänzen)
from nlm_ingest.migrate import build_neo4j_backfill_statement

def test_backfill_statement_is_scoped_and_parametrized():
    stmt = build_neo4j_backfill_statement()
    cypher = stmt["statement"]
    assert "r.source_kind IS NULL" in cypher
    assert "r.source_id IS NULL" in cypher
    assert "d.notebook_id IS NOT NULL" in cypher
    # parametergebunden, keine Literale
    assert "$source_kind" in cypher and "$source_id" in cypher
    assert "'transcript'" not in cypher
    assert stmt["parameters"] == {"source_kind": "transcript", "source_id": "transcript"}
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_migrate.py::test_backfill_statement_is_scoped_and_parametrized -q`
Expected: FAIL — `ImportError: build_neo4j_backfill_statement`.

- [ ] **Step 3: Template + Builder**

In `nlm_ingest/write_templates.py` ergänzen:

```python
BACKFILL_EXTRACTED_FROM = """
MATCH (:Claim)-[r:EXTRACTED_FROM]->(d:Document)
WHERE d.notebook_id IS NOT NULL
  AND r.source_kind IS NULL
  AND r.source_id IS NULL
SET r.source_kind = $source_kind, r.source_id = $source_id
"""
```

In `nlm_ingest/migrate.py` ergänzen:

```python
from nlm_ingest.write_templates import BACKFILL_EXTRACTED_FROM


def build_neo4j_backfill_statement() -> dict:
    """Deterministisches, gescoptes Backfill alter property-loser NLM-Kanten.
    Rührt fremde EXTRACTED_FROM-Kanten (ohne Document.notebook_id) nicht an."""
    return {
        "statement": BACKFILL_EXTRACTED_FROM,
        "parameters": {"source_kind": "transcript", "source_id": "transcript"},
    }
```

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_migrate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/write_templates.py nlm_ingest/migrate.py tests/test_nlm_migrate.py
git commit -m "feat(nlm-migrate): scoped, parametrized Neo4j EXTRACTED_FROM backfill"
```

---

# Stage 2 — Sources / Extract

## Task 5: `ExtractionSource` + `Extraction`-Provenance-Felder

**Files:**
- Modify: `nlm_ingest/schemas.py:100-106`
- Test: `tests/test_nlm_schemas.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_nlm_schemas.py  (ergänzen)
from nlm_ingest.schemas import ExtractionSource, Extraction

def test_extraction_source_fields():
    s = ExtractionSource(notebook_id="nb1", source_id="r1", source_kind="report", text="x")
    assert s.source_kind == "report" and s.source_id == "r1"

def test_extraction_requires_provenance():
    e = Extraction(notebook_id="nb1", entities=[], relations=[], claims=[],
                   extraction_model="qwen", prompt_version="v1",
                   source_kind="transcript", source_id="transcript")
    assert e.source_kind == "transcript"
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_schemas.py -q -k "source or provenance"`
Expected: FAIL — `ImportError: ExtractionSource` / `ValidationError` (Felder fehlen).

- [ ] **Step 3: Schemas erweitern**

In `nlm_ingest/schemas.py` (Imports: `Literal` aus `typing` ist dort bereits in Verwendung für die `*Type`-Aliase; sonst ergänzen):

```python
class ExtractionSource(BaseModel):
    notebook_id: str
    source_id: str
    source_kind: Literal["transcript", "report"]
    text: str
```

und `Extraction` um zwei Felder erweitern:

```python
class Extraction(BaseModel):
    notebook_id: str
    entities: list[Entity]
    relations: list[Relation]
    claims: list[Claim]
    extraction_model: str
    prompt_version: str
    source_kind: Literal["transcript", "report"]
    source_id: str
```

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_schemas.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/schemas.py tests/test_nlm_schemas.py
git commit -m "feat(nlm-schemas): ExtractionSource + Extraction provenance fields"
```

---

## Task 6: `sources.load_sources()`

**Files:**
- Create: `nlm_ingest/sources.py`
- Test: `tests/test_nlm_sources.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_nlm_sources.py
import json
from pathlib import Path

from nlm_ingest.sources import load_sources


def _write_transcript(data_dir, nid, text):
    p = data_dir / "transcripts" / f"{nid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "notebook_id": nid, "duration_seconds": 1.0, "language": "en",
        "segments": [], "full_text": text,
    }))


def _write_report(data_dir, nid, artifact_id, text):
    p = data_dir / "notebooks" / nid / f"report_{artifact_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_load_sources_transcript_and_reports(tmp_path):
    _write_transcript(tmp_path, "nb1", "podcast text")
    _write_report(tmp_path, "nb1", "rep-a", "report A")
    _write_report(tmp_path, "nb1", "rep-b", "report B")

    sources = load_sources(tmp_path, "nb1")

    kinds = [(s.source_kind, s.source_id) for s in sources]
    assert ("transcript", "transcript") in kinds
    assert ("report", "rep-a") in kinds
    assert ("report", "rep-b") in kinds
    transcript = next(s for s in sources if s.source_kind == "transcript")
    assert transcript.text == "podcast text"


def test_load_sources_empty_when_nothing(tmp_path):
    (tmp_path / "notebooks" / "nb1").mkdir(parents=True)
    assert load_sources(tmp_path, "nb1") == []
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_sources.py -q`
Expected: FAIL — `ModuleNotFoundError: nlm_ingest.sources`.

- [ ] **Step 3: `sources.py`**

```python
# nlm_ingest/sources.py
from __future__ import annotations

from pathlib import Path

from nlm_ingest.schemas import ExtractionSource, Transcript


def load_sources(data_dir: Path, notebook_id: str) -> list[ExtractionSource]:
    """Alle auf der Platte vorhandenen, extrahierbaren Quellen eines Notebooks.

    Deterministische Reihenfolge: Transkript zuerst, Reports nach source_id sortiert.
    """
    sources: list[ExtractionSource] = []

    transcript_path = data_dir / "transcripts" / f"{notebook_id}.json"
    if transcript_path.exists():
        transcript = Transcript.model_validate_json(transcript_path.read_text())
        sources.append(ExtractionSource(
            notebook_id=notebook_id,
            source_id="transcript",
            source_kind="transcript",
            text=transcript.full_text,
        ))

    nb_dir = data_dir / "notebooks" / notebook_id
    if nb_dir.exists():
        for report in sorted(nb_dir.glob("report_*.md")):
            artifact_id = report.stem[len("report_"):]
            sources.append(ExtractionSource(
                notebook_id=notebook_id,
                source_id=artifact_id,
                source_kind="report",
                text=report.read_text(),
            ))

    return sources
```

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_sources.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/sources.py tests/test_nlm_sources.py
git commit -m "feat(nlm-sources): load_sources for transcript + reports"
```

---

## Task 7: Extract auf `ExtractionSource` umstellen

**Files:**
- Modify: `nlm_ingest/extract.py:39-90` (`extract_with_qwen`), `:93-147` (`review_with_claude`)
- Test: `tests/test_nlm_extract.py`

- [ ] **Step 1: Failing test — `extract_with_qwen` nimmt `ExtractionSource`, setzt Provenance**

```python
# tests/test_nlm_extract.py  (ergänzen)
from unittest.mock import AsyncMock
import httpx
import pytest

from nlm_ingest.extract import extract_with_qwen
from nlm_ingest.schemas import ExtractionSource

_REQ = httpx.Request("POST", "http://x/v1/chat/completions")

@pytest.mark.asyncio
async def test_extract_with_qwen_sets_provenance():
    body = {"choices": [{"message": {"content": '{"entities": [], "relations": [], "claims": []}'}}]}
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(200, json=body, request=_REQ)

    source = ExtractionSource(notebook_id="nb1", source_id="rep-a",
                              source_kind="report", text="report text")
    result = await extract_with_qwen(
        source=source, metadata={"source_name": "RAND", "title": "T"},
        client=client, vllm_url="http://x", vllm_model="qwen",
    )
    assert result.source_kind == "report"
    assert result.source_id == "rep-a"
    assert result.notebook_id == "nb1"
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_extract.py::test_extract_with_qwen_sets_provenance -q`
Expected: FAIL — `TypeError` (Signatur erwartet `transcript`, nicht `source`).

- [ ] **Step 3: `extract.py` refactoren**

In `nlm_ingest/extract.py`:
- Import anpassen: `from nlm_ingest.schemas import (Claim, Entity, Extraction, ExtractionSource, Relation)` (`Transcript` darf bleiben, falls noch von `review_with_claude` genutzt — hier ebenfalls auf `source` umgestellt).
- `extract_with_qwen`-Signatur und -Rumpf:

```python
async def extract_with_qwen(
    source: ExtractionSource,
    metadata: dict,
    client: httpx.AsyncClient,
    vllm_url: str,
    vllm_model: str,
    prompt_version: str = "v1",
) -> Extraction:
    prompt_template = load_prompt(prompt_version)
    prompt = (
        prompt_template
        .replace("{source_name}", metadata.get("source_name", "unknown"))
        .replace("{title}", metadata.get("title", "untitled"))
        .replace("{transcript_text}", source.text[:16_000])
    )

    payload = {
        "model": vllm_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4000,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    response = await client.post(f"{vllm_url}/v1/chat/completions", json=payload, timeout=120.0)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(content)

    return Extraction(
        notebook_id=source.notebook_id,
        entities=[Entity(**e) for e in data.get("entities", [])],
        relations=[Relation(**r) for r in data.get("relations", [])],
        claims=[Claim(**c) for c in data.get("claims", [])],
        extraction_model=vllm_model,
        prompt_version=prompt_version,
        source_kind=source.source_kind,
        source_id=source.source_id,
    )
```

- `review_with_claude`-Signatur: `transcript: Transcript` → `source: ExtractionSource`; im Rumpf `transcript.full_text` → `source.text` (zwei Stellen: `extract_context(source.text, ...)` und der Prompt-Hinweis „think-tank podcast transcript" → „think-tank source").

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_extract.py -q`
Expected: PASS. Bestehende `test_nlm_extract`-Tests, die `transcript=`/`Transcript` übergeben, auf `ExtractionSource` umstellen (gleiche Felder, `source.text` = bisheriger `full_text`).

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/extract.py tests/test_nlm_extract.py
git commit -m "refactor(nlm-extract): extract_with_qwen/review_with_claude take ExtractionSource"
```

---

## Task 8: Export — `audio_status` + `report_status`

**Files:**
- Modify: `nlm_ingest/export.py` (`_export_audio`, `_export_reports`, `export_all`)
- Test: `tests/test_nlm_export.py`

**Vertrag:** `export_all`-Dicts erhalten `audio_status: "downloaded"|"absent"|"failed"` und `report_status: "complete"|"failed"`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_nlm_export.py  (ergänzen — nutzt vorhandene _make_client/_patch_client/_notebook/_artifact)

@pytest.mark.asyncio
async def test_audio_status_absent_when_no_audio_artifact(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], reports=[_artifact("r1", completed=True)])
    client.artifacts.list_audio = AsyncMock(return_value=[])          # leer
    _patch_client(monkeypatch, client)
    results = await export_all(tmp_path)
    assert results[0]["audio_status"] == "absent"
    assert results[0]["report_status"] == "complete"

@pytest.mark.asyncio
async def test_audio_status_failed_when_list_audio_raises(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], reports=[_artifact("r1", completed=True)])
    client.artifacts.list_audio = AsyncMock(side_effect=RuntimeError("api down"))
    _patch_client(monkeypatch, client)
    results = await export_all(tmp_path)
    assert results[0]["audio_status"] == "failed"     # NICHT absent

@pytest.mark.asyncio
async def test_report_status_failed_when_completed_report_download_fails(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], slide_decks=None,
                          reports=[_artifact("r1", completed=True)], write_audio=True)
    client.artifacts.list_audio = AsyncMock(return_value=[_artifact("a1", completed=True)])
    client.artifacts.download_report = AsyncMock(side_effect=RuntimeError("dl fail"))
    _patch_client(monkeypatch, client)
    results = await export_all(tmp_path)
    assert results[0]["report_status"] == "failed"
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_export.py -q -k "audio_status or report_status"`
Expected: FAIL — Key `audio_status`/`report_status` fehlt.

- [ ] **Step 3: `export.py` erweitern**

`_export_audio` gibt `(audio_path, audio_status)` zurück; vor dem Download `list_audio` prüfen:

```python
async def _export_audio(client, notebook_id: str, nb_dir: Path):
    """Returns (Path|None, status) with status in {'downloaded','absent','failed'}."""
    audio_path = nb_dir / "podcast.mp4"
    if audio_path.exists():
        return audio_path, "downloaded"
    try:
        audio_arts = await client.artifacts.list_audio(notebook_id)
    except Exception:
        log.warning("export_list_audio_failed", notebook_id=notebook_id, exc_info=True)
        return None, "failed"
    if not audio_arts:
        return None, "absent"
    try:
        await client.artifacts.download_audio(notebook_id, str(audio_path))
        size_mb = audio_path.stat().st_size / 1e6
        log.info("export_audio", notebook_id=notebook_id, size_mb=round(size_mb, 1))
        return audio_path, "downloaded"
    except Exception:
        log.warning("export_audio_failed", notebook_id=notebook_id, exc_info=True)
        return None, "failed"
```

`_export_reports` gibt `(paths, report_status)` zurück:

```python
async def _export_reports(client, notebook_id: str, nb_dir: Path):
    """Returns (list[str], status) with status in {'complete','failed'}."""
    try:
        reports = await client.artifacts.list_reports(notebook_id)
    except Exception:
        log.warning("export_reports_list_failed", notebook_id=notebook_id, exc_info=True)
        return [], "failed"
    paths: list[str] = []
    status = "complete"
    for report in [r for r in reports if r.is_completed]:
        out = nb_dir / f"report_{report.id}.md"
        if out.exists():
            paths.append(str(out)); continue
        try:
            await client.artifacts.download_report(notebook_id, str(out), artifact_id=report.id)
            paths.append(str(out))
            log.info("export_report", notebook_id=notebook_id, artifact_id=report.id)
        except Exception:
            log.warning("export_report_failed", notebook_id=notebook_id, artifact_id=report.id, exc_info=True)
            status = "failed"
    return paths, status
```

In `export_all` die Aufrufe + Dict anpassen:

```python
            audio_path, audio_status = await _export_audio(client, nb.id, nb_dir)
            slide_deck_paths = await _export_slide_decks(client, nb.id, nb_dir)
            report_paths, report_status = await _export_reports(client, nb.id, nb_dir)

            if not (audio_path or slide_deck_paths or report_paths
                    or audio_status == "absent"):
                # nichts geholt UND auch kein definitiv-leeres Audio -> nicht registrieren
                # (audio_status 'absent' deutet auf ein evtl. slide-only Notebook,
                #  das registriert werden soll, damit Reconciliation es als skipped führt)
                if audio_status != "failed" and report_status != "failed":
                    continue

            exported.append({
                "notebook_id": nb.id,
                "title": meta["title"],
                "source_name": meta["source_name"],
                "audio_path": str(audio_path) if audio_path else None,
                "audio_status": audio_status,
                "report_status": report_status,
                "slide_deck_paths": slide_deck_paths,
                "report_paths": report_paths,
            })
```

(Hinweis: Das `_make_client`-Test-Helper muss `list_audio` bereitstellen — in Step 1 wird es je Test gesetzt; ergänze im Helper einen Default `client.artifacts.list_audio = AsyncMock(return_value=[])`, damit Bestands-Tests nicht brechen.)

- [ ] **Step 4: Run — verify PASS (gesamte export-Suite)**

Run: `uv run pytest tests/test_nlm_export.py -q`
Expected: PASS. Bestehende Tests ggf. um den `list_audio`-Default im Helper ergänzen.

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/export.py tests/test_nlm_export.py
git commit -m "feat(nlm-export): audio_status (absent/failed/downloaded) + report_status"
```

---

## Task 9: `reconcile_phases()`

**Files:**
- Modify: `nlm_ingest/state.py` (neue Funktion `reconcile_phases`)
- Test: `tests/test_nlm_state.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_nlm_state.py  (ergänzen)
import json
from nlm_ingest.state import reconcile_phases, set_phase_status, get_phase_status

def _seed(db, data_dir, nid="nb1"):
    register_notebook(db, nid, "T", "RAND")
    for ph in ("export","transcribe","extract","ingest"):
        set_phase_status(db, nid, ph, "completed")

def _report(data_dir, nid, aid, text="r"):
    p = data_dir / "notebooks" / nid / f"report_{aid}.md"
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)

def test_reconcile_new_report_resets_extract_ingest(tmp_path):
    db = init_db(tmp_path / "s.db"); _seed(db, tmp_path)
    _report(tmp_path, "nb1", "rNEW")                      # neue Quelle, keine Extraktionsdatei
    reconcile_phases(db, tmp_path, "nb1", audio_status="downloaded", report_status="complete")
    assert get_phase_status(db, "nb1", "extract") == "pending"
    assert get_phase_status(db, "nb1", "ingest") == "pending"
    db.close()

def test_reconcile_slide_only_skips_all(tmp_path):
    db = init_db(tmp_path / "s.db"); register_notebook(db, "nb1", "T", "RAND")
    reconcile_phases(db, tmp_path, "nb1", audio_status="absent", report_status="complete")
    for ph in ("transcribe","extract","ingest"):
        assert get_phase_status(db, "nb1", ph) == "skipped"
    db.close()

def test_reconcile_no_skip_when_report_failed(tmp_path):
    db = init_db(tmp_path / "s.db"); register_notebook(db, "nb1", "T", "RAND")
    reconcile_phases(db, tmp_path, "nb1", audio_status="absent", report_status="failed")
    assert get_phase_status(db, "nb1", "extract") != "skipped"
    db.close()

def test_reconcile_audio_after_skip_resets_transcribe(tmp_path):
    db = init_db(tmp_path / "s.db"); register_notebook(db, "nb1", "T", "RAND")
    set_phase_status(db, "nb1", "transcribe", "skipped")
    reconcile_phases(db, tmp_path, "nb1", audio_status="downloaded", report_status="complete")
    assert get_phase_status(db, "nb1", "transcribe") == "pending"
    db.close()
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_state.py -q -k reconcile`
Expected: FAIL — `ImportError: reconcile_phases`.

- [ ] **Step 3: `reconcile_phases` in `state.py`**

```python
def _valid_extraction_exists(data_dir, notebook_id, source_id) -> bool:
    from nlm_ingest.schemas import Extraction  # lokaler Import, vermeidet Zyklen
    p = data_dir / "extractions" / f"{notebook_id}.{source_id}.json"
    if not p.exists():
        return False
    try:
        Extraction.model_validate_json(p.read_text())
        return True
    except Exception:
        return False


def reconcile_phases(db, data_dir, notebook_id, *, audio_status, report_status):
    """Hält extract/ingest/transcribe mit dem Quell-Inventar (load_sources) konsistent.

    audio_status ∈ {downloaded,absent,failed}; report_status ∈ {complete,failed}.
    """
    from nlm_ingest.sources import load_sources  # lokaler Import, vermeidet Zyklen

    # 1. Audio erschien nach skipped -> transcribe reaktivieren
    if audio_status in ("downloaded", "failed") and get_phase_status(db, notebook_id, "transcribe") == "skipped":
        set_phase_status(db, notebook_id, "transcribe", "pending")

    sources = load_sources(data_dir, notebook_id)

    # 3. Terminal skipped: keine extrahierbare Quelle UND kein Audio UND Reports vollständig
    if not sources and audio_status == "absent" and report_status == "complete":
        for ph in ("transcribe", "extract", "ingest"):
            set_phase_status(db, notebook_id, ph, "skipped")
        return

    # 2. Fehlt für eine Quelle eine valide Extraktionsdatei -> extract/ingest reaktivieren
    needs_extract = any(
        not _valid_extraction_exists(data_dir, notebook_id, s.source_id) for s in sources
    )
    if needs_extract:
        for ph in ("extract", "ingest"):
            if get_phase_status(db, notebook_id, ph) not in ("running",):
                set_phase_status(db, notebook_id, ph, "pending")
```

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_state.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/state.py tests/test_nlm_state.py
git commit -m "feat(nlm-state): reconcile_phases keyed on load_sources + report_status"
```

---

# Stage 3 — Graph / Qdrant

## Task 10: Provenance auf der `EXTRACTED_FROM`-Kante

**Files:**
- Modify: `nlm_ingest/write_templates.py:20-26` (Document-Type), `:58-62` (`LINK_CLAIM_DOCUMENT`)
- Modify: `nlm_ingest/ingest_neo4j.py:36-44` (Document params), `:110-117` (Link params)
- Test: `tests/test_nlm_ingest.py`

- [ ] **Step 1: Failing test — Link-Statement trägt source_kind/source_id**

```python
# tests/test_nlm_ingest.py  (ergänzen)
from nlm_ingest.ingest_neo4j import _build_statements
from nlm_ingest.schemas import Extraction, Claim

def _extraction(**kw):
    base = dict(notebook_id="nb1", entities=[], relations=[],
                claims=[Claim(statement="X happened", type="event_claim",
                              polarity="positive", entities_involved=[],
                              confidence=0.9, temporal_scope="2026")],
                extraction_model="qwen", prompt_version="v1",
                source_kind="report", source_id="rep-a")
    base.update(kw)
    return Extraction(**base)

def test_link_claim_document_carries_provenance():
    stmts = _build_statements(_extraction(), "RAND")
    link = [s for s in stmts if "EXTRACTED_FROM" in s["statement"]][0]
    assert "$source_kind" in link["statement"] and "$source_id" in link["statement"]
    assert "{source_kind: $source_kind, source_id: $source_id}" in link["statement"]
    assert link["parameters"]["source_kind"] == "report"
    assert link["parameters"]["source_id"] == "rep-a"
```

*(Claim-Enum-Werte wie `type="event_claim"` ggf. an die echten `ClaimType`/`ClaimPolarity`-Literale in `schemas.py` anpassen — vor dem Schreiben kurz dort nachsehen.)*

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_ingest.py::test_link_claim_document_carries_provenance -q`
Expected: FAIL — Template hat noch keine Rel-Props.

- [ ] **Step 3: Template + Builder anpassen**

`nlm_ingest/write_templates.py`:

```python
LINK_CLAIM_DOCUMENT = """
MATCH (c:Claim {statement_hash: $statement_hash})
MATCH (d:Document {notebook_id: $notebook_id})
MERGE (c)-[r:EXTRACTED_FROM {source_kind: $source_kind, source_id: $source_id}]->(d)
"""
```

`nlm_ingest/ingest_neo4j.py` — Document-Type notebook-neutral (`:36-44`):

```python
    statements.append({
        "statement": UPSERT_DOCUMENT,
        "parameters": {
            "notebook_id": extraction.notebook_id,
            "title": f"NLM: {source_name}",
            "source": source_name,
            "type": "notebooklm",
        },
    })
```

und der Link-Block (`:110-117`):

```python
        statements.append({
            "statement": LINK_CLAIM_DOCUMENT,
            "parameters": {
                "statement_hash": stmt_hash,
                "notebook_id": extraction.notebook_id,
                "source_kind": extraction.source_kind,
                "source_id": extraction.source_id,
            },
        })
```

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_ingest.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/write_templates.py nlm_ingest/ingest_neo4j.py tests/test_nlm_ingest.py
git commit -m "feat(nlm-ingest): EXTRACTED_FROM carries source_kind/source_id provenance"
```

---

## Task 11: `ingest_qdrant.py` — Embed pro Claim + Preflight

**Files:**
- Create: `nlm_ingest/ingest_qdrant.py`
- Test: `tests/test_nlm_ingest_qdrant.py`

- [ ] **Step 1: Failing tests — Point-Bau (reine Funktion, ohne Netz)**

```python
# tests/test_nlm_ingest_qdrant.py
from nlm_ingest.ingest_qdrant import build_claim_points, _point_id
from nlm_ingest.schemas import Extraction, Claim

def _claim(stmt, conf=0.9):
    return Claim(statement=stmt, type="event_claim", polarity="positive",
                 entities_involved=["NATO"], confidence=conf, temporal_scope="2026")

def _extraction(**kw):
    base = dict(notebook_id="nb1", entities=[], relations=[],
                claims=[_claim("NATO expanded")],
                extraction_model="qwen", prompt_version="v1",
                source_kind="report", source_id="rep-a")
    base.update(kw); return Extraction(**base)

def test_point_id_is_source_specific_and_deterministic():
    a = _point_id("nb1", "report", "rep-a", "hash1")
    b = _point_id("nb1", "transcript", "transcript", "hash1")
    assert a == _point_id("nb1", "report", "rep-a", "hash1")   # deterministisch
    assert a != b                                              # quell-spezifisch

def test_build_points_payload(monkeypatch):
    vectors = {"NATO expanded": [0.1] * 1024}
    points = build_claim_points(_extraction(), notebook_title="T",
                                embed=lambda text: vectors[text])
    assert len(points) == 1
    p = points[0].payload
    assert p["content"] == "NATO expanded"
    assert p["source_kind"] == "report" and p["source_id"] == "rep-a"
    assert p["region"] == "N/A"
    assert p["entities"] == [{"name": "NATO"}]
    assert "claim_hash" in p and "content_hash" in p and "ingested_at" in p

def test_rejected_claims_are_skipped():
    points = build_claim_points(_extraction(claims=[_claim("low", conf=0.0)]),
                                notebook_title="T", embed=lambda t: [0.0]*1024)
    assert points == []
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_ingest_qdrant.py -q`
Expected: FAIL — `ModuleNotFoundError: nlm_ingest.ingest_qdrant`.

- [ ] **Step 3: `ingest_qdrant.py`**

```python
# nlm_ingest/ingest_qdrant.py
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Callable

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from nlm_ingest.schemas import Extraction, claim_hash
from qdrant_doctor.schema import validate_collection_schema

log = structlog.get_logger()

# Projektfeste Namespace-UUID (deterministisch aus URL-Namespace abgeleitet).
NLM_QDRANT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "odin/nlm/odin_intel")


def _point_id(notebook_id: str, source_kind: str, source_id: str, statement_hash: str) -> str:
    name = f"{notebook_id}|{source_kind}|{source_id}|{statement_hash}"
    return str(uuid.uuid5(NLM_QDRANT_NAMESPACE, name))


def build_claim_points(
    extraction: Extraction,
    notebook_title: str,
    embed: Callable[[str], list[float]],
    *,
    source_name: str = "unknown",
    now_iso: str | None = None,
) -> list[PointStruct]:
    """Ein Point je nicht-abgelehntem Claim. `embed` mappt Text -> Vektor."""
    ts = now_iso or datetime.now(UTC).isoformat()
    points: list[PointStruct] = []
    for claim in extraction.claims:
        if claim.confidence <= 0.0:
            continue
        chash = claim_hash(claim.statement)
        payload = {
            "title": notebook_title,
            "source": source_name,
            "region": "N/A",
            "content": claim.statement,
            "entities": [{"name": n} for n in claim.entities_involved],
            "notebook_id": extraction.notebook_id,
            "source_kind": extraction.source_kind,
            "source_id": extraction.source_id,
            "claim_type": str(claim.type),
            "claim_hash": chash,
            "content_hash": chash,
            "ingested_at": ts,
            "ingested_epoch": datetime.fromisoformat(ts).timestamp(),
        }
        points.append(PointStruct(
            id=_point_id(extraction.notebook_id, extraction.source_kind, extraction.source_id, chash),
            vector=embed(claim.statement),
            payload=payload,
        ))
    return points


async def ensure_collection(qdrant: QdrantClient, collection: str, dim: int) -> None:
    """Collection anlegen falls fehlend, sonst Schema vor dem Write validieren."""
    collections = await asyncio.to_thread(lambda: qdrant.get_collections().collections)
    if not any(c.name == collection for c in collections):
        await asyncio.to_thread(lambda: qdrant.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        ))
        log.info("nlm_qdrant_collection_created", collection=collection)
    else:
        info = await asyncio.to_thread(lambda: qdrant.get_collection(collection))
        validate_collection_schema(info, enable_hybrid=False)


async def ingest_to_qdrant(qdrant: QdrantClient, collection: str, points: list[PointStruct]) -> None:
    if not points:
        return
    await asyncio.to_thread(qdrant.upsert, collection_name=collection, points=points)
    log.info("nlm_qdrant_upserted", count=len(points))
```

*(Falls `validate_collection_schema` eine andere Signatur hat — vor dem Schreiben in [`qdrant_doctor/schema.py`](../../../services/data-ingestion/qdrant_doctor/schema.py) prüfen; in `feeds/base.py` wird es als `validate_collection_schema(info, enable_hybrid=...)` aufgerufen.)*

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_ingest_qdrant.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/ingest_qdrant.py tests/test_nlm_ingest_qdrant.py
git commit -m "feat(nlm-qdrant): per-claim embedding with UUIDv5 ids + collection preflight"
```

---

# Stage 4 — CLI / E2E

## Task 12: Extract-CLI — Multi-Source, Idempotenz, Aggregation

**Files:**
- Modify: `nlm_ingest/cli.py` (`extract`-Command, `:178-243`)
- Test: `tests/test_nlm_cli_wiring.py`

**Verhalten:** Target = Notebook mit nicht-leerem `load_sources()` und `extract ∈ {pending,failed,running}`. Pro Quelle nur extrahieren, wenn keine valide `extractions/{nid}.{source_id}.json` existiert. `extract=completed` nur, wenn am Ende für **alle** Quellen eine valide Datei vorliegt, sonst `failed`.

- [ ] **Step 1: Failing test — Idempotenz-Helper auslagern + testen**

Da der CLI-Code I/O-lastig ist, die Kernlogik in eine reine, testbare Funktion ziehen:

```python
# tests/test_nlm_cli_wiring.py  (ergänzen)
from nlm_ingest.cli import _sources_needing_extract
from nlm_ingest.schemas import ExtractionSource
import json

def _src(nid, sid, kind):
    return ExtractionSource(notebook_id=nid, source_id=sid, source_kind=kind, text="t")

def test_sources_needing_extract_skips_valid_files(tmp_path):
    ext = tmp_path / "extractions"; ext.mkdir()
    valid = {"notebook_id":"nb1","entities":[],"relations":[],"claims":[],
             "extraction_model":"q","prompt_version":"v1",
             "source_kind":"report","source_id":"r1"}
    (ext / "nb1.r1.json").write_text(json.dumps(valid))
    sources = [_src("nb1","r1","report"), _src("nb1","r2","report")]
    todo = _sources_needing_extract(tmp_path, sources)
    assert [s.source_id for s in todo] == ["r2"]   # r1 hat valide Datei
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_cli_wiring.py::test_sources_needing_extract_skips_valid_files -q`
Expected: FAIL — `ImportError: _sources_needing_extract`.

- [ ] **Step 3: Helper + CLI-Refactor**

In `nlm_ingest/cli.py` Helper ergänzen und den `extract`-Command umbauen:

```python
def _sources_needing_extract(data_dir, sources):
    """Quellen ohne valide extractions/{nid}.{source_id}.json."""
    from nlm_ingest.schemas import Extraction
    todo = []
    for s in sources:
        p = data_dir / "extractions" / f"{s.notebook_id}.{s.source_id}.json"
        if p.exists():
            try:
                Extraction.model_validate_json(p.read_text())
                continue
            except Exception:
                pass
        todo.append(s)
    return todo
```

`extract`-Command (Kern):

```python
        from nlm_ingest.extract import extract_with_qwen, review_with_claude
        from nlm_ingest.sources import load_sources
        db = _get_db()
        matrix = get_all_status(db)
        candidates = [
            r for r in matrix
            if r.get("extract") in ("pending", "failed", "running")
            and (notebook_id is None or r["notebook_id"] == notebook_id)
        ]
        async with httpx.AsyncClient() as client:
            for row in candidates:
                nid = row["notebook_id"]
                sources = load_sources(data_dir, nid)
                if not sources:
                    continue
                set_phase_status(db, nid, "extract", "running")
                meta_path = data_dir / "notebooks" / nid / "metadata.json"
                metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
                ok = True
                for source in _sources_needing_extract(data_dir, sources):
                    try:
                        extraction = await extract_with_qwen(
                            source=source, metadata=metadata, client=client,
                            vllm_url=settings.ingestion_vllm_url,
                            vllm_model=settings.ingestion_vllm_model,
                        )
                        if claude_client:
                            extraction = await review_with_claude(
                                extraction=extraction, source=source,
                                claude_client=claude_client, claude_model=settings.claude_model)
                        out = data_dir / "extractions" / f"{nid}.{source.source_id}.json"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_text(extraction.model_dump_json(indent=2))
                    except Exception as e:
                        ok = False
                        click.echo(f"FAIL {nid}/{source.source_id}: {e}")
                set_phase_status(db, nid, "extract", "completed" if ok else "failed")
        db.close()
```

(`claude_client` wie im Bestand initialisieren; `_get_db`, `settings`, `data_dir` wie gehabt.)

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_cli_wiring.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/cli.py tests/test_nlm_cli_wiring.py
git commit -m "feat(nlm-cli): extract iterates all sources, idempotent skip, phase aggregation"
```

---

## Task 13: Export-CLI — Reconciliation + Migrationsaufruf

**Files:**
- Modify: `nlm_ingest/cli.py` (`export`-Command `:105-122`; ggf. `_get_db`)
- Test: `tests/test_nlm_cli_wiring.py`

- [ ] **Step 1: Failing test — Export ruft Reconciliation mit audio_status/report_status**

```python
# tests/test_nlm_cli_wiring.py  (ergänzen)
from unittest.mock import AsyncMock, patch
from click.testing import CliRunner
from nlm_ingest.cli import cli

def test_export_command_reconciles(tmp_path, monkeypatch):
    monkeypatch.setenv("NLM_DATA_DIR", str(tmp_path))   # falls Settings env-gesteuert
    fake_results = [{
        "notebook_id": "nb1", "title": "T", "source_name": "RAND",
        "audio_path": None, "audio_status": "absent", "report_status": "complete",
        "slide_deck_paths": [], "report_paths": [],
    }]
    with patch("nlm_ingest.export.export_all", new=AsyncMock(return_value=fake_results)), \
         patch("nlm_ingest.state.reconcile_phases") as rec:
        result = CliRunner().invoke(cli, ["export"], catch_exceptions=False)
    assert result.exit_code == 0
    rec.assert_called()  # mit audio_status/report_status
```

*(Falls Settings nicht env-gesteuert: `_get_settings`/`_get_db` zusätzlich patchen — vor dem Schreiben kurz die Helper in `cli.py` ansehen.)*

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_cli_wiring.py::test_export_command_reconciles -q`
Expected: FAIL — `reconcile_phases` wird (noch) nicht aufgerufen.

- [ ] **Step 3: `export`-Command erweitern**

```python
        from nlm_ingest.export import export_all
        from nlm_ingest.state import reconcile_phases
        results = await export_all(data_dir, notebook_id=notebook_id)
        db = _get_db()
        for r in results:
            register_notebook(db, r["notebook_id"], r["title"], r["source_name"])
            export_status = "failed" if (r["audio_status"] == "failed"
                                         or r["report_status"] == "failed") else "completed"
            set_phase_status(db, r["notebook_id"], "export", export_status)
            if r["audio_status"] == "absent":
                set_phase_status(db, r["notebook_id"], "transcribe", "skipped")
            reconcile_phases(db, data_dir, r["notebook_id"],
                             audio_status=r["audio_status"], report_status=r["report_status"])
        db.close()
        click.echo(f"Exported {len(results)} notebooks.")
```

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_cli_wiring.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/cli.py tests/test_nlm_cli_wiring.py
git commit -m "feat(nlm-cli): export sets audio/report phase status + runs reconciliation"
```

---

## Task 14: Ingest-CLI — Multi-Source Glob + Neo4j + Qdrant + Aggregation

**Files:**
- Modify: `nlm_ingest/cli.py` (`ingest`-Command `:253+`)
- Test: `tests/test_nlm_cli_wiring.py`

- [ ] **Step 1: Failing test — Glob mehrerer Extraktionsdateien**

```python
# tests/test_nlm_cli_wiring.py  (ergänzen)
from nlm_ingest.cli import _extraction_files_for

def test_extraction_files_globs_all_sources(tmp_path):
    ext = tmp_path / "extractions"; ext.mkdir()
    (ext / "nb1.transcript.json").write_text("{}")
    (ext / "nb1.rep-a.json").write_text("{}")
    (ext / "nb2.transcript.json").write_text("{}")
    files = sorted(p.name for p in _extraction_files_for(tmp_path, "nb1"))
    assert files == ["nb1.rep-a.json", "nb1.transcript.json"]
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_cli_wiring.py::test_extraction_files_globs_all_sources -q`
Expected: FAIL — `ImportError: _extraction_files_for`.

- [ ] **Step 3: Helper + `ingest`-Command**

```python
def _extraction_files_for(data_dir, notebook_id):
    """Alle extractions/{nid}.*.json eines Notebooks (Multi-Source)."""
    return sorted((data_dir / "extractions").glob(f"{notebook_id}.*.json"))
```

`ingest`-Command (Kern): pro Notebook über `_extraction_files_for` iterieren, je Datei `ingest_extraction(...)` (Neo4j) **und** `build_claim_points`+`ingest_to_qdrant` (Qdrant) aufrufen; `ingest=completed` nur bei Vollerfolg, sonst `failed`. Qdrant einmalig `ensure_collection` vor der Schleife.

```python
        from nlm_ingest.ingest_neo4j import ingest_extraction
        from nlm_ingest.ingest_qdrant import (
            build_claim_points, ensure_collection, ingest_to_qdrant)
        from qdrant_client import QdrantClient
        db = _get_db()
        qdrant = QdrantClient(url=settings.qdrant_url)
        await ensure_collection(qdrant, settings.qdrant_collection, settings.embedding_dimensions)
        targets = [r for r in get_all_status(db)
                   if r.get("ingest") in ("pending", "failed", "running")
                   and (notebook_id is None or r["notebook_id"] == notebook_id)]
        async with httpx.AsyncClient() as client:
            async def _embed(text: str) -> list[float]:
                resp = await client.post(f"{settings.tei_embed_url}/embed",
                                         json={"inputs": text, "truncate": True})
                resp.raise_for_status()
                d = resp.json()
                return d[0] if isinstance(d[0], list) else d
            for row in targets:
                nid = row["notebook_id"]
                files = _extraction_files_for(data_dir, nid)
                if not files:
                    continue
                set_phase_status(db, nid, "ingest", "running")
                ok = True
                for f in files:
                    try:
                        extraction = Extraction.model_validate_json(f.read_text())
                        await ingest_extraction(extraction, row.get("source") or "unknown",
                                                client, settings.neo4j_http_url,
                                                settings.neo4j_user, settings.neo4j_password)
                        # Qdrant: embed synchron via TEI (await je Claim)
                        points = []
                        for c in extraction.claims:
                            if c.confidence <= 0.0:
                                continue
                            vec = await _embed(c.statement)
                            points += build_claim_points(
                                extraction.model_copy(update={"claims": [c]}),
                                notebook_title=row.get("title") or "untitled",
                                embed=lambda _t, _v=vec: _v,
                                source_name=row.get("source") or "unknown")
                        await ingest_to_qdrant(qdrant, settings.qdrant_collection, points)
                    except Exception as e:
                        ok = False
                        click.echo(f"FAIL {nid}/{f.name}: {e}")
                set_phase_status(db, nid, "ingest", "completed" if ok else "failed")
        db.close()
```

*(Anmerkung: `build_claim_points` ist bewusst `embed`-injizierbar, damit Tests ohne TEI laufen; hier wird pro Claim einmal asynchron via TEI eingebettet und der Vektor injiziert. `Extraction.model_copy` hält die Provenance je Claim intakt.)*

- [ ] **Step 4: Run — verify PASS**

Run: `uv run pytest tests/test_nlm_cli_wiring.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/cli.py tests/test_nlm_cli_wiring.py
git commit -m "feat(nlm-cli): ingest globs all sources, writes Neo4j + Qdrant, aggregates phase"
```

---

## Task 15: Migrations-Verdrahtung + Suite-Gesamtlauf + Lint

**Files:**
- Modify: `nlm_ingest/cli.py` (neuer `migrate`-Command bzw. Aufruf in `_get_db`)
- Modify: `tests/conftest.py` (Guards für neue NLM-Testdateien)
- Test: gesamte `tests/test_nlm_*`

- [ ] **Step 1: Failing test — `migrate`-Command ruft lokalen Teil**

```python
# tests/test_nlm_cli_wiring.py  (ergänzen)
from unittest.mock import patch
from click.testing import CliRunner
from nlm_ingest.cli import cli

def test_migrate_command_invokes_local(monkeypatch):
    with patch("nlm_ingest.migrate.migrate_local") as ml:
        res = CliRunner().invoke(cli, ["migrate", "--local-only"])
    assert res.exit_code == 0
    ml.assert_called_once()
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run pytest tests/test_nlm_cli_wiring.py::test_migrate_command_invokes_local -q`
Expected: FAIL — `migrate`-Command existiert nicht.

- [ ] **Step 3: `migrate`-Command + conftest-Guards**

In `nlm_ingest/cli.py`:

```python
@cli.command()
@click.option("--local-only", is_flag=True, help="Nur SQLite/Dateien, kein Neo4j-Backfill")
def migrate(local_only: bool):
    """Einmalige Migration auf das Multi-Source-Schema."""
    from nlm_ingest.migrate import migrate_local, build_neo4j_backfill_statement
    settings = _get_settings()
    data_dir = Path(settings.nlm_data_dir)
    db = _get_db()
    migrate_local(db, data_dir)
    db.close()
    click.echo("Local migration done.")
    if local_only:
        return
    # Neo4j-Backfill separat (unerreichbares Neo4j blockiert den lokalen Teil nicht)
    import base64
    async def _backfill():
        stmt = build_neo4j_backfill_statement()
        auth = base64.b64encode(
            f"{settings.neo4j_user}:{settings.neo4j_password}".encode()).decode()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.neo4j_http_url}/db/neo4j/tx/commit",
                json={"statements": [stmt]},
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                timeout=30.0,
            )
            resp.raise_for_status()
            errors = resp.json().get("errors", [])
            if errors:
                raise RuntimeError(f"Neo4j backfill error: {errors[0].get('message','')}")
    asyncio.run(_backfill())
    click.echo("Neo4j backfill done.")
```

In `tests/conftest.py` Guards ergänzen (analog vorhandenem `notebooklm`-Guard), damit die neuen Tests bei fehlenden Optional-Deps nicht das Panel brechen:

```python
for _t in ("test_nlm_sources.py", "test_nlm_migrate.py", "test_nlm_ingest_qdrant.py"):
    try:
        import qdrant_client  # noqa: F401
    except ModuleNotFoundError:
        collect_ignore_glob.append("test_nlm_ingest_qdrant.py")
        break
```

*(Nur `test_nlm_ingest_qdrant.py` hängt an `qdrant_client`; `sources`/`migrate` nur an Kern-Deps — diese brauchen keinen Guard, außer sie importieren Optional-Pakete.)*

- [ ] **Step 4: Gesamtlauf + Lint**

Run:
```bash
uv run pytest tests/ -q
uvx ruff check nlm_ingest/ tests/test_nlm_*.py
```
Expected: alle NLM-Tests grün; ruff „All checks passed!". Vorbestehende, nicht-NLM Failures sind außerhalb des Scopes (notieren, nicht hier fixen).

- [ ] **Step 5: Commit**

```bash
git add nlm_ingest/cli.py tests/conftest.py tests/test_nlm_cli_wiring.py
git commit -m "feat(nlm-cli): migrate command (local + separable neo4j backfill) + test guards"
```

---

## Abschluss

- [ ] **Zwei-stufiges Review** (Spec-Konformität + Qualität) für die gesamte Story — Pflicht laut Projektregeln. Insbesondere `graph-rag-auditor` für die Write-Template-Änderung (Task 4, 10) und Read/Write-Pfad-Trennung; `intel-codebook-curator` falls Codebook/Schemas berührt.
- [ ] **`finishing-a-development-branch`** zur Integration (Merge/PR-Entscheidung). Das fertige `export.py`-Feature (Slide/Report-Download) liegt bereits uncommitted auf diesem Branch und sollte als eigener Commit vor dieser Story eingereiht werden.
- [ ] **Manuelle E2E-Verifikation** (echtes Notebook mit Audio + Report): `export → transcribe → extract → ingest`; prüfen, dass zwei `EXTRACTED_FROM`-Kanten und zwei `odin_intel`-Points (transcript + report) entstehen und `qdrant_search` den Report-Claim findet.

## Spec-Coverage-Check (Self-Review)

| Spec-Abschnitt | Task(s) |
|---|---|
| Änderung 1 (ExtractionSource, Extraction-Felder) | Task 5 |
| Änderung 2 (sources.py) | Task 6 |
| Änderung 3 (extract.py Refactor) | Task 7 |
| Änderung 4 (Extract-CLI: Target, Persistenz, Idempotenz, Aggregation) | Task 12 |
| Änderung 5 (audio_status, report_status) | Task 8 |
| Änderung 6 (skipped + DAG validate_retry) | Task 1, 2 |
| Änderung 6b (Reconciliation) | Task 9, 13 |
| Änderung 7 (Provenance-Kante, Document-Type) | Task 10 |
| Änderung 8 (Qdrant pro Claim, UUIDv5, Preflight) | Task 11, 14 |
| Änderung 9 (Ingest-CLI Multi-Source) | Task 14 |
| Migration (SQLite, Datei, ingest→pending, Neo4j-Backfill, Test) | Task 3, 4, 15 |
