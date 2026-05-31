import json

import pytest

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
    _write_report(tmp_path, "nb1", "rep-b", "report B")
    _write_report(tmp_path, "nb1", "rep-a", "report A")

    sources = load_sources(tmp_path, "nb1")

    kinds = [(s.source_kind, s.source_id) for s in sources]
    assert kinds == [
        ("transcript", "transcript"),
        ("report", "rep-a"),
        ("report", "rep-b"),
    ]
    transcript = next(s for s in sources if s.source_kind == "transcript")
    assert transcript.text == "podcast text"


def test_load_sources_empty_when_nothing(tmp_path):
    (tmp_path / "notebooks" / "nb1").mkdir(parents=True)
    assert load_sources(tmp_path, "nb1") == []


def test_load_sources_rejects_transcript_id_mismatch(tmp_path):
    # transcripts/nb1.json carrying an internal notebook_id of nb-other must NOT
    # be silently trusted as a source of nb1 — load_sources must raise.
    p = tmp_path / "transcripts" / "nb1.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "notebook_id": "nb-other", "duration_seconds": 1.0, "language": "en",
        "segments": [], "full_text": "foreign text",
    }))
    with pytest.raises(ValueError, match="notebook_id"):
        load_sources(tmp_path, "nb1")
