import json

import pytest

from munin_distill.dataset import (
    assert_no_leakage,
    response_label_mask,
    split,
    to_chat,
    write_heldout,
)

ROWS = [{"id": str(i), "system": "S", "human": "H", "assistant": "A"} for i in range(20)]


def test_to_chat_shape():
    m = to_chat(ROWS[0])["messages"]
    assert [x["role"] for x in m] == ["system", "user", "assistant"]
    assert m[1]["content"] == "H" and m[2]["content"] == "A"


def test_split_disjoint():
    tr, va, ho = split(ROWS, val_frac=0.1, heldout_n=4, seed=0)

    def ids(xs):
        return {r["id"] for r in xs}

    assert ids(tr) & ids(va) == set()
    assert ids(tr) & ids(ho) == set()
    assert ids(va) & ids(ho) == set()
    assert len(ho) == 4
    assert_no_leakage(tr, va, ho)  # must not raise


def test_leakage_detected():
    with pytest.raises(ValueError):
        assert_no_leakage(ROWS, ROWS[:1], [])


def test_heldout_is_context_only(tmp_path):
    p = tmp_path / "ho.jsonl"
    write_heldout([{"id": "1", "query": "q", "system": "S", "human": "H", "assistant": "A"}], str(p))
    rec = json.loads(p.read_text().splitlines()[0])
    assert rec == {"id": "1", "query": "q", "system": "S", "human": "H"}
    assert "assistant" not in rec  # no gold leaks into the eval set


class _Tok:
    # minimal fake: one token per word
    def __call__(self, text):
        return list(range(len(text.split())))


def test_label_mask_masks_prompt():
    msgs = [
        {"role": "system", "content": "s s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a a a"},
    ]
    labels = response_label_mask(msgs, _Tok())
    assert labels[:3] == [-100, -100, -100]      # system(2)+user(1) masked
    assert all(x != -100 for x in labels[3:])    # assistant unmasked
    assert len(labels[3:]) == 3
