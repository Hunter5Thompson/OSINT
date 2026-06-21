"""Opus teacher: produce the gold Munin Lagebericht from the exact prod (system, human) pair.

The teacher is Opus delivered via Claude Code SUBAGENTS (the already-paid session), not a
metered Anthropic-API integration. `generate(ctx, client)` keeps an injected-`client`
abstraction: in tests it is a mock; for the real run the orchestrator passes a `client`
that dispatches one Opus subagent ("new instance") per context and returns its report."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path


def build_messages(ctx: dict) -> list[dict]:
    return [
        {"role": "system", "content": ctx["system"]},
        {"role": "user", "content": ctx["human"]},
    ]


def generate(ctx: dict, client: Callable[[list[dict]], str]) -> dict:
    assistant = client(build_messages(ctx))
    return {**ctx, "assistant": assistant}


def write_gold(rows: list[dict], path: str) -> None:
    Path(path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
