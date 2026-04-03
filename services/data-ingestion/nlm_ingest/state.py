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


def validate_retry(db, notebook_id, phase):
    idx = PHASE_ORDER.index(phase)
    for prev_phase in PHASE_ORDER[:idx]:
        status = get_phase_status(db, notebook_id, prev_phase)
        if status != "completed":
            raise ValueError(
                f"Cannot retry '{phase}': prerequisite '{prev_phase}' is '{status}'"
            )


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
