"""Verify nlm_ingest.cli passes ingestion_vllm_* to extract_with_qwen."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from nlm_ingest import cli as cli_mod
from nlm_ingest.schemas import Extraction, Transcript


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
        return Extraction(
            notebook_id=kwargs["transcript"].notebook_id,
            entities=[],
            relations=[],
            claims=[],
            extraction_model=kwargs["vllm_model"],
            prompt_version="v0-test",
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
