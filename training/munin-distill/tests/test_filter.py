from munin_distill.filter import filter_examples, heuristic_ok

GOOD = ("Executive Summary: x. Key Findings: - a. Threat Assessment: HIGH. "
        "Confidence Level: moderate confidence. Recommended Actions: y." * 3)


def _report(i: int) -> str:
    # distinct in the first 200 chars so the near-dup guard does not collapse them
    return f"Variante {i}: " + GOOD


def test_heuristic_rejects_missing_label():
    assert heuristic_ok(GOOD) is True
    assert heuristic_ok("kein label, keine struktur") is False


def test_heuristic_does_not_require_bracket_citations():
    # Munin uses (unverifiziert), not [n] citations — a bracket-free report must still pass.
    assert "[" not in GOOD
    assert heuristic_ok(GOOD) is True


def test_filter_keeps_top_k():
    rows = [{"id": str(i), "assistant": _report(i), "human": "h"} for i in range(5)]
    scores = iter([5, 9, 7, 8, 6])
    kept = filter_examples(rows, judge=lambda rep: {"faithfulness": next(scores)}, keep=2)
    assert len(kept) == 2
    assert {k["id"] for k in kept} == {"1", "3"}  # top-2 by score (9, 8)


def test_filter_drops_near_duplicates():
    dup = _report(0)
    rows = [
        {"id": "a", "assistant": dup, "human": "h"},
        {"id": "b", "assistant": dup, "human": "h"},
    ]
    kept = filter_examples(rows, judge=lambda rep: {"faithfulness": 9}, keep=5)
    assert len(kept) == 1


def test_heuristic_allows_long_thorough_report():
    # real Opus gold can exceed 6000 chars; a complete-but-long report must pass (slice finding)
    long_rep = "Variante L: " + GOOD * 18
    assert 6000 < len(long_rep) < 12000
    assert heuristic_ok(long_rep) is True


def test_filter_drops_malformed():
    rows = [{"id": "bad", "assistant": "kein label", "human": "h"}]
    kept = filter_examples(rows, judge=lambda rep: {"faithfulness": 10}, keep=5)
    assert kept == []
