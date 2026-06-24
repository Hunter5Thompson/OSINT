from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Iterable
from pathlib import Path


def _existing_recorded_at(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidate_id = row.get("candidate_id")
        recorded_at = row.get("recorded_at")
        if isinstance(candidate_id, str) and isinstance(recorded_at, str):
            out[candidate_id] = recorded_at
    return out


def write_candidates(path: Path, candidates: Iterable, recorded_at: str) -> int:
    existing_recorded_at = _existing_recorded_at(path)
    by_id: dict[str, dict] = {}
    for c in candidates:
        d = dataclasses.asdict(c)
        d["recorded_at"] = existing_recorded_at.get(c.candidate_id, recorded_at)
        by_id[c.candidate_id] = d  # dedup by candidate_id
    rows = [by_id[k] for k in sorted(by_id)]  # deterministic order
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    os.replace(tmp, path)  # atomic
    return len(rows)
