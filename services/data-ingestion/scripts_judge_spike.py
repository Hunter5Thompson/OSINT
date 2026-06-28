#!/usr/bin/env python3
"""Relation-v2 Sonnet promotion-gate spike RUNNER (versioned; reviewer findings).

Runs the EXACT production gate (nlm_ingest.relations_judge.judge_relation) over a
set of canonical-eligible edges with a persistent cache, then — on a SCORED run —
reports the binary precision of the gate's APPROVED set (the >=90% Go/No-Go).

All decision-critical logic lives in the CI-tested nlm_ingest.judge_spike_eval
(gold validation + metrics + GO/NO-GO). This file is the thin live driver: it
makes paid network calls and so cannot itself run in CI, but it owns no scoring
logic. `anthropic` is imported lazily so the module imports in the base venv.

AUTH (reviewer finding 6 — honest): every SDK /v1/messages call is billed on the
Anthropic **Developer Platform (Console)**. The Claude.ai **chat subscription is
billed separately and does NOT authorise SDK calls**; `ant auth login`
authenticates to Console/Workspace (also Console-billed), not the chat plan.
Order tried: $ANTHROPIC_API_KEY -> $ANTHROPIC_AUTH_TOKEN -> `ant` profile.

SCORED-RUN GATES (findings 1/4/5): --ground-truth requires --gt-sha256, a FROZEN
gold whose recorded edges_sha256 matches the actual edge file, and labels that
cover every scored edge exactly. --limit is forbidden on scored runs.

    cd services/data-ingestion
    uv run --extra notebooklm python scripts_judge_spike.py \
        --edges /…/canonical_with_evidence.json \
        --cache /…/judge_cache.json --out /…/gate_results.json \
        --ground-truth /…/ground_truth_v8_88.json --gt-sha256 <sha>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from nlm_ingest.judge_spike_eval import decide, metrics, require_frozen_gold
from nlm_ingest.relation_validator import relation_hash
from nlm_ingest.relations_judge import (
    DEFAULT_JUDGE_MODEL,
    DEFAULT_MAX_TOKENS,
    JUDGE_TEMPERATURE,
    RUBRIC_VERSION,
    config_fingerprint,
    judge_relation,
    load_cache,
    save_cache,
)

_OAUTH_BETA = {"anthropic-beta": "oauth-2025-04-20"}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _pct(x) -> str:
    return f"{x * 100:.1f}%" if x is not None else "n/a"


def _abort(msg: str) -> int:
    print(f"ABORT: {msg}", file=sys.stderr)
    return 2


def _build_client():
    """All SDK calls are Console-billed; the chat subscription does not authorise
    them (finding 6). Try API key, then an OAuth token, then an `ant` profile."""
    import anthropic
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("auth: ANTHROPIC_API_KEY (Console API billing)")
        return anthropic.AsyncAnthropic()
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print("auth: ANTHROPIC_AUTH_TOKEN (OAuth Bearer + oauth-2025-04-20, Console-billed)")
        return anthropic.AsyncAnthropic(default_headers=_OAUTH_BETA)
    try:
        r = subprocess.run(["ant", "auth", "print-credentials", "--access-token"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            print("auth: `ant` profile OAuth (Bearer + oauth-2025-04-20, Console-billed)")
            return anthropic.AsyncAnthropic(
                auth_token=r.stdout.strip(), default_headers=_OAUTH_BETA)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    raise SystemExit(
        "No usable Anthropic credential. SDK calls are Console-billed (the "
        "Claude.ai chat subscription does NOT authorise SDK calls). Set "
        "ANTHROPIC_API_KEY, or ANTHROPIC_AUTH_TOKEN, or run `ant auth login`.")


def _edge_to_rel(e: dict) -> SimpleNamespace:
    rh = relation_hash(
        (e["source"], e["source_type"]), e["type"],
        (e["target"], e["target_type"]), e.get("evidence", ""))
    return SimpleNamespace(
        rel_type=e["type"], source=e["source"], source_type=e["source_type"],
        target=e["target"], target_type=e["target_type"],
        evidence=e.get("evidence", ""), relation_hash=rh)


async def _run(edges, *, client, model, cache, concurrency, cache_path):
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    results: list[dict] = [None] * len(edges)  # type: ignore[list-item]
    done = 0

    async def one(idx, e):
        nonlocal done
        async with sem:
            v = await judge_relation(_edge_to_rel(e), client=client, model=model, cache=cache)
        results[idx] = {
            "i": e.get("i", idx + 1), "type": e["type"],
            "source": e["source"], "target": e["target"],
            "decision": v.decision, "cached": v.cached, "error": v.error,
            "reason": v.reason,
        }
        mark = {"approve": "✓", "reject": "✗", "abstain": "?"}[v.decision]
        tag = " (cache)" if v.cached else (" [FAIL-CLOSED]" if v.error else "")
        print(f"  {mark} i={results[idx]['i']:>2} {e['type']:<16} "
              f"{e['source']} -> {e['target']}{tag}", flush=True)
        async with lock:  # checkpoint so an abort never loses decisions/cost (finding 8)
            done += 1
            if done % 5 == 0 or done == len(edges):
                save_cache(cache_path, cache)

    await asyncio.gather(*(one(i, e) for i, e in enumerate(edges)))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edges", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ground-truth", default=None)
    ap.add_argument("--gt-sha256", default=None,
                    help="expected sha256 of the frozen gold file (MANDATORY on scored runs)")
    ap.add_argument("--model", default=DEFAULT_JUDGE_MODEL)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0,
                    help="cap edges (UNSCORED diagnostics only; forbidden with --ground-truth)")
    args = ap.parse_args()

    edge_bytes = Path(args.edges).read_bytes()
    edges_sha = _sha256(edge_bytes)
    edges = json.loads(edge_bytes)

    ids = [str(e["i"]) for e in edges]
    if len(set(ids)) != len(ids):
        return _abort("edge file has duplicate `i` ids")

    scored = bool(args.ground_truth)
    if scored and args.limit:
        return _abort("--limit is not allowed on a scored run (--ground-truth)")
    if scored and not args.gt_sha256:
        return _abort("--gt-sha256 is mandatory on a scored run (FROZEN must be "
                      "pinned by an external hash, not just an editable string)")
    if args.limit:
        edges = edges[: args.limit]

    cache = load_cache(args.cache)
    print(f"Edges: {len(edges)} | edges_sha256={edges_sha} | model: {args.model} "
          f"| rubric: {RUBRIC_VERSION} | cache entries: {len(cache)}")

    gt = None
    gt_sha = None
    if scored:
        gt_bytes = Path(args.ground_truth).read_bytes()
        gt_sha = _sha256(gt_bytes)
        print(f"ground-truth: {Path(args.ground_truth).name}  sha256={gt_sha}")
        if args.gt_sha256 != gt_sha:
            return _abort(f"frozen-hash mismatch: --gt-sha256={args.gt_sha256} actual={gt_sha}")
        try:
            gt = require_frozen_gold(json.loads(gt_bytes),
                                     edge_ids=set(ids), edges_sha256=edges_sha)
        except ValueError as e:
            return _abort(str(e))
        print(f"gold OK: FROZEN, edge-hash bound, {len(gt)} labels cover all "
              f"{len(ids)} edges exactly")
    print(flush=True)

    client = _build_client()
    try:
        results = asyncio.run(_run(edges, client=client, model=args.model,
                                   cache=cache, concurrency=args.concurrency,
                                   cache_path=args.cache))
    finally:
        save_cache(args.cache, cache)

    counts = {"approve": 0, "reject": 0, "abstain": 0}
    for r in results:
        counts[r["decision"]] += 1
    failclosed = sum(1 for r in results if r["error"])

    # Auditable report object: provenance hashes + config + decisions + metrics
    # (reviewer finding 3) so a run can be reproduced/verified after the fact.
    report = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": args.model,
            "rubric_version": RUBRIC_VERSION,
            "config_fingerprint": config_fingerprint(
                args.model, RUBRIC_VERSION, JUDGE_TEMPERATURE, DEFAULT_MAX_TOKENS),
            "edges_sha256": edges_sha,
            "gold_sha256": gt_sha,
            "gt_sha256_expected": args.gt_sha256,
            "n_edges": len(edges),
            "decision_counts": counts,
            "fail_closed_abstains": failclosed,
        },
        "metrics": None,
        "verdict": None,
        "decisions": results,
    }

    print(f"\n=== DECISIONS ===  approve={counts['approve']}  reject={counts['reject']}  "
          f"abstain={counts['abstain']}  (fail-closed abstains: {failclosed})")

    is_go = True
    if gt is not None:
        m = metrics(results, gt)
        is_go, verdict = decide(m)
        report["metrics"], report["verdict"] = m, verdict
        p, ar = m["precision_of_approved"], m["approval_rate"]
        print("\n=== REGRESSION vs frozen ground truth ===")
        print(f"  approved: {m['approved_total']} "
              f"(correct {m['approved_correct']} / wrong {m['approved_wrong']})")
        print(f"  PRECISION of approved set: {_pct(p)}")
        print(f"  APPROVAL-RATE (approved/labeled): {_pct(ar)}")
        print(f"  error-recall (wrong kept out): {_pct(m['error_recall'])}")
        print(f"  good-approval-rate (correct approved): {_pct(m['good_approval_rate'])}")
        print(f"  labeled: {m['n_correct']} correct / {m['n_wrong']} wrong "
              f"| unlabeled: {m['unlabeled']}")
        print(f"  confusion: {json.dumps(m['confusion'])}")
        print(f"\n  >>> single-Sonnet gate: {verdict}")

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"Wrote audit report -> {args.out}")
    # Scored runs return 1 on NO-GO so CI / callers can branch on the exit code.
    return 0 if is_go else 1


if __name__ == "__main__":
    sys.exit(main())
