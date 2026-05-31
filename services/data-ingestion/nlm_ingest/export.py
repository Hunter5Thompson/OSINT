# nlm_ingest/export.py
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

import structlog

log = structlog.get_logger()


async def _download_atomic(
    do_download_to: Callable[[str], Awaitable], final_path: Path
) -> None:
    """Download to a temp ``*.part`` path, then atomically replace ``final_path``.

    ``do_download_to`` is an async callable that downloads to the given path
    string. On ANY failure the partial ``*.part`` file is removed and the
    exception propagates, so ``final_path`` never holds a partial file (the
    callers' ``exists()`` skip stays trustworthy).
    """
    part_path = final_path.with_name(final_path.name + ".part")
    try:
        await do_download_to(str(part_path))
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise
    part_path.replace(final_path)


async def export_all(data_dir: Path, notebook_id: str | None = None) -> list[dict]:
    """
    Export notebooks from NotebookLM.

    Requires prior login via `python -m notebooklm login`.
    If notebook_id is given, only that notebook is exported.

    For each notebook the podcast audio, all *completed* slide decks and all
    *completed* reports are downloaded.  Failed/pending artifacts are skipped.
    A notebook is included in the result if at least one artifact was captured
    OR a retryable export failure occurred (so reconciliation can retry); a
    fully artifact-less notebook with no failure is NOT registered.

    Returns list of dicts with keys: notebook_id, title, source_name,
    audio_path (str | None), audio_status ("downloaded"|"absent"|"failed"),
    report_status ("complete"|"failed"), slide_deck_paths (list[str]),
    report_paths (list[str]).
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

            audio_path, audio_status = await _export_audio(client, nb.id, nb_dir)
            slide_deck_paths = await _export_slide_decks(client, nb.id, nb_dir)
            report_paths, report_status = await _export_reports(client, nb.id, nb_dir)

            # Register only if an artifact exists OR a retryable export failure must
            # be recorded (P2#9). A fully artifact-less notebook (no audio, no report,
            # no slide) is NOT registered.
            has_artifact = bool(audio_path or slide_deck_paths or report_paths)
            retryable_failure = audio_status == "failed" or report_status == "failed"
            if not (has_artifact or retryable_failure):
                continue

            exported.append({
                "notebook_id": nb.id,
                "title": meta["title"],
                "source_name": meta["source_name"],
                "audio_path": str(audio_path) if audio_path else None,
                "audio_status": audio_status,
                "report_status": report_status,
                "slide_deck_paths": slide_deck_paths,
                "report_paths": report_paths,
            })

    return exported


async def _export_audio(
    client, notebook_id: str, nb_dir: Path
) -> tuple[Path | None, Literal["downloaded", "absent", "failed"]]:
    """Returns (Path|None, status) with status in {'downloaded','absent','failed'}."""
    audio_path = nb_dir / "podcast.mp4"
    if audio_path.exists():
        return audio_path, "downloaded"
    try:
        audio_arts = await client.artifacts.list_audio(notebook_id)
    except Exception:
        log.warning("export_list_audio_failed", notebook_id=notebook_id, exc_info=True)
        return None, "failed"
    if not audio_arts:
        return None, "absent"
    try:
        await _download_atomic(
            lambda p: client.artifacts.download_audio(notebook_id, p), audio_path
        )
        size_mb = audio_path.stat().st_size / 1e6
        log.info("export_audio", notebook_id=notebook_id, size_mb=round(size_mb, 1))
        return audio_path, "downloaded"
    except Exception:
        log.warning("export_audio_failed", notebook_id=notebook_id, exc_info=True)
        return None, "failed"


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
            await _download_atomic(
                lambda p, _did=deck.id: client.artifacts.download_slide_deck(
                    notebook_id, p, artifact_id=_did, output_format="pdf"
                ),
                out,
            )
            paths.append(str(out))
            log.info("export_slide_deck", notebook_id=notebook_id, artifact_id=deck.id)
        except Exception:
            # Intentional asymmetry: unlike reports/audio, a slide-deck failure is
            # NOT surfaced as a retryable status (per the export retry contract).
            log.warning(
                "export_slide_deck_failed",
                notebook_id=notebook_id,
                artifact_id=deck.id,
                exc_info=True,
            )
    return paths


async def _export_reports(
    client, notebook_id: str, nb_dir: Path
) -> tuple[list[str], Literal["complete", "failed"]]:
    """Returns (list[str], status) with status in {'complete','failed'}."""
    try:
        reports = await client.artifacts.list_reports(notebook_id)
    except Exception:
        log.warning("export_reports_list_failed", notebook_id=notebook_id, exc_info=True)
        return [], "failed"

    paths: list[str] = []
    status = "complete"
    completed = [r for r in reports if r.is_completed]
    for report in completed:
        out = nb_dir / f"report_{report.id}.md"
        if out.exists():
            paths.append(str(out))
            continue
        try:
            await _download_atomic(
                lambda p, _rid=report.id: client.artifacts.download_report(
                    notebook_id, p, artifact_id=_rid
                ),
                out,
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
            status = "failed"
    return paths, status


def _infer_source(title: str) -> str:
    """Best-effort source inference from notebook title."""
    known = ["RAND", "CSIS", "Brookings", "CNA", "IISS", "SIPRI", "NATO", "RUSI"]
    title_lower = title.lower()
    for source in known:
        if source.lower() in title_lower:
            return source
    return "unknown"
