"""CI tests for the spike's decision-critical logic (judge_spike_eval).

These lock the reviewer's soundness findings into CI: gold must be FROZEN +
edge-hash-bound + exactly-covering (findings 1/4), and 0 approvals is a forced
NO-GO (a gate can't pass by abstaining)."""

from __future__ import annotations

import pytest

from nlm_ingest.judge_spike_eval import (
    THRESHOLD,
    decide,
    is_sha256,
    metrics,
    require_complete_results,
    require_frozen_gold,
)

_SHA = "a" * 64


def _frozen_gold(labels: dict, *, status="FROZEN", edges_sha=_SHA) -> dict:
    g = {"_meta": {"status": status, "edges_sha256": edges_sha}}
    g.update({k: {"label": v} for k, v in labels.items()})
    return g


# --- is_sha256 -------------------------------------------------------------

def test_is_sha256():
    assert is_sha256(_SHA)
    assert not is_sha256("a" * 63)       # too short
    assert not is_sha256("A" * 64)       # uppercase not hex-lower
    assert not is_sha256(None)
    assert not is_sha256("xyz")


# --- require_frozen_gold (findings 1/4) ------------------------------------

def test_require_frozen_gold_happy_path():
    gold = require_frozen_gold(
        _frozen_gold({"1": "correct", "2": "wrong"}),
        edge_ids={"1", "2"}, edges_sha256=_SHA)
    assert gold == {"1": "correct", "2": "wrong"}


def test_rejects_unfrozen_gold():
    with pytest.raises(ValueError, match="FROZEN"):
        require_frozen_gold(
            _frozen_gold({"1": "correct"}, status="DRAFT — pending"),
            edge_ids={"1"}, edges_sha256=_SHA)


def test_rejects_null_or_bad_edges_sha():
    with pytest.raises(ValueError, match="edges_sha256"):
        require_frozen_gold(
            _frozen_gold({"1": "correct"}, edges_sha=None),
            edge_ids={"1"}, edges_sha256=_SHA)
    with pytest.raises(ValueError, match="edges_sha256"):
        require_frozen_gold(
            _frozen_gold({"1": "correct"}, edges_sha="short"),
            edge_ids={"1"}, edges_sha256="short")


def test_rejects_edges_sha_mismatch():
    with pytest.raises(ValueError, match="different edge file"):
        require_frozen_gold(
            _frozen_gold({"1": "correct"}, edges_sha=_SHA),
            edge_ids={"1"}, edges_sha256="b" * 64)


def test_rejects_invalid_labels():
    with pytest.raises(ValueError, match="invalid labels"):
        require_frozen_gold(
            _frozen_gold({"1": "maybe"}),
            edge_ids={"1"}, edges_sha256=_SHA)


def test_finding1_bypass_is_rejected():
    # The exact reported bypass: 1 labelled edge but 88 scored edges. Exact
    # coverage must reject it (no silent unlabeled -> GO).
    edge_ids = {str(i) for i in range(1, 89)}
    with pytest.raises(ValueError, match="missing="):
        require_frozen_gold(_frozen_gold({"1": "correct"}),
                            edge_ids=edge_ids, edges_sha256=_SHA)


def test_rejects_orphan_labels():
    with pytest.raises(ValueError, match="orphan="):
        require_frozen_gold(
            _frozen_gold({"1": "correct", "99": "wrong"}),
            edge_ids={"1"}, edges_sha256=_SHA)


# --- results must cover the gold exactly (result-side bypass) --------------

def test_metrics_rejects_partial_results():
    # The reported bypass: 1 result vs 88 gold labels would score 100% + GO.
    gold = {str(i): "correct" for i in range(1, 89)}
    with pytest.raises(ValueError, match="cover the gold exactly"):
        metrics([{"i": 1, "decision": "approve"}], gold)


def test_metrics_rejects_duplicate_result_ids():
    gold = {"1": "correct", "2": "wrong"}
    results = [{"i": 1, "decision": "approve"}, {"i": 1, "decision": "reject"}]
    with pytest.raises(ValueError, match="duplicate ids"):
        metrics(results, gold)


def test_metrics_rejects_extra_result_id():
    gold = {"1": "correct"}
    results = [{"i": 1, "decision": "approve"}, {"i": 2, "decision": "reject"}]
    with pytest.raises(ValueError, match="cover the gold exactly"):
        metrics(results, gold)


def test_require_complete_results_rejects_invalid_decision():
    gold = {"1": "correct"}
    with pytest.raises(ValueError, match="invalid decisions"):
        require_complete_results([{"i": 1, "decision": "maybe"}], gold)


def test_require_complete_results_happy_path():
    gold = {"1": "correct", "2": "wrong"}
    require_complete_results(
        [{"i": 1, "decision": "approve"}, {"i": 2, "decision": "reject"}], gold)


# --- metrics ---------------------------------------------------------------

def test_metrics_precision_and_rates():
    gold = {"1": "correct", "2": "correct", "3": "wrong", "4": "wrong"}
    results = [
        {"i": 1, "decision": "approve"},   # correct approved
        {"i": 2, "decision": "abstain"},   # correct held
        {"i": 3, "decision": "approve"},   # wrong approved (precision hit)
        {"i": 4, "decision": "reject"},    # wrong kept out
    ]
    m = metrics(results, gold)
    assert m["approved_total"] == 2
    assert m["precision_of_approved"] == 0.5          # 1 of 2 approved is correct
    assert m["approval_rate"] == 0.5                  # 2 of 4 labeled approved
    assert m["error_recall"] == 0.5                   # 1 of 2 wrong kept out
    assert m["unlabeled"] == 0
    assert m["confusion"]["wrong/approve"] == 1


# --- decide (0-approvals NO-GO + threshold) --------------------------------

def test_decide_zero_approvals_is_no_go():
    m = metrics([{"i": 1, "decision": "abstain"}], {"1": "correct"})
    is_go, msg = decide(m)
    assert is_go is False and "0 approvals" in msg


def test_decide_go_at_threshold():
    # 9 correct approved + 1 wrong approved = 90% -> GO
    gold = {str(i): "correct" for i in range(9)}
    gold["9"] = "wrong"
    results = [{"i": i, "decision": "approve"} for i in range(10)]
    is_go, msg = decide(metrics(results, gold))
    assert is_go is True and "GO:" in msg


def test_decide_no_go_below_threshold():
    gold = {str(i): "correct" for i in range(8)}
    gold["8"] = gold["9"] = "wrong"
    results = [{"i": i, "decision": "approve"} for i in range(10)]
    is_go, msg = decide(metrics(results, gold))  # 80%
    assert is_go is False and "NO-GO" in msg


def test_threshold_is_ninety_percent():
    assert THRESHOLD == 0.90


# --- runner imports in base venv (anthropic lazy) + delegates scoring -------

def test_runner_imports_without_anthropic_and_delegates():
    import scripts_judge_spike as runner
    # importing must NOT pull in anthropic (lazy in _build_client); these are the
    # delegated scoring functions from the tested eval module
    assert runner.require_frozen_gold is require_frozen_gold
    assert runner.metrics is metrics and runner.decide is decide
    assert callable(runner.main)
