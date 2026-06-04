from feeds.fulltext_chunker import chunk_markdown


def test_splits_into_multiple_chunks_with_target_size():
    para = ("This is a substantial analytic paragraph about strategy. " * 12).strip()
    md = "\n\n".join(f"## Section {i}\n\n{para}" for i in range(8))
    chunks = chunk_markdown(md, target_tokens=120, overlap_tokens=20)
    assert len(chunks) >= 3
    # ~target: no chunk wildly over (char-approx 4 chars/token)
    assert all(len(c) <= 120 * 4 * 2 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_no_mid_word_split_and_overlap():
    md = "## H\n\n" + "alpha beta gamma delta epsilon zeta eta theta iota kappa. " * 60
    chunks = chunk_markdown(md, target_tokens=80, overlap_tokens=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert not c.startswith(" ")
        # boundary words are whole (no split like 'gam')
        assert c.split()[0].isalpha()


def test_short_input_single_chunk():
    chunks = chunk_markdown(
        "## H\n\nshort body paragraph here.",
        target_tokens=650,
        overlap_tokens=100,
    )
    assert len(chunks) == 1


def test_overlap_repeats_boundary_sentence():
    md = "## H\n\n" + " ".join(
        f"Distinct sentence {i:02d} with several words of padding." for i in range(40)
    )
    chunks = chunk_markdown(md, target_tokens=40, overlap_tokens=20)
    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        # the final sentence of chunk i is carried into chunk i+1 (overlap)
        last = chunks[i].rstrip().rsplit(". ", 1)[-1].rstrip(".")
        assert last in chunks[i + 1], f"no overlap between chunk {i} and {i + 1}"
