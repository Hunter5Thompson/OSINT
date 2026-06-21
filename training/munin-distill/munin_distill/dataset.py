"""Build the chat-format SFT dataset, split with held-out isolation, and provide the
assistant-only label-mask contract used by the trainer (train_on_responses_only)."""
from __future__ import annotations

import json
import random
from pathlib import Path


def to_chat(row: dict) -> dict:
    return {"messages": [
        {"role": "system", "content": row["system"]},
        {"role": "user", "content": row["human"]},
        {"role": "assistant", "content": row["assistant"]},
    ]}


def split(rows, val_frac, heldout_n, seed):
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    heldout = rows[:heldout_n]
    rest = rows[heldout_n:]
    n_val = max(1, int(len(rest) * val_frac))
    return rest[n_val:], rest[:n_val], heldout


def assert_no_leakage(train, val, heldout) -> None:
    ids = [{r["id"] for r in xs} for xs in (train, val, heldout)]
    if ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2]:
        raise ValueError("id overlap across train/val/heldout")


def response_label_mask(messages, tokenizer) -> list[int]:
    labels: list[int] = []
    for m in messages:
        toks = tokenizer(m["content"])
        if m["role"] == "assistant":
            labels.extend(toks)
        else:
            labels.extend([-100] * len(toks))
    return labels


def write_jsonl(rows, path) -> None:
    """Train/val: SFT chat format (system, user, assistant)."""
    Path(path).write_text("\n".join(json.dumps(to_chat(r), ensure_ascii=False) for r in rows))


def write_heldout(rows, path) -> None:
    """Held-out is CONTEXT-ONLY (no gold assistant) — baseline/distilled/Opus generate fresh
    at eval. Keeps id/query metadata so the gate can label sources."""
    Path(path).write_text("\n".join(
        json.dumps(
            {"id": r["id"], "query": r["query"], "system": r["system"], "human": r["human"]},
            ensure_ascii=False,
        )
        for r in rows
    ))
