"""Drive queries through the live intelligence service and collect the captured
(system, human) synthesis inputs.

The intelligence service must run with DISTILL_CAPTURE_DIR set (Task 4 capture hook),
so each query writes a side-car JSON the harvest then reads. READ-ONLY w.r.t. ODIN data."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import httpx


def _capture_key(query: str) -> str:
    # MUST match services/intelligence/distill_capture.capture_synthesis_input
    return hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]


def load_queries(path: str) -> list[dict]:
    """Parse queries.jsonl via Python JSON per non-empty line — robust to a missing trailing
    newline (the bash `while read` driver dropped the last query in that case)."""
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def run_harvest(
    queries: list[dict],
    intel_url: str,
    capture_dir: str,
    client,
    on_event: Callable[..., None] = lambda *a: None,
) -> dict:
    """Fire each query at the intel service (tolerant: log + continue on per-query failure), then
    collect the captured contexts and verify EACH successful query produced a capture file.

    Returns a summary: fired / ok / failed / failures / captured / capture_complete /
    missing_captures / contexts. `capture_complete` is the 'no query lost' guarantee."""
    ok, failed, failures, ok_queries = 0, 0, [], []
    for i, q in enumerate(queries, 1):
        query = q["query"] if isinstance(q, dict) else q
        try:
            fire_query(client, intel_url, query)
            ok += 1
            ok_queries.append(query)
            on_event("ok", i, len(queries), query)
        except Exception as e:  # noqa: BLE001 - tolerant batch run: record and continue
            failed += 1
            failures.append({"query": query, "error": str(e)})
            on_event("fail", i, len(queries), query)
    cap = Path(capture_dir)
    missing = [q for q in ok_queries if not (cap / f"{_capture_key(q)}.json").exists()]
    contexts = collect_contexts(capture_dir)
    return {
        "fired": len(queries),
        "ok": ok,
        "failed": failed,
        "failures": failures,
        "captured": len(contexts),
        "capture_complete": not missing,
        "missing_captures": missing,
        "contexts": contexts,
    }


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
    Path(path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


if __name__ == "__main__":  # pragma: no cover
    import sys

    queries_path = sys.argv[1] if len(sys.argv) > 1 else "artifacts/queries.jsonl"
    intel_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8003/query"
    capture_dir = sys.argv[3] if len(sys.argv) > 3 else "/tmp/odin/distill/capture"
    out = sys.argv[4] if len(sys.argv) > 4 else "artifacts/contexts.jsonl"

    qs = load_queries(queries_path)

    def _ev(kind, i, n, q):
        print(f"[{i}/{n}] {kind}: {q}", flush=True)

    with httpx.Client() as _client:
        summary = run_harvest(qs, intel_url, capture_dir, _client, on_event=_ev)
    write_contexts(summary["contexts"], out)
    print(
        f"fired={summary['fired']} ok={summary['ok']} failed={summary['failed']} "
        f"captured={summary['captured']} capture_complete={summary['capture_complete']}"
    )
    if summary["failures"]:
        print(f"FAILURES: {summary['failures']}", file=sys.stderr)
    if not summary["capture_complete"]:
        print(f"MISSING CAPTURES: {summary['missing_captures']}", file=sys.stderr)
        sys.exit(1)
