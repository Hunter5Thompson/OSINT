"""Verify nlm_ingest.cli passes ingestion_vllm_* to extract_with_qwen."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from nlm_ingest import cli as cli_mod
from nlm_ingest.cli import _extraction_files_for, _sources_needing_extract, cli
from nlm_ingest.schemas import Extraction, ExtractionSource, Transcript


def _transcript_json() -> str:
    t = Transcript(
        notebook_id="nb1",
        duration_seconds=10.0,
        language="en",
        segments=[],
        full_text="hello world",
    )
    return t.model_dump_json()


def test_cli_extract_uses_ingestion_vllm_settings(tmp_path, monkeypatch):
    """The 'extract' CLI must call extract_with_qwen with ingestion_vllm_url
    (without '+/v1' suffix) and ingestion_vllm_model."""

    # Lay out the on-disk fixture the CLI expects.
    data_dir = tmp_path / "nlm"
    (data_dir / "transcripts").mkdir(parents=True)
    (data_dir / "transcripts" / "nb1.json").write_text(_transcript_json())
    (data_dir / "notebooks" / "nb1").mkdir(parents=True)
    (data_dir / "notebooks" / "nb1" / "metadata.json").write_text(json.dumps(
        {"source_name": "x", "title": "t"}
    ))

    # Force settings.nlm_data_dir + Spark URL/model into a known state.
    monkeypatch.setenv("NLM_DATA_DIR", str(data_dir))
    monkeypatch.setenv("INGESTION_VLLM_URL", "http://192.168.178.39:8000")
    monkeypatch.setenv("INGESTION_VLLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

    captured = {}

    async def fake_extract(**kwargs):
        captured.update(kwargs)
        src = kwargs["source"]
        return Extraction(
            notebook_id=src.notebook_id,
            entities=[],
            relations=[],
            claims=[],
            extraction_model=kwargs["vllm_model"],
            prompt_version="v0-test",
            source_kind=src.source_kind,
            source_id=src.source_id,
        )

    # get_all_status returns rows describing per-notebook phase state.
    fake_rows = [{"notebook_id": "nb1", "transcribe": "completed", "extract": "pending"}]

    with patch.object(cli_mod, "get_all_status", return_value=fake_rows), \
         patch.object(cli_mod, "_get_db", return_value=MagicMock()), \
         patch.object(cli_mod, "set_phase_status"), \
         patch("nlm_ingest.extract.extract_with_qwen", new=AsyncMock(side_effect=fake_extract)):
        runner = CliRunner()
        result = runner.invoke(cli_mod.extract, [])

    assert result.exit_code == 0, result.output
    assert captured["vllm_url"] == "http://192.168.178.39:8000"
    assert "/v1" not in captured["vllm_url"]
    assert captured["vllm_model"] == "Qwen/Qwen3.6-35B-A3B"
    assert captured["source"].source_kind == "transcript"


def _src(nid, sid, kind):
    return ExtractionSource(notebook_id=nid, source_id=sid, source_kind=kind, text="t")


def test_sources_needing_extract_skips_valid_files(tmp_path):
    ext = tmp_path / "extractions"
    ext.mkdir()
    valid = {
        "notebook_id": "nb1",
        "entities": [],
        "relations": [],
        "claims": [],
        "extraction_model": "q",
        "prompt_version": "v1",
        "source_kind": "report",
        "source_id": "r1",
    }
    (ext / "nb1.r1.json").write_text(json.dumps(valid))
    sources = [_src("nb1", "r1", "report"), _src("nb1", "r2", "report")]
    todo = _sources_needing_extract(tmp_path, sources)
    assert [s.source_id for s in todo] == ["r2"]  # r1 has a valid file


def test_sources_needing_extract_includes_corrupt_file(tmp_path):
    ext = tmp_path / "extractions"
    ext.mkdir()
    (ext / "nb1.r1.json").write_text("{ not valid json")  # corrupt -> not valid
    todo = _sources_needing_extract(tmp_path, [_src("nb1", "r1", "report")])
    assert [s.source_id for s in todo] == ["r1"]


def test_cli_extract_partial_failure_marks_failed_but_attempts_all(tmp_path, monkeypatch):
    """If one source raises during extract, the loop must still attempt the other
    source and the notebook's final extract status must be 'failed' (not aborted)."""

    # Two sources on disk: a transcript + one report -> load_sources yields both.
    data_dir = tmp_path / "nlm"
    (data_dir / "transcripts").mkdir(parents=True)
    (data_dir / "transcripts" / "nb1.json").write_text(_transcript_json())
    (data_dir / "notebooks" / "nb1").mkdir(parents=True)
    (data_dir / "notebooks" / "nb1" / "metadata.json").write_text(json.dumps(
        {"source_name": "x", "title": "t"}
    ))
    (data_dir / "notebooks" / "nb1" / "report_r1.md").write_text("report body")

    monkeypatch.setenv("NLM_DATA_DIR", str(data_dir))
    monkeypatch.setenv("INGESTION_VLLM_URL", "http://192.168.178.39:8000")
    monkeypatch.setenv("INGESTION_VLLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

    attempted: list[str] = []

    async def fake_extract(**kwargs):
        src = kwargs["source"]
        attempted.append(src.source_id)
        if src.source_kind == "transcript":
            raise RuntimeError("boom on transcript")
        return Extraction(
            notebook_id=src.notebook_id,
            entities=[],
            relations=[],
            claims=[],
            extraction_model=kwargs["vllm_model"],
            prompt_version="v0-test",
            source_kind=src.source_kind,
            source_id=src.source_id,
        )

    status_calls: list[tuple] = []

    def record_status(db, nid, phase, status, **kwargs):
        status_calls.append((nid, phase, status))

    fake_rows = [{"notebook_id": "nb1", "transcribe": "completed", "extract": "pending"}]

    with patch.object(cli_mod, "get_all_status", return_value=fake_rows), \
         patch.object(cli_mod, "_get_db", return_value=MagicMock()), \
         patch.object(cli_mod, "set_phase_status", side_effect=record_status), \
         patch("nlm_ingest.extract.extract_with_qwen", new=AsyncMock(side_effect=fake_extract)):
        runner = CliRunner()
        result = runner.invoke(cli_mod.extract, [])

    assert result.exit_code == 0, result.output
    # (b) both sources attempted despite the first raising
    assert attempted == ["transcript", "r1"]
    # (a) final extract status is 'failed' (partial failure)
    assert ("nb1", "extract", "failed") in status_calls
    assert ("nb1", "extract", "completed") not in status_calls


def test_cli_extract_isolates_load_sources_failure(tmp_path, monkeypatch):
    """A corrupt transcript that makes load_sources raise must mark THAT notebook
    extract=failed and continue to the next candidate — not abort the whole batch."""

    data_dir = tmp_path / "nlm"
    (data_dir / "transcripts").mkdir(parents=True)
    # nb1: corrupt transcript -> load_sources raises (invalid JSON).
    (data_dir / "transcripts" / "nb1.json").write_text("{ not valid json")
    # nb2: valid transcript -> processed normally.
    (data_dir / "transcripts" / "nb2.json").write_text(
        Transcript(
            notebook_id="nb2", duration_seconds=10.0, language="en",
            segments=[], full_text="hello",
        ).model_dump_json()
    )
    for nid in ("nb1", "nb2"):
        (data_dir / "notebooks" / nid).mkdir(parents=True)
        (data_dir / "notebooks" / nid / "metadata.json").write_text(
            json.dumps({"source_name": "x", "title": "t"})
        )

    monkeypatch.setenv("NLM_DATA_DIR", str(data_dir))
    monkeypatch.setenv("INGESTION_VLLM_URL", "http://192.168.178.39:8000")
    monkeypatch.setenv("INGESTION_VLLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

    attempted: list[str] = []

    async def fake_extract(**kwargs):
        src = kwargs["source"]
        attempted.append(src.notebook_id)
        return Extraction(
            notebook_id=src.notebook_id, entities=[], relations=[], claims=[],
            extraction_model=kwargs["vllm_model"], prompt_version="v0-test",
            source_kind=src.source_kind, source_id=src.source_id,
        )

    status_calls: list[tuple] = []

    def record_status(db, nid, phase, status, **kwargs):
        status_calls.append((nid, phase, status))

    fake_rows = [
        {"notebook_id": "nb1", "transcribe": "completed", "extract": "pending"},
        {"notebook_id": "nb2", "transcribe": "completed", "extract": "pending"},
    ]

    with patch.object(cli_mod, "get_all_status", return_value=fake_rows), \
         patch.object(cli_mod, "_get_db", return_value=MagicMock()), \
         patch.object(cli_mod, "set_phase_status", side_effect=record_status), \
         patch("nlm_ingest.extract.extract_with_qwen", new=AsyncMock(side_effect=fake_extract)):
        runner = CliRunner()
        result = runner.invoke(cli_mod.extract, [])

    # The bad notebook does not abort the whole batch.
    assert result.exit_code == 0, result.output
    # nb1's load_sources raised -> marked failed.
    assert ("nb1", "extract", "failed") in status_calls
    # nb2 was still processed.
    assert "nb2" in attempted
    assert ("nb2", "extract", "completed") in status_calls


def test_sources_needing_extract_detects_provenance_mismatch(tmp_path):
    # File nb1.r1.json internally carries source_id="r2" -> must NOT count as done.
    ext = tmp_path / "extractions"
    ext.mkdir()
    (ext / "nb1.r1.json").write_text(
        '{"notebook_id":"nb1","entities":[],"relations":[],"claims":[],'
        '"extraction_model":"q","prompt_version":"v1",'
        '"source_kind":"report","source_id":"r2"}'
    )  # wrong source_id
    todo = _sources_needing_extract(tmp_path, [_src("nb1", "r1", "report")])
    assert [s.source_id for s in todo] == ["r1"]


def test_export_command_reconciles(tmp_path, monkeypatch):
    monkeypatch.setenv("NLM_DATA_DIR", str(tmp_path))
    fake_results = [{
        "notebook_id": "nb1", "title": "T", "source_name": "RAND",
        "audio_path": None, "audio_status": "absent", "report_status": "complete",
        "slide_deck_paths": [], "report_paths": [],
    }]
    with patch("nlm_ingest.export.export_all", new=AsyncMock(return_value=fake_results)), \
         patch("nlm_ingest.state.reconcile_phases") as rec:
        result = CliRunner().invoke(cli, ["export"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    rec.assert_called()  # called with audio_status/report_status


def test_export_command_status_failed_on_report_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("NLM_DATA_DIR", str(tmp_path))
    fake_results = [{
        "notebook_id": "nb2", "title": "T2", "source_name": "RAND",
        "audio_path": None, "audio_status": "downloaded", "report_status": "failed",
        "slide_deck_paths": [], "report_paths": [],
    }]
    status_calls: list[tuple] = []

    def record_status(db, nid, phase, status, **kwargs):
        status_calls.append((nid, phase, status))

    with patch("nlm_ingest.export.export_all", new=AsyncMock(return_value=fake_results)), \
         patch("nlm_ingest.state.reconcile_phases"), \
         patch.object(cli_mod, "set_phase_status", side_effect=record_status):
        result = CliRunner().invoke(cli, ["export"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert ("nb2", "export", "failed") in status_calls
    # audio present -> no transcribe=skipped
    assert ("nb2", "transcribe", "skipped") not in status_calls


def test_export_command_skips_transcribe_when_audio_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("NLM_DATA_DIR", str(tmp_path))
    fake_results = [{
        "notebook_id": "nb3", "title": "T3", "source_name": "RAND",
        "audio_path": None, "audio_status": "absent", "report_status": "complete",
        "slide_deck_paths": [], "report_paths": [],
    }]
    status_calls: list[tuple] = []

    def record_status(db, nid, phase, status, **kwargs):
        status_calls.append((nid, phase, status))

    with patch("nlm_ingest.export.export_all", new=AsyncMock(return_value=fake_results)), \
         patch("nlm_ingest.state.reconcile_phases"), \
         patch.object(cli_mod, "set_phase_status", side_effect=record_status):
        result = CliRunner().invoke(cli, ["export"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert ("nb3", "export", "completed") in status_calls
    assert ("nb3", "transcribe", "skipped") in status_calls


def test_export_command_continues_after_notebook_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("NLM_DATA_DIR", str(tmp_path))
    fake_results = [
        {
            "notebook_id": "nb1", "title": "T1", "source_name": "RAND",
            "audio_path": None, "audio_status": "absent", "report_status": "complete",
            "slide_deck_paths": [], "report_paths": [],
        },
        {
            "notebook_id": "nb2", "title": "T2", "source_name": "RAND",
            "audio_path": None, "audio_status": "absent", "report_status": "complete",
            "slide_deck_paths": [], "report_paths": [],
        },
    ]
    status_calls: list[tuple] = []

    def record_status(db, nid, phase, status, **kwargs):
        status_calls.append((nid, phase, status))

    def reconcile_side_effect(db, data_dir, nid, **kwargs):
        if nid == "nb1":
            raise RuntimeError("boom")

    with patch("nlm_ingest.export.export_all", new=AsyncMock(return_value=fake_results)), \
         patch("nlm_ingest.state.reconcile_phases", side_effect=reconcile_side_effect), \
         patch.object(cli_mod, "set_phase_status", side_effect=record_status):
        result = CliRunner().invoke(cli, ["export"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    # nb1 raised in reconcile -> reported as FAIL but did not abort the batch
    assert "FAIL nb1" in result.output
    # nb2 still got its export status set despite nb1 failing
    assert ("nb2", "export", "completed") in status_calls


def test_export_command_reconcile_failure_forces_retryable_state(tmp_path, monkeypatch):
    """A reconcile failure (corrupt transcript -> load_sources raises) for a notebook
    that already has extract/ingest=completed must NOT leave the stale completed state.
    Instead it must force a retryable state so a NEW report on disk is not stranded:
    extract=failed, ingest=pending, and (audio present) transcribe=pending."""
    from nlm_ingest.state import register_notebook, set_phase_status

    monkeypatch.setenv("NLM_DATA_DIR", str(tmp_path))

    # Seed a real DB: nb1 has every phase 'completed' (stale).
    db = cli_mod._get_db()
    register_notebook(db, "nb1", "T", "RAND")
    for phase in ("export", "transcribe", "extract", "ingest"):
        set_phase_status(db, "nb1", phase, "completed")
    db.close()

    # On disk: a CORRUPT transcript so load_sources (called by reconcile_phases) raises,
    # and a NEW report so there IS pending work that must not silently vanish.
    (tmp_path / "transcripts").mkdir(parents=True)
    (tmp_path / "transcripts" / "nb1.json").write_text("{ not valid json")
    (tmp_path / "notebooks" / "nb1").mkdir(parents=True)
    (tmp_path / "notebooks" / "nb1" / "report_rNEW.md").write_text("new report body")

    fake_results = [{
        "notebook_id": "nb1", "title": "T", "source_name": "RAND",
        "audio_path": str(tmp_path / "notebooks" / "nb1" / "podcast.mp4"),
        "audio_status": "downloaded", "report_status": "complete",
        "slide_deck_paths": [], "report_paths": [],
    }]

    # Do NOT patch reconcile_phases — let it run the real load_sources -> raise.
    with patch("nlm_ingest.export.export_all", new=AsyncMock(return_value=fake_results)):
        result = CliRunner().invoke(cli, ["export"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "FAIL nb1 reconcile" in result.output

    # Read back the REAL persisted phase state.
    from nlm_ingest.state import get_phase_status
    db = cli_mod._get_db()
    try:
        assert get_phase_status(db, "nb1", "extract") == "failed"
        assert get_phase_status(db, "nb1", "ingest") == "pending"
        assert get_phase_status(db, "nb1", "transcribe") == "pending"
    finally:
        db.close()


def test_extraction_files_globs_all_sources(tmp_path):
    ext = tmp_path / "extractions"
    ext.mkdir()
    (ext / "nb1.transcript.json").write_text("{}")
    (ext / "nb1.rep-a.json").write_text("{}")
    (ext / "nb2.transcript.json").write_text("{}")
    files = sorted(p.name for p in _extraction_files_for(tmp_path, "nb1"))
    assert files == ["nb1.rep-a.json", "nb1.transcript.json"]


def test_ingest_command_marks_completed(tmp_path, monkeypatch):
    """End-to-end (hermetic) 'ingest' CLI run: a notebook with ingest=pending
    and extract=completed, two extraction files on disk, all heavy collaborators
    mocked (no Neo4j/Qdrant/TEI network) -> exits 0 and phase ends 'completed'."""

    data_dir = tmp_path / "nlm"
    ext = data_dir / "extractions"
    ext.mkdir(parents=True)
    valid = ('{"notebook_id":"nb1","entities":[],"relations":[],"claims":[],'
             '"extraction_model":"q","prompt_version":"v1",'
             '"source_kind":"%s","source_id":"%s"}')
    (ext / "nb1.transcript.json").write_text(valid % ("transcript", "transcript"))
    (ext / "nb1.rep-a.json").write_text(valid % ("report", "rep-a"))

    monkeypatch.setenv("NLM_DATA_DIR", str(data_dir))

    # One target: ready to ingest.
    fake_rows = [{
        "notebook_id": "nb1", "title": "T", "source": "RAND",
        "ingest": "pending", "extract": "completed",
    }]

    status_calls: list[tuple] = []

    def record_status(db, nid, phase, status, **kwargs):
        status_calls.append((nid, phase, status))

    # Local imports inside _run resolve at their definition modules -> patch there.
    with patch.object(cli_mod, "get_all_status", return_value=fake_rows), \
         patch.object(cli_mod, "_get_db", return_value=MagicMock()), \
         patch.object(cli_mod, "set_phase_status", side_effect=record_status), \
         patch("qdrant_client.QdrantClient", return_value=MagicMock()), \
         patch("nlm_ingest.ingest_qdrant.ensure_collection", new=AsyncMock()), \
         patch("nlm_ingest.ingest_qdrant.ingest_to_qdrant", new=AsyncMock()), \
         patch("nlm_ingest.ingest_qdrant.build_claim_points", return_value=[]), \
         patch("nlm_ingest.ingest_neo4j.ingest_extraction", new=AsyncMock()):
        result = CliRunner().invoke(cli, ["ingest"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert ("nb1", "ingest", "completed") in status_calls
    assert ("nb1", "ingest", "failed") not in status_calls


@pytest.mark.asyncio
async def test_ingest_one_notebook_partial_failure_is_not_ok(tmp_path):
    # Aggregation (P1#4/P2#8): if ONE source fails, the notebook is NOT ok.
    from nlm_ingest.cli import _ingest_one_notebook
    ext = tmp_path / "extractions"
    ext.mkdir()
    valid = ('{"notebook_id":"nb1","entities":[],"relations":[],"claims":[],'
             '"extraction_model":"q","prompt_version":"v1",'
             '"source_kind":"%s","source_id":"%s"}')
    (ext / "nb1.transcript.json").write_text(valid % ("transcript", "transcript"))
    (ext / "nb1.rep-a.json").write_text(valid % ("report", "rep-a"))

    async def good_write(extraction):
        return None

    async def bad_for_report(extraction):
        if extraction.source_kind == "report":
            raise RuntimeError("neo4j down")

    ok_all = await _ingest_one_notebook(
        _extraction_files_for(tmp_path, "nb1"),
        expected_notebook_id="nb1",
        neo4j_write=good_write,
        qdrant_write=good_write,
    )
    ok_partial = await _ingest_one_notebook(
        _extraction_files_for(tmp_path, "nb1"),
        expected_notebook_id="nb1",
        neo4j_write=bad_for_report,
        qdrant_write=good_write,
    )
    assert ok_all is True and ok_partial is False


@pytest.mark.asyncio
async def test_ingest_one_notebook_skips_foreign_provenance(tmp_path):
    # A file named nb1.rep-a.json whose internal notebook_id/source_id point at a
    # foreign id must NOT be ingested: _ingest_one_notebook returns False and the
    # writers are never called for that file.
    from nlm_ingest.cli import _ingest_one_notebook
    ext = tmp_path / "extractions"
    ext.mkdir()
    (ext / "nb1.rep-a.json").write_text(
        '{"notebook_id":"nb-other","entities":[],"relations":[],"claims":[],'
        '"extraction_model":"q","prompt_version":"v1",'
        '"source_kind":"report","source_id":"rep-other"}'
    )

    neo4j_calls: list = []
    qdrant_calls: list = []

    async def neo4j_write(extraction):
        neo4j_calls.append(extraction)

    async def qdrant_write(extraction):
        qdrant_calls.append(extraction)

    ok = await _ingest_one_notebook(
        _extraction_files_for(tmp_path, "nb1"),
        expected_notebook_id="nb1",
        neo4j_write=neo4j_write,
        qdrant_write=qdrant_write,
    )
    assert ok is False
    assert neo4j_calls == []  # no foreign-id ingest
    assert qdrant_calls == []


def test_migrate_command_runs_local_via_get_db(tmp_path, monkeypatch):
    # local-only runs via _get_db() (which executes migrate_local idempotently) — no
    # duplicate migrate_local call (Finding #3). Fully isolated (P1#5).
    fake_db = MagicMock()
    monkeypatch.setattr(cli_mod, "_get_db", MagicMock(return_value=fake_db))
    monkeypatch.setattr(
        cli_mod, "_get_settings",
        lambda: SimpleNamespace(nlm_data_dir=str(tmp_path)),
    )
    res = CliRunner().invoke(cli, ["migrate", "--local-only"])
    assert res.exit_code == 0
    cli_mod._get_db.assert_called_once()      # auto-migration is the mechanism
    fake_db.close.assert_called_once()


def test_migrate_command_rejects_both_flags():
    # --local-only and --neo4j-only are mutually exclusive -> UsageError (exit != 0).
    result = CliRunner().invoke(cli, ["migrate", "--local-only", "--neo4j-only"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_migrate_command_neo4j_only_skips_local(monkeypatch):
    # --neo4j-only runs the Neo4j backfill and SKIPS the local part: _get_db must
    # not be called, migrate_neo4j_edges (locally imported from nlm_ingest.migrate)
    # must be awaited once.
    import nlm_ingest.migrate as mig_mod

    fake_get_db = MagicMock()
    monkeypatch.setattr(cli_mod, "_get_db", fake_get_db)
    monkeypatch.setattr(
        cli_mod,
        "_get_settings",
        lambda: SimpleNamespace(
            neo4j_http_url="http://neo", neo4j_user="u", neo4j_password="p"
        ),
    )
    backfill = AsyncMock()
    monkeypatch.setattr(mig_mod, "migrate_neo4j_edges", backfill)

    result = CliRunner().invoke(cli, ["migrate", "--neo4j-only"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    backfill.assert_awaited_once()
    fake_get_db.assert_not_called()


def test_get_db_auto_migrates(tmp_path, monkeypatch):
    # Old-schema DB under nlm_data_dir/state.db -> _get_db auto-migrates.
    db_path = tmp_path / "state.db"
    old = sqlite3.connect(str(db_path))
    old.executescript(
        "CREATE TABLE notebooks (id TEXT PRIMARY KEY, title TEXT, "
        "source_name TEXT, created_at TEXT);"
        "CREATE TABLE phase_status (notebook_id TEXT, phase TEXT, "
        "status TEXT CHECK(status IN ('pending','running','completed','failed')), "
        "error TEXT, started_at TEXT, finished_at TEXT, retry_count INTEGER DEFAULT 0, "
        "updated_at TEXT, PRIMARY KEY (notebook_id, phase));"
    )
    old.close()
    monkeypatch.setattr(
        cli_mod, "_get_settings",
        lambda: SimpleNamespace(nlm_data_dir=str(tmp_path)),
    )
    db = cli_mod._get_db()
    db.execute("INSERT OR IGNORE INTO notebooks (id) VALUES ('nb1')")
    db.execute(
        "INSERT INTO phase_status (notebook_id, phase, status) "
        "VALUES ('nb1','transcribe','skipped')"
    )
    db.commit()  # accepts 'skipped' -> migration ran
    db.close()
