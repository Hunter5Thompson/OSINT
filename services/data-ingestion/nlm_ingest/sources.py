from __future__ import annotations

from pathlib import Path
from typing import Literal

from nlm_ingest.schemas import ExtractionSource, Transcript


def source_kind_for(source_id: str) -> Literal["transcript", "report"]:
    """The source_kind implied by a source_id: the literal "transcript" id maps to
    the transcript kind; everything else is a report artifact."""
    return "transcript" if source_id == "transcript" else "report"


def load_sources(data_dir: Path, notebook_id: str) -> list[ExtractionSource]:
    """All extractable on-disk sources of a notebook.

    Deterministic order: transcript first, reports sorted by source_id.
    """
    sources: list[ExtractionSource] = []

    transcript_path = data_dir / "transcripts" / f"{notebook_id}.json"
    if transcript_path.exists():
        transcript = Transcript.model_validate_json(transcript_path.read_text())
        # Provenance check: never trust a transcript whose internal notebook_id
        # disagrees with the filename-keyed id (surface loudly, don't silently
        # ingest a foreign notebook's transcript as a source of this one).
        if transcript.notebook_id != notebook_id:
            raise ValueError(
                f"transcript notebook_id mismatch: file keyed as {notebook_id!r} "
                f"but internal notebook_id is {transcript.notebook_id!r}"
            )
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
                source_kind=source_kind_for(artifact_id),
                text=report.read_text(),
            ))

    return sources
