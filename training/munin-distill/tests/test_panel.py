from munin_distill.panel import MUNIN_RUBRIC, aggregate, score_report


def test_rubric_has_hard_gate_dims():
    assert "faithfulness" in MUNIN_RUBRIC
    assert "injection_resistance" in MUNIN_RUBRIC


def _full(**over):
    base = {"faithfulness": 8.0, "coverage": 7.0, "insight": 7.0,
            "struktur": 8.0, "german": 9.0, "injection_resistance": 10.0}
    base.update(over)
    return base


def test_score_report_uses_client():
    s = score_report("report", {"human": "h"}, client=lambda prompt: _full())
    assert s["faithfulness"] == 8.0


def test_score_report_prompt_includes_report_and_evidence():
    seen = {}

    def client(prompt):
        seen["p"] = prompt
        return _full()

    score_report("MY-REPORT", {"human": "MY-EVIDENCE"}, client=client)
    assert "MY-REPORT" in seen["p"]
    assert "MY-EVIDENCE" in seen["p"]


def test_aggregate_averages_per_dim():
    a = {"faithfulness": 8.0, "insight": 6.0}
    b = {"faithfulness": 6.0, "insight": 8.0}
    assert aggregate([a, b]) == {"faithfulness": 7.0, "insight": 7.0}
