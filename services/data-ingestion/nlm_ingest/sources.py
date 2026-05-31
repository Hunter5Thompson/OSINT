from __future__ import annotations

from pathlib import Path

from nlm_ingest.schemas import ExtractionSource, Transcript


def load_sources(data_dir: Path, notebook_id: str) -> list[ExtractionSource]:
    """All extractable on-disk sources of a notebook.

    Deterministic order: transcript first, reports sorted by source_id.
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
