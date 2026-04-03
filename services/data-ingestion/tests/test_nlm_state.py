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
        conn2.close()


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
        validate_retry(db, "nb1", "export")

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
        validate_retry(db, "nb1", "transcribe")

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
