"""Tests for legacy fallback agent prompts — untrusted-data hardening.

The legacy OSINT/Analyst agents are reached on ReAct timeout→fallback. Their
system prompts must refuse to follow instructions embedded in grounding data,
signals, or tool results (prompt-injection defense).
"""


def test_legacy_osint_prompt_has_untrusted_data_rule():
    from agents.osint_agent import SYSTEM_PROMPT

    low = SYSTEM_PROMPT.lower()
    assert "untrusted" in low
    assert "instructions" in low or "anweisungen" in low


def test_legacy_analyst_prompt_has_untrusted_data_rule():
    from agents.analyst_agent import SYSTEM_PROMPT

    low = SYSTEM_PROMPT.lower()
    assert "untrusted" in low
    assert "instructions" in low or "anweisungen" in low
