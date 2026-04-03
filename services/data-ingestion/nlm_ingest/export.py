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
    Returns list of {notebook_id, title, source_name, audio_path} dicts.
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

            # Metadata
            meta = {
                "id": nb.id,
                "title": getattr(nb, "title", "untitled"),
                "source_name": _infer_source(getattr(nb, "title", "")),
            }
            (nb_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

            # Audio (podcast) — download via artifacts API
            audio_path = nb_dir / "podcast.mp4"
            if not audio_path.exists():
                try:
                    await client.artifacts.download_audio(
                        nb.id, str(audio_path)
                    )
                    size_mb = audio_path.stat().st_size / 1e6
                    log.info(
                        "export_audio",
                        notebook_id=nb.id,
                        size_mb=round(size_mb, 1),
                    )
                except Exception:
                    log.warning(
                        "export_audio_failed",
                        notebook_id=nb.id,
                        exc_info=True,
                    )
                    continue

            exported.append({
                "notebook_id": nb.id,
                "title": meta["title"],
                "source_name": meta["source_name"],
                "audio_path": str(audio_path),
            })

    return exported


def _infer_source(title: str) -> str:
    """Best-effort source inference from notebook title."""
    known = ["RAND", "CSIS", "Brookings", "CNA", "IISS", "SIPRI", "NATO", "RUSI"]
    title_lower = title.lower()
    for source in known:
        if source.lower() in title_lower:
            return source
    return "unknown"
