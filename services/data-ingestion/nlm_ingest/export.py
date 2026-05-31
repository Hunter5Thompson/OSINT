# nlm_ingest/export.py
from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()


async def export_all(data_dir: Path, notebook_id: str | None = None) -> list[dict]:
    """
    Export notebooks from NotebookLM.

    Requires prior login via `python -m notebooklm login`.
    If notebook_id is given, only that notebook is exported.

    For each notebook the podcast audio, all *completed* slide decks and all
    *completed* reports are downloaded.  Failed/pending artifacts are skipped.
    A notebook is included in the result only if at least one artifact was
    captured.

    Returns list of dicts with keys: notebook_id, title, source_name,
    audio_path (str | None), slide_deck_paths (list[str]), report_paths
    (list[str]).
    """
    try:
        from notebooklm import NotebookLMClient
    except ImportError:
        raise ImportError(
            "notebooklm-py not installed. "
            "Run: uv pip install 'notebooklm-py[browser]' && playwright install"
        ) from None

    client = await NotebookLMClient.from_storage()
    async with client:
        notebooks = await client.notebooks.list()
        if notebook_id:
            notebooks = [nb for nb in notebooks if nb.id == notebook_id]
        log.info("notebooklm_list", count=len(notebooks))

        exported: list[dict] = []
        for nb in notebooks:
            nb_dir = data_dir / "notebooks" / nb.id
            nb_dir.mkdir(parents=True, exist_ok=True)

            title = getattr(nb, "title", "untitled")
            meta = {
                "id": nb.id,
                "title": title,
                "source_name": _infer_source(title),
            }
            (nb_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

            audio_path = await _export_audio(client, nb.id, nb_dir)
            slide_deck_paths = await _export_slide_decks(client, nb.id, nb_dir)
            report_paths = await _export_reports(client, nb.id, nb_dir)

            if not (audio_path or slide_deck_paths or report_paths):
                continue

            exported.append({
                "notebook_id": nb.id,
                "title": meta["title"],
                "source_name": meta["source_name"],
                "audio_path": str(audio_path) if audio_path else None,
                "slide_deck_paths": slide_deck_paths,
                "report_paths": report_paths,
            })

    return exported


async def _export_audio(client, notebook_id: str, nb_dir: Path) -> Path | None:
    """Download the podcast audio. Returns the path, or None on failure."""
    audio_path = nb_dir / "podcast.mp4"
    if audio_path.exists():
        return audio_path
    try:
        await client.artifacts.download_audio(notebook_id, str(audio_path))
        size_mb = audio_path.stat().st_size / 1e6
        log.info("export_audio", notebook_id=notebook_id, size_mb=round(size_mb, 1))
        return audio_path
    except Exception:
        log.warning("export_audio_failed", notebook_id=notebook_id, exc_info=True)
        return None


async def _export_slide_decks(client, notebook_id: str, nb_dir: Path) -> list[str]:
    """Download all completed slide decks as PDF. Returns saved paths."""
    try:
        decks = await client.artifacts.list_slide_decks(notebook_id)
    except Exception:
        log.warning("export_slides_list_failed", notebook_id=notebook_id, exc_info=True)
        return []

    paths: list[str] = []
    completed = [d for d in decks if d.is_completed]
    for deck in completed:
        out = nb_dir / f"slides_{deck.id}.pdf"
        if out.exists():
            paths.append(str(out))
            continue
        try:
            await client.artifacts.download_slide_deck(
                notebook_id, str(out), artifact_id=deck.id, output_format="pdf"
            )
            paths.append(str(out))
            log.info("export_slide_deck", notebook_id=notebook_id, artifact_id=deck.id)
        except Exception:
            log.warning(
                "export_slide_deck_failed",
                notebook_id=notebook_id,
                artifact_id=deck.id,
                exc_info=True,
            )
    return paths


async def _export_reports(client, notebook_id: str, nb_dir: Path) -> list[str]:
    """Download all completed reports as markdown. Returns saved paths."""
    try:
        reports = await client.artifacts.list_reports(notebook_id)
    except Exception:
        log.warning("export_reports_list_failed", notebook_id=notebook_id, exc_info=True)
        return []

    paths: list[str] = []
    completed = [r for r in reports if r.is_completed]
    for report in completed:
        out = nb_dir / f"report_{report.id}.md"
        if out.exists():
            paths.append(str(out))
            continue
        try:
            await client.artifacts.download_report(
                notebook_id, str(out), artifact_id=report.id
            )
            paths.append(str(out))
            log.info("export_report", notebook_id=notebook_id, artifact_id=report.id)
        except Exception:
            log.warning(
                "export_report_failed",
                notebook_id=notebook_id,
                artifact_id=report.id,
                exc_info=True,
            )
    return paths


def _infer_source(title: str) -> str:
    """Best-effort source inference from notebook title."""
    known = ["RAND", "CSIS", "Brookings", "CNA", "IISS", "SIPRI", "NATO", "RUSI"]
    title_lower = title.lower()
    for source in known:
        if source.lower() in title_lower:
            return source
    return "unknown"
