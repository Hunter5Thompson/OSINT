"""L05 validates parameters before any early return or chunk loop."""

from unittest.mock import AsyncMock

import pytest

from rag.chunker import chunk_text


@pytest.mark.parametrize(
    ("size", "overlap"),
    [
        (0, 0),
        (-1, 0),
        (1, -1),
        (5, 5),
        (5, 6),
        (True, 0),
        (5, False),
        (None, 0),
        ("5", 0),
        (5, "1"),
        (1.5, 0),
    ],
)
def test_invalid_parameters_are_rejected_for_empty_text(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("", chunk_size=size, overlap=overlap)


@pytest.mark.parametrize("text", ["", " \n\t "])
def test_no_chunks_for_empty_or_whitespace(text):
    assert chunk_text(text) == []


def test_normal_overlap_and_exact_size_remain_stable():
    assert chunk_text("a b c d e f", chunk_size=3, overlap=1) == ["a b c", "c d e", "e f"]
    assert chunk_text("a  b c", chunk_size=3, overlap=1) == ["a  b c"]
    assert chunk_text("a b", chunk_size=1, overlap=0) == ["a", "b"]


def test_default_chunks_advance_and_cover_every_word():
    words = [str(index) for index in range(1200)]
    chunks = [chunk.split() for chunk in chunk_text(" ".join(words))]
    assert [len(chunk) for chunk in chunks] == [512, 512, 276]
    assert chunks[0][-50:] == chunks[1][:50]
    assert chunks[1][-50:] == chunks[2][:50]
    assert chunks[2][-1] == "1199"


async def test_indexer_does_no_work_for_empty_document(monkeypatch):
    import rag.indexer as indexer

    ensure = AsyncMock()
    embed = AsyncMock(return_value=[])
    monkeypatch.setattr(indexer, "ensure_collection", ensure)
    monkeypatch.setattr(indexer, "embed_text", embed)
    assert await indexer.ingest_document("synthetic", " \n", "rss") == 0
    ensure.assert_not_awaited()
    embed.assert_not_awaited()
