import json
import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest

from nlm_ingest.migrate import (
    build_neo4j_backfill_statement,
    migrate_local,
    migrate_neo4j_edges,
)

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
    for ph, st in [("export", "completed"), ("transcribe", "completed"),
                   ("extract", "completed"), ("ingest", "completed")]:
        db.execute("INSERT INTO phase_status (notebook_id,phase,status) VALUES (?,?,?)",
                   ("nb1", ph, st))
    db.commit()
    return db


def test_migrate_local_rebuilds_and_reactivates_ingest(tmp_path):
    db_path = tmp_path / "state.db"
    db = _old_db(db_path)
    db.close()

    data_dir = tmp_path / "data"
    (data_dir / "extractions").mkdir(parents=True)
    old_extraction = {
        "notebook_id": "nb1", "entities": [], "relations": [], "claims": [],
        "extraction_model": "qwen", "prompt_version": "v1",
    }
    (data_dir / "extractions" / "nb1.json").write_text(json.dumps(old_extraction))

    db = sqlite3.connect(str(db_path))
    migrate_local(db, data_dir)

    # skipped now allowed
    db.execute(
        "UPDATE phase_status SET status='skipped' "
        "WHERE notebook_id='nb1' AND phase='transcribe'"
    )
    # file renamed + backfilled
    new = json.loads((data_dir / "extractions" / "nb1.transcript.json").read_text())
    assert new["source_kind"] == "transcript" and new["source_id"] == "transcript"
    assert not (data_dir / "extractions" / "nb1.json").exists()
    # ingest reactivated
    row = db.execute(
        "SELECT status FROM phase_status WHERE notebook_id='nb1' AND phase='ingest'"
    ).fetchone()
    assert row[0] == "pending"
    db.close()


def test_migrate_local_is_idempotent(tmp_path):
    db_path = tmp_path / "state.db"
    db = _old_db(db_path)
    db.close()
    data_dir = tmp_path / "data"
    (data_dir / "extractions").mkdir(parents=True)
    db = sqlite3.connect(str(db_path))
    migrate_local(db, data_dir)
    migrate_local(db, data_dir)  # second run must not raise
    db.close()


def test_rebuild_rolls_back_after_drop(tmp_path):
    # Atomicity: an error AFTER the destructive DROP TABLE -> ROLLBACK restores
    # phase_status. Deny ALTER TABLE via SQLite authorizer so the exception falls
    # after CREATE+INSERT+DROP (test hardening).
    import pytest

    from nlm_ingest.migrate import _rebuild_status_table
    db_path = tmp_path / "state.db"
    db = _old_db(db_path)
    db.close()
    db = sqlite3.connect(str(db_path))

    def _deny_alter(action, *args):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK
    db.set_authorizer(_deny_alter)
    with pytest.raises(sqlite3.DatabaseError):
        _rebuild_status_table(db)
    db.set_authorizer(None)

    # ROLLBACK after DROP -> original phase_status with 4 rows restored
    assert db.execute("SELECT count(*) FROM phase_status").fetchone()[0] == 4
    db.close()


_VALID_EXTRACTION = ('{"notebook_id":"nb1","entities":[],"relations":[],"claims":[],'
                     '"extraction_model":"q","prompt_version":"v1",'
                     '"source_kind":"transcript","source_id":"transcript"}')


def test_extraction_rename_valid_target_removes_old(tmp_path):
    # Target is a valid transcript-extraction -> safely remove the old file.
    from nlm_ingest.migrate import _migrate_extraction_files
    ext = tmp_path / "extractions"
    ext.mkdir(parents=True)
    (ext / "nb1.json").write_text('{"notebook_id":"nb1"}')
    (ext / "nb1.transcript.json").write_text(_VALID_EXTRACTION)
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE phase_status "
        "(notebook_id TEXT, phase TEXT, status TEXT, updated_at TEXT)"
    )
    db.execute("INSERT INTO phase_status VALUES ('nb1','ingest','completed','x')")
    db.commit()
    migrated = _migrate_extraction_files(db, tmp_path)
    assert migrated == ["nb1"]
    assert not (ext / "nb1.json").exists()


def test_extraction_rename_invalid_target_aborts_without_loss(tmp_path):
    # Conflict with an INvalid/foreign target -> abort, BOTH files remain (P1#2).
    import pytest

    from nlm_ingest.migrate import _migrate_extraction_files
    ext = tmp_path / "extractions"
    ext.mkdir(parents=True)
    (ext / "nb1.json").write_text('{"notebook_id":"nb1"}')
    # not a valid Extraction
    (ext / "nb1.transcript.json").write_text('{"notebook_id":"nb1","keep":true}')
    db = sqlite3.connect(":memory:")
    with pytest.raises(RuntimeError, match="conflict"):
        _migrate_extraction_files(db, tmp_path)
    assert (ext / "nb1.json").exists()                                   # old file preserved
    assert json.loads((ext / "nb1.transcript.json").read_text())["keep"] is True


def test_migrate_extraction_invalid_old_file_aborts(tmp_path):
    # Broken old file (missing required fields), NO target -> abort before write/delete.
    import pytest

    from nlm_ingest.migrate import _migrate_extraction_files
    ext = tmp_path / "extractions"
    ext.mkdir(parents=True)
    (ext / "nb1.json").write_text('{"notebook_id":"nb1"}')   # invalid Extraction
    db = sqlite3.connect(":memory:")
    with pytest.raises(RuntimeError, match="not a valid Extraction"):
        _migrate_extraction_files(db, tmp_path)
    assert (ext / "nb1.json").exists()                       # old file stays
    assert not (ext / "nb1.transcript.json").exists()        # no half-written target


def test_migrate_extraction_malformed_json_aborts(tmp_path):
    # Malformed legacy JSON (no target) -> friendly RuntimeError, not a raw
    # JSONDecodeError; abort before any write/delete.
    import pytest

    from nlm_ingest.migrate import _migrate_extraction_files
    ext = tmp_path / "extractions"
    ext.mkdir(parents=True)
    (ext / "nb1.json").write_text('{not valid json')   # malformed
    db = sqlite3.connect(":memory:")
    with pytest.raises(RuntimeError, match="not a valid Extraction"):
        _migrate_extraction_files(db, tmp_path)
    assert (ext / "nb1.json").exists()                       # old file stays
    assert not (ext / "nb1.transcript.json").exists()        # no half-written target


def test_migrate_extraction_notebook_id_mismatch_aborts(tmp_path):
    # Old file nb1.json carries internal notebook_id="other" -> abort (Finding #2).
    import pytest

    from nlm_ingest.migrate import _migrate_extraction_files
    ext = tmp_path / "extractions"
    ext.mkdir(parents=True)
    (ext / "nb1.json").write_text(
        '{"notebook_id":"other","entities":[],"relations":[],"claims":[],'
        '"extraction_model":"q","prompt_version":"v1"}')
    db = sqlite3.connect(":memory:")
    with pytest.raises(RuntimeError, match="notebook_id"):
        _migrate_extraction_files(db, tmp_path)
    assert (ext / "nb1.json").exists()
    assert not (ext / "nb1.transcript.json").exists()


def test_backfill_statement_is_scoped_and_parametrized():
    stmt = build_neo4j_backfill_statement()
    cypher = stmt["statement"]
    assert "r.source_kind IS NULL" in cypher
    assert "r.source_id IS NULL" in cypher
    assert "d.notebook_id IS NOT NULL" in cypher
    # parameter-bound, no literals
    assert "$source_kind" in cypher and "$source_id" in cypher
    assert "'transcript'" not in cypher
    assert stmt["parameters"] == {"source_kind": "transcript", "source_id": "transcript"}


_NEO_REQ = httpx.Request("POST", "http://neo/db/neo4j/tx/commit")


@pytest.mark.asyncio
async def test_migrate_neo4j_edges_raises_on_neo4j_errors():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(
        200, json={"errors": [{"message": "boom"}]}, request=_NEO_REQ
    )
    with pytest.raises(RuntimeError, match="boom"):
        await migrate_neo4j_edges(client, "http://neo", "neo4j", "pw")


@pytest.mark.asyncio
async def test_migrate_neo4j_edges_raises_on_http_error():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(503, request=_NEO_REQ)
    with pytest.raises(httpx.HTTPStatusError):
        await migrate_neo4j_edges(client, "http://neo", "neo4j", "pw")
