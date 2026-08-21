"""Pure soundness + scoring logic for the relations_judge measurement spike.

Extracted from the scratchpad runner so the decision-critical logic — gold-set
validation and the GO/NO-GO computation — is versioned and CI-tested rather than
living only in an un-tested scratchpad script (reviewer's repo/CI finding).

No anthropic, no IO, no network: just dict-in / dict-out, so the base venv test
suite exercises it directly.
"""

from __future__ import annotations

import re
from collections import Counter

THRESHOLD = 0.90
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LABELS = ("correct", "wrong")
_DECISIONS = ("approve", "reject", "abstain")


def is_sha256(s) -> bool:
    return isinstance(s, str) and bool(_SHA256_RE.match(s))


def require_frozen_gold(gold_raw: dict, *, edge_ids: set[str],
                        edges_sha256: str) -> dict[str, str]:
    """Validate a parsed gold dict for a SCORED run; return ``{id: label}``.

    Raises ``ValueError`` on any soundness failure (reviewer findings 1/4) — a
    precision number is meaningless unless the gold is frozen AND covers exactly
    the edge set that was scored:

      * ``_meta.status`` must be exactly ``"FROZEN"``.
      * ``_meta.edges_sha256`` must be a 64-hex digest AND equal ``edges_sha256``
        (binds the gold to this exact edge file/order/content; a ``null`` is
        rejected — the earlier "FROZEN + null hash" hole).
      * every label is ``"correct"`` or ``"wrong"`` (no borderline class).
      * labels cover ``edge_ids`` EXACTLY — no missing, no orphan (kills the
        "1 labelled + N unlabelled ⇒ GO" bypass).
    """
    if not isinstance(gold_raw, dict):
        raise ValueError("gold is not a JSON object")
    meta = gold_raw.get("_meta", {})
    if meta.get("status") != "FROZEN":
        raise ValueError("gold._meta.status must be exactly 'FROZEN'")
    gold_edges_sha = meta.get("edges_sha256")
    if not is_sha256(gold_edges_sha):
        raise ValueError("gold._meta.edges_sha256 must be a 64-char hex sha256")
    if gold_edges_sha != edges_sha256:
        raise ValueError(
            f"gold built against a different edge file: "
            f"gold.edges_sha256={gold_edges_sha} actual={edges_sha256}")
    gold = {k: (v.get("label") if isinstance(v, dict) else v)
            for k, v in gold_raw.items() if not k.startswith("_")}
    bad = {k: v for k, v in gold.items() if v not in _LABELS}
    if bad:
        raise ValueError(f"invalid labels (must be correct/wrong): {bad}")
    missing = sorted(edge_ids - set(gold))
    orphan = sorted(set(gold) - edge_ids)
    if missing or orphan:
        raise ValueError(
            f"gold must cover the scored edges exactly: missing={missing} orphan={orphan}")
    return gold


def require_complete_results(results, gold: dict) -> None:
    """Raise ``ValueError`` unless the results cover the gold EXACTLY and uniquely
    with valid decisions (reviewer finding: a partial result set — e.g. 1 result
    vs 88 gold labels — would otherwise score 100% and GO). Scoring a subset of
    the frozen set is never a valid measurement."""
    ids = [str(r["i"]) for r in results]
    if len(set(ids)) != len(ids):
        dup = sorted(i for i, n in Counter(ids).items() if n > 1)
        raise ValueError(f"results contain duplicate ids: {dup}")
    rset, gset = set(ids), set(gold)
    if rset != gset:
        raise ValueError(
            f"results must cover the gold exactly: "
            f"missing={sorted(gset - rset)} extra={sorted(rset - gset)}")
    bad = [r.get("i") for r in results if r.get("decision") not in _DECISIONS]
    if bad:
        raise ValueError(f"results contain invalid decisions for ids: {bad}")


def metrics(results, gold: dict) -> dict:
    """Confusion + precision/approval-rate of the gate's decisions vs the gold.

    ``results`` is a list of ``{"i", "decision", ...}`` dicts; ``gold`` is
    ``{str(i): "correct"|"wrong"}``. Refuses to score an incomplete/duplicated
    result set (see ``require_complete_results``)."""
    require_complete_results(results, gold)
    conf = {(g, d): 0 for g in _LABELS for d in _DECISIONS}
    unlabeled = 0
    for r in results:
        g = gold.get(str(r["i"]))
        if g not in _LABELS:
            unlabeled += 1
            continue
        conf[(g, r["decision"])] += 1
    approved_correct = conf[("correct", "approve")]
    approved_wrong = conf[("wrong", "approve")]
    approved = approved_correct + approved_wrong
    n_correct = sum(conf[("correct", d)] for d in _DECISIONS)
    n_wrong = sum(conf[("wrong", d)] for d in _DECISIONS)
    labeled = n_correct + n_wrong
    kept_out_wrong = conf[("wrong", "reject")] + conf[("wrong", "abstain")]
    return {
        "precision_of_approved": (approved_correct / approved) if approved else None,
        "approved_correct": approved_correct, "approved_wrong": approved_wrong,
        "approved_total": approved,
        "approval_rate": (approved / labeled) if labeled else None,
        "n_correct": n_correct, "n_wrong": n_wrong,
        "error_recall": (kept_out_wrong / n_wrong) if n_wrong else None,
        "good_approval_rate": (approved_correct / n_correct) if n_correct else None,
        "unlabeled": unlabeled,
        "confusion": {f"{g}/{d}": conf[(g, d)] for g in _LABELS for d in _DECISIONS},
    }


def decide(m: dict) -> tuple[bool, str]:
    """GO iff approvals exist AND precision >= 90%. Zero approvals is a forced
    NO-GO so a gate can't 'pass' by abstaining on everything."""
    if m["approved_total"] == 0:
        return False, ("NO-GO: 0 approvals — a gate cannot pass by abstaining on "
                       "everything")
    p = m["precision_of_approved"]
    if p is not None and p >= THRESHOLD:
        return True, f"GO: precision {p * 100:.1f}% >= {THRESHOLD * 100:.0f}%"
    return False, f"NO-GO: precision {p * 100:.1f}% < {THRESHOLD * 100:.0f}%"
