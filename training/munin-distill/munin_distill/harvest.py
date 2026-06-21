"""Drive queries through the live intelligence service and collect the captured
(system, human) synthesis inputs.

The intelligence service must run with DISTILL_CAPTURE_DIR set (Task 4 capture hook),
so each query writes a side-car JSON the harvest then reads. READ-ONLY w.r.t. ODIN data."""
from __future__ import annotations

import json
from pathlib import Path

import httpx


def fire_query(client: httpx.Client, intel_url: str, query: str) -> None:
    # Run the full prod pipeline so the capture hook records the real synthesis input.
    # intel_url = the intelligence service /query endpoint, default http://localhost:8003/query.
    resp = client.post(intel_url, json={"query": query}, timeout=180.0)
    resp.raise_for_status()


def collect_contexts(capture_dir: str) -> list[dict]:
    rows = []
    for fp in sorted(Path(capture_dir).glob("*.json")):
        d = json.loads(fp.read_text())
        rows.append(
            {"id": fp.stem, "query": d["query"], "system": d["system"], "human": d["human"]}
        )
    return rows


def write_contexts(rows: list[dict], path: str) -> None:
    Path(path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
