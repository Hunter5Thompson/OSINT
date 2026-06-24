"""Env-gated capture of the exact synthesis (system, human) messages for distillation.

No-op unless DISTILL_CAPTURE_DIR is set. READ-ONLY w.r.t. the agent graph — it only
writes a side-car JSON of the messages the synthesis LLM is about to receive, so the
distillation harvest sees the real prod input distribution."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def capture_synthesis_input(query: str, messages: list) -> None:
    capture_dir = os.environ.get("DISTILL_CAPTURE_DIR")
    if not capture_dir:
        return
    system = next((m.content for m in messages if type(m).__name__ == "SystemMessage"), "")
    human = next((m.content for m in messages if type(m).__name__ == "HumanMessage"), "")
    out = Path(capture_dir)
    out.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    (out / f"{key}.json").write_text(
        json.dumps({"query": query, "system": str(system), "human": str(human)}, ensure_ascii=False)
    )
