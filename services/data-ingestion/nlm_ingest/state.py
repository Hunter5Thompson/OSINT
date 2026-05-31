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
    status TEXT CHECK(status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
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


def register_notebook(db, notebook_id, title, source_name):
    db.execute(
        "INSERT OR IGNORE INTO notebooks (id, title, source_name) VALUES (?, ?, ?)",
        (notebook_id, title, source_name),
    )
    for phase in PHASE_ORDER:
        db.execute(
            "INSERT OR IGNORE INTO phase_status (notebook_id, phase, status) "
            "VALUES (?, ?, 'pending')",
            (notebook_id, phase),
        )
    db.commit()


def set_phase_status(db, notebook_id, phase, status, *, error=None):
    if status == "running":
        db.execute(
            """UPDATE phase_status
               SET status = ?, started_at = datetime('now'),
                   error = NULL, updated_at = datetime('now')
               WHERE notebook_id = ? AND phase = ?""",
            (status, notebook_id, phase),
        )
    elif status == "completed":
        db.execute(
            """UPDATE phase_status
               SET status = ?, finished_at = datetime('now'),
                   error = NULL, updated_at = datetime('now')
               WHERE notebook_id = ? AND phase = ?""",
            (status, notebook_id, phase),
        )
    elif status == "failed":
        db.execute(
            """UPDATE phase_status
               SET status = ?, finished_at = datetime('now'),
                   error = ?, updated_at = datetime('now')
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


def get_phase_status(db, notebook_id, phase):
    row = db.execute(
        "SELECT status FROM phase_status WHERE notebook_id = ? AND phase = ?",
        (notebook_id, phase),
    ).fetchone()
    return row[0] if row else "unknown"


def get_all_status(db):
    rows = db.execute(
        """SELECT n.id, n.title, n.source_name, ps.phase, ps.status
           FROM notebooks n
           JOIN phase_status ps ON n.id = ps.notebook_id
           ORDER BY n.id, ps.phase"""
    ).fetchall()
    notebooks = {}
    for nid, title, source, phase, status in rows:
        if nid not in notebooks:
            notebooks[nid] = {"notebook_id": nid, "title": title, "source": source}
        notebooks[nid][phase] = status
    return list(notebooks.values())


# Explicit phase DAG instead of linear PHASE_ORDER.
# transcribe is NOT a prereq of extract (reports are audio-independent).
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


def valid_extraction_exists(data_dir, source) -> bool:
    """Valid, provenance-consistent extraction file for `source` (Finding #5)."""
    from nlm_ingest.schemas import Extraction  # deferred import: keep state.py import-light

    p = data_dir / "extractions" / f"{source.notebook_id}.{source.source_id}.json"
    if not p.exists():
        return False
    try:
        e = Extraction.model_validate_json(p.read_text())
    except Exception:
        return False
    return (
        e.notebook_id == source.notebook_id
        and e.source_id == source.source_id
        and e.source_kind == source.source_kind
    )


def reconcile_phases(db, data_dir, notebook_id, *, audio_status, report_status):
    """Keep extract/ingest/transcribe consistent with the source inventory (load_sources).

    audio_status in {downloaded,absent,failed}; report_status in {complete,failed}.
    """
    from nlm_ingest.sources import load_sources  # deferred import: keep state.py import-light

    # Audio appeared after skipped -> reactivate transcribe, extract, ingest.
    if (
        audio_status in ("downloaded", "failed")
        and get_phase_status(db, notebook_id, "transcribe") == "skipped"
    ):
        for ph in ("transcribe", "extract", "ingest"):
            set_phase_status(db, notebook_id, ph, "pending")

    sources = load_sources(data_dir, notebook_id)

    # Terminal skipped: no extractable source AND no audio AND reports complete.
    if not sources and audio_status == "absent" and report_status == "complete":
        for ph in ("transcribe", "extract", "ingest"):
            set_phase_status(db, notebook_id, ph, "skipped")
        return

    # Source lacks a valid extraction file -> reactivate extract/ingest.
    needs_extract = not all(
        valid_extraction_exists(data_dir, s) for s in sources
    )
    if needs_extract:
        for ph in ("extract", "ingest"):
            if get_phase_status(db, notebook_id, ph) not in ("running",):
                set_phase_status(db, notebook_id, ph, "pending")


def attempt_retry(db, notebook_id, phase):
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
