"""Verify nlm_ingest.cli passes ingestion_vllm_* to extract_with_qwen."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from nlm_ingest import cli as cli_mod
from nlm_ingest.cli import _sources_needing_extract, cli
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
