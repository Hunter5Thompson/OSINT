# nlm_ingest/migrate.py
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import httpx
import structlog

from nlm_ingest.write_templates import BACKFILL_EXTRACTED_FROM

log = structlog.get_logger()


# _NEW_PHASE_STATUS is EXACTLY ONE CREATE statement (no executescript!).
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
)
"""


def _needs_status_rebuild(db: sqlite3.Connection) -> bool:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='phase_status'"
    ).fetchone()
    return bool(row) and "skipped" not in row[0]


def _rebuild_status_table(db: sqlite3.Connection) -> None:
    """Atomic schema rebuild (P1#1) — ONLY schema, no reactivation.
    isolation_level=None + manual BEGIN/COMMIT/ROLLBACK; NO executescript
    (it would implicitly commit and break atomicity)."""
    prev = db.isolation_level
    db.isolation_level = None
    try:
        db.execute("BEGIN")
        db.execute(_NEW_PHASE_STATUS)
        db.execute(
            "INSERT INTO phase_status_new SELECT notebook_id, phase, status, error, "
            "started_at, finished_at, retry_count, updated_at FROM phase_status"
        )
        db.execute("DROP TABLE phase_status")
        db.execute("ALTER TABLE phase_status_new RENAME TO phase_status")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.isolation_level = prev


def _is_valid_transcript_extraction(path: Path, notebook_id: str) -> bool:
    """Is the target a valid transcript-extraction for exactly this notebook?"""
    from nlm_ingest.schemas import Extraction
    try:
        e = Extraction.model_validate_json(path.read_text())
    except Exception:
        return False
    return (e.notebook_id == notebook_id
            and e.source_id == "transcript" and e.source_kind == "transcript")


def _migrate_extraction_files(db: sqlite3.Connection, data_dir: Path) -> list[str]:
    """Crash-safe + conflict-safe (P1#1/P1#2). Per old {nid}.json:
      1. write {nid}.transcript.json (if missing; via tmp + atomic replace),
      2. reactivate ingest ONLY for this nid (commit),
      3. only THEN delete {nid}.json.
    The old file is the durable marker -> a crash at any point is re-runnable,
    and only actually-migrated ids are reactivated (P1#1).
    If the target already exists but is INvalid/foreign -> abort (RuntimeError),
    both files remain -> no data loss (P1#2)."""
    ext_dir = data_dir / "extractions"
    if not ext_dir.exists():
        return []
    migrated: list[str] = []
    for old in sorted(ext_dir.glob("*.json")):
        if old.stem.count(".") > 0:          # skip new {nid}.{source_id}.json
            continue
        nid = old.stem
        target = ext_dir / f"{nid}.transcript.json"
        if target.exists():
            if not _is_valid_transcript_extraction(target, nid):
                raise RuntimeError(
                    f"Migration conflict for {nid}: {target.name} exists but is not a "
                    f"valid transcript extraction; refusing to delete {old.name}")
        else:
            from nlm_ingest.schemas import Extraction
            # parse + model + semantic validation before write/delete; malformed
            # JSON must surface as the same friendly RuntimeError, not a raw
            # JSONDecodeError -> keep json.loads INSIDE the try:
            try:
                data = json.loads(old.read_text())
                # Legacy is always a transcript source -> set provenance
                # EXPLICITLY (overwrite, not setdefault), so e.g. a
                # wrongly-present source_kind="report" is not cemented as
                # transcript.json (Finding #2).
                data["source_kind"] = "transcript"
                data["source_id"] = "transcript"
                e = Extraction.model_validate(data)
            except Exception as exc:
                raise RuntimeError(
                    f"Migration: {old.name} is not a valid Extraction after backfill "
                    f"({exc}); refusing to migrate/delete") from exc
            if e.notebook_id != nid:
                raise RuntimeError(
                    f"Migration: {old.name} carries notebook_id={e.notebook_id!r} != "
                    f"filename {nid!r}; refusing to migrate/delete")
            tmp = ext_dir / f"{nid}.transcript.json.tmp"
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(target)              # atomic rename
        # idempotently reactivate only this nid, commit, THEN delete old file
        db.execute(
            "UPDATE phase_status SET status='pending', updated_at=datetime('now') "
            "WHERE notebook_id=? AND phase='ingest' AND status='completed'", (nid,))
        db.commit()
        old.unlink()
        migrated.append(nid)
        log.info("migrate_extraction_renamed", notebook_id=nid)
    return migrated


def migrate_local(db: sqlite3.Connection, data_dir: Path) -> None:
    """Idempotent local migration. Neo4j is NOT touched (see migrate_neo4j_edges).
    Order: atomic SQLite schema rebuild, then crash-safe file migration incl.
    targeted ingest reactivation of only the migrated ids."""
    if _needs_status_rebuild(db):
        _rebuild_status_table(db)
        log.info("migrate_sqlite_rebuilt")
    migrated = _migrate_extraction_files(db, data_dir)
    if migrated:
        log.info("migrate_ingest_reactivated", count=len(migrated))


def build_neo4j_backfill_statement() -> dict:
    """Deterministic, scoped backfill of old property-less NLM edges.
    Leaves foreign EXTRACTED_FROM edges (without Document.notebook_id) untouched."""
    return {
        "statement": BACKFILL_EXTRACTED_FROM,
        "parameters": {"source_kind": "transcript", "source_id": "transcript"},
    }


async def migrate_neo4j_edges(
    client: httpx.AsyncClient,
    neo4j_http_url: str,
    neo4j_user: str,
    neo4j_password: str,
) -> None:
    """Separately runnable Neo4j backfill (P2#10). Independent of the local part —
    an unreachable Neo4j does not block migrate_local. Idempotent, re-runnable.
    Raises on HTTP error (raise_for_status) or Neo4j errors in the response body."""
    stmt = build_neo4j_backfill_statement()
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [stmt]},
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        message = data["errors"][0].get("message", "")
        log.warning("nlm_neo4j_backfill_failed", error=message)
        raise RuntimeError(f"Neo4j backfill error: {message}")
