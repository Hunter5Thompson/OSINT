from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Iterable
from pathlib import Path


def write_candidates(path: Path, candidates: Iterable, recorded_at: str) -> int:
    by_id: dict[str, dict] = {}
    for c in candidates:
        d = dataclasses.asdict(c)
        d["recorded_at"] = recorded_at
        by_id[c.candidate_id] = d  # dedup by candidate_id
    rows = [by_id[k] for k in sorted(by_id)]  # deterministic order
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    os.replace(tmp, path)  # atomic
    return len(rows)
