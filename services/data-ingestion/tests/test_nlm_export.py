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
        client.artifacts.list_audio = AsyncMock(
            return_value=[_artifact("a1", completed=True)]
        )
    else:
        client.artifacts.download_audio = AsyncMock(
            side_effect=RuntimeError("no audio")
        )
        client.artifacts.list_audio = AsyncMock(return_value=[])

    client.artifacts.list_slide_decks = AsyncMock(return_value=slide_decks or [])
    client.artifacts.list_reports = AsyncMock(return_value=reports or [])

    # Mirror the real downloaders: write bytes to the path the impl passes
    # (the atomic helper hands a *.part path, then replaces the final file).
    async def _dl_slide(nb_id, path, artifact_id=None, output_format="pdf"):
        Path(path).write_bytes(b"fake-pdf")
        return path

    async def _dl_report(nb_id, path, artifact_id=None):
        Path(path).write_text("fake-report")
        return path
    client.artifacts.download_slide_deck = AsyncMock(side_effect=_dl_slide)
    client.artifacts.download_report = AsyncMock(side_effect=_dl_report)
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
    assert r["audio_status"] == "downloaded"


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
        Path(path).write_bytes(b"fake-pdf")
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


@pytest.mark.asyncio
async def test_audio_status_absent_when_no_audio_artifact(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], reports=[_artifact("r1", completed=True)])
    client.artifacts.list_audio = AsyncMock(return_value=[])          # empty
    _patch_client(monkeypatch, client)
    results = await export_all(tmp_path)
    assert results[0]["audio_status"] == "absent"
    assert results[0]["report_status"] == "complete"


@pytest.mark.asyncio
async def test_audio_status_failed_when_list_audio_raises(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], reports=[_artifact("r1", completed=True)])
    client.artifacts.list_audio = AsyncMock(side_effect=RuntimeError("api down"))
    _patch_client(monkeypatch, client)
    results = await export_all(tmp_path)
    assert results[0]["audio_status"] == "failed"     # NOT absent


@pytest.mark.asyncio
async def test_report_status_failed_when_completed_report_download_fails(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], slide_decks=None,
                          reports=[_artifact("r1", completed=True)], write_audio=True)
    client.artifacts.download_report = AsyncMock(side_effect=RuntimeError("dl fail"))
    _patch_client(monkeypatch, client)
    results = await export_all(tmp_path)
    assert results[0]["report_status"] == "failed"


@pytest.mark.asyncio
async def test_partial_download_leaves_no_final_file(tmp_path, monkeypatch):
    # A partial download that writes bytes to the target then errors must NOT
    # leave a file at the FINAL report path (only a cleaned-up .part). Otherwise
    # the next run's exists()-skip would treat it as a permanent false success.
    client = _make_client([_notebook("nb1")], reports=[_artifact("r1", completed=True)])
    client.artifacts.list_audio = AsyncMock(return_value=[])

    async def _partial_then_fail(nb_id, path, artifact_id=None):
        Path(path).write_text("PARTIAL")
        raise RuntimeError("network drop")
    client.artifacts.download_report = AsyncMock(side_effect=_partial_then_fail)
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)
    nb_dir = tmp_path / "notebooks" / "nb1"
    # The FINAL report path must NOT exist after a partial-then-fail.
    assert not (nb_dir / "report_r1.md").exists()
    # No leftover .part either.
    assert list(nb_dir.glob("*.part")) == []
    assert results[0]["report_status"] == "failed"


@pytest.mark.asyncio
async def test_partial_audio_download_leaves_no_final_file(tmp_path, monkeypatch):
    client = _make_client([_notebook("nb1")], reports=[_artifact("r1", completed=True)])
    client.artifacts.list_audio = AsyncMock(return_value=[_artifact("a1", completed=True)])

    async def _partial_then_fail(nb_id, path):
        Path(path).write_text("PARTIAL")
        raise RuntimeError("network drop")
    client.artifacts.download_audio = AsyncMock(side_effect=_partial_then_fail)
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)
    nb_dir = tmp_path / "notebooks" / "nb1"
    assert not (nb_dir / "podcast.mp4").exists()
    assert list(nb_dir.glob("*.part")) == []
    assert results[0]["audio_status"] == "failed"


@pytest.mark.asyncio
async def test_partial_slide_download_leaves_no_final_file(tmp_path, monkeypatch):
    client = _make_client(
        [_notebook("nb1")],
        slide_decks=[_artifact("deck1", completed=True)],
        reports=[_artifact("r1", completed=True)],  # keeps the notebook
    )

    async def _partial_then_fail(nb_id, path, artifact_id=None, output_format="pdf"):
        Path(path).write_text("PARTIAL")
        raise RuntimeError("network drop")
    client.artifacts.download_slide_deck = AsyncMock(side_effect=_partial_then_fail)
    _patch_client(monkeypatch, client)

    results = await export_all(tmp_path)
    nb_dir = tmp_path / "notebooks" / "nb1"
    assert not (nb_dir / "slides_deck1.pdf").exists()
    assert list(nb_dir.glob("*.part")) == []
    assert results[0]["slide_deck_paths"] == []
