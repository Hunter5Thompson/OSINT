"""Tests for nlm_ingest.export — multi-artifact export from NotebookLM.

export_all must, in addition to the podcast audio, pull *completed* slide
decks and reports for each notebook while skipping failed/pending artifacts,
and must preserve the dict contract consumed by the CLI
(notebook_id / title / source_name).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nlm_ingest.export import export_all


def _notebook(nb_id: str, title: str = "RAND Strategic Outlook"):
    return SimpleNamespace(id=nb_id, title=title)


def _artifact(art_id: str, *, completed: bool):
    return SimpleNamespace(id=art_id, is_completed=completed)


def _make_client(
    notebooks,
    *,
    slide_decks=None,
    reports=None,
    write_audio=False,
):
    """Build a fake NotebookLMClient usable as `async with client:`."""
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    client.notebooks.list = AsyncMock(return_value=notebooks)

    if write_audio:
        async def _dl_audio(nb_id, path):
            Path(path).write_bytes(b"fake-audio-bytes")
            return path
        client.artifacts.download_audio = AsyncMock(side_effect=_dl_audio)
    else:
        client.artifacts.download_audio = AsyncMock(
            side_effect=RuntimeError("no audio")
        )

    client.artifacts.list_slide_decks = AsyncMock(return_value=slide_decks or [])
    client.artifacts.list_reports = AsyncMock(return_value=reports or [])
    client.artifacts.download_slide_deck = AsyncMock(return_value="ok")
    client.artifacts.download_report = AsyncMock(return_value="ok")
    return client


def _patch_client(monkeypatch, client):
    import notebooklm

    fake_cls = SimpleNamespace(from_storage=AsyncMock(return_value=client))
    monkeypatch.setattr(notebooklm, "NotebookLMClient", fake_cls)


@pytest.mark.asyncio
async def test_downloads_completed_slide_deck(tmp_path, monkeypatch):
    client = _make_client(
        [_notebook("nb1")],
        slide_decks=[_artifact("deck1", completed=True)],
    )
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    assert len(results) == 1
    expected = str(tmp_path / "notebooks" / "nb1" / "slides_deck1.pdf")
    assert results[0]["slide_deck_paths"] == [expected]
    client.artifacts.download_slide_deck.assert_awaited_once()
    _, kwargs = client.artifacts.download_slide_deck.await_args
    assert kwargs.get("output_format") == "pdf"


@pytest.mark.asyncio
async def test_skips_failed_slide_deck(tmp_path, monkeypatch):
    client = _make_client(
        [_notebook("nb1")],
        slide_decks=[_artifact("deck1", completed=False)],
        reports=[_artifact("rep1", completed=True)],  # so the notebook is kept
    )
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    assert results[0]["slide_deck_paths"] == []
    client.artifacts.download_slide_deck.assert_not_awaited()


@pytest.mark.asyncio
async def test_downloads_completed_report(tmp_path, monkeypatch):
    client = _make_client(
        [_notebook("nb1")],
        reports=[_artifact("rep1", completed=True)],
    )
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    expected = str(tmp_path / "notebooks" / "nb1" / "report_rep1.md")
    assert results[0]["report_paths"] == [expected]
    client.artifacts.download_report.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_completed_slide_decks(tmp_path, monkeypatch):
    client = _make_client(
        [_notebook("nb1")],
        slide_decks=[
            _artifact("deck1", completed=True),
            _artifact("deck2", completed=True),
        ],
    )
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    nb_dir = tmp_path / "notebooks" / "nb1"
    assert results[0]["slide_deck_paths"] == [
        str(nb_dir / "slides_deck1.pdf"),
        str(nb_dir / "slides_deck2.pdf"),
    ]


@pytest.mark.asyncio
async def test_preserves_core_keys_and_audio(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], write_audio=True)
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    r = results[0]
    assert r["notebook_id"] == "nb1"
    assert r["title"] == "RAND Strategic Outlook"
    assert r["source_name"] == "RAND"
    assert r["audio_path"] == str(tmp_path / "notebooks" / "nb1" / "podcast.mp4")


@pytest.mark.asyncio
async def test_slide_deck_list_failure_is_isolated(tmp_path, monkeypatch):
    client = _make_client(
        [_notebook("nb1")],
        reports=[_artifact("rep1", completed=True)],  # keeps the notebook
    )
    client.artifacts.list_slide_decks = AsyncMock(side_effect=RuntimeError("boom"))
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    # listing blew up -> no decks, but reports were still captured
    assert results[0]["slide_deck_paths"] == []
    assert len(results[0]["report_paths"]) == 1


@pytest.mark.asyncio
async def test_one_failed_download_keeps_sibling(tmp_path, monkeypatch):
    client = _make_client(
        [_notebook("nb1")],
        slide_decks=[
            _artifact("deck1", completed=True),
            _artifact("deck2", completed=True),
        ],
    )

    async def _dl(nb_id, path, artifact_id=None, output_format="pdf"):
        if artifact_id == "deck1":
            raise RuntimeError("download failed")
        return path
    client.artifacts.download_slide_deck = AsyncMock(side_effect=_dl)
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    # deck1 failed, deck2 survived
    expected = str(tmp_path / "notebooks" / "nb1" / "slides_deck2.pdf")
    assert results[0]["slide_deck_paths"] == [expected]


@pytest.mark.asyncio
async def test_notebook_without_any_artifact_is_skipped(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")])  # no audio, no decks, no reports
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)

    assert results == []
