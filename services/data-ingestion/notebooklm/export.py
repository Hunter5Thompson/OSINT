# notebooklm/export.py
from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()


async def export_all(data_dir: Path, notebook_id: str | None = None) -> list[dict]:
    """
    Export notebooks from NotebookLM.

    Requires prior manual login (cookie-auth via notebooklm-py).
    If notebook_id is given, only that notebook is exported.
    Returns list of {notebook_id, title, source_name, audio_path} dicts.
    """
    try:
        import notebooklm_py
    except ImportError:
        raise ImportError(
            "notebooklm-py not installed. Run: uv pip install 'notebooklm-py[browser]' && playwright install"
        )

    client = notebooklm_py.NotebookLM()
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

        # Audio (podcast)
        audio_path = nb_dir / "podcast.mp3"
        if not audio_path.exists():
            try:
                audio_data = await client.notebooks.get_audio(nb.id)
                audio_path.write_bytes(audio_data)
                log.info("export_audio", notebook_id=nb.id, size_mb=len(audio_data) / 1e6)
            except Exception:
                log.warning("export_audio_failed", notebook_id=nb.id, exc_info=True)
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
