# services/backend/tests/test_munin_parse.py
from app.services.briefing import parse_munin_report

REPORT = """## Executive Summary
Lage angespannt.

## Key Findings
- Grenzzwischenfall bestätigt
- Truppenbewegung gemeldet

## Threat Assessment
HIGH — Eskalationsrisiko.

## Recommended Actions
- Aufklärung verstärken
"""


def test_extracts_sections():
    parsed = parse_munin_report(REPORT)
    assert parsed.context.startswith("Lage angespannt")
    assert parsed.findings == ["Grenzzwischenfall bestätigt", "Truppenbewegung gemeldet"]
    assert any("Threat Assessment" in p or "HIGH" in p for p in parsed.body_paragraphs)


def test_fallback_when_no_headings():
    parsed = parse_munin_report("Freitext ohne Überschriften, nur ein Absatz.")
    assert parsed.findings == []
    assert parsed.body_paragraphs == ["Freitext ohne Überschriften, nur ein Absatz."]
    assert parsed.context.startswith("Freitext")


def test_empty_text_is_safe():
    parsed = parse_munin_report("")
    assert parsed.findings == []
    assert parsed.body_paragraphs == [""] or parsed.body_paragraphs == []
