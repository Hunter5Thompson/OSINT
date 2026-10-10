"""Declared field grammar, duplicates and fallback diagnostics."""

import pytest

from graph.assessment import ASSESSMENT_NOTICE, annotate_assessment, parse_assessment


@pytest.mark.parametrize(
    "text",
    [
        "Threat Assessment: HIGH-RISK\nConfidence Level: high confidence",
        "Threat Assessment: HIGH/CRITICAL\nConfidence Level: high confidence",
        "Threat Assessment: not HIGH\nConfidence Level: high confidence",
        "Threat Assessment: HIGH\nThreat Assessment: HIGH\nConfidence Level: high confidence",
        "```\nThreat Assessment: CRITICAL\n```\nConfidence Level: high confidence",
        "> Threat Assessment: CRITICAL\nConfidence Level: high confidence",
        "Prose: Threat Assessment: CRITICAL\nConfidence Level: high confidence",
    ],
)
def test_invalid_threat_positions_are_diagnosed(text):
    result = parse_assessment(text)
    assert result.threat == "MODERATE"
    assert result.issues
    assert result.confidence == 0.8
    annotated = annotate_assessment(text, result)
    assert annotated.count(ASSESSMENT_NOTICE) == 1
    assert annotate_assessment(annotated, result) == annotated


@pytest.mark.parametrize(
    "text",
    [
        "### 3. **Threat Assessment:** **HIGH**\n### 4. **Confidence Level:** `low confidence`",
        "3) __Threat Assessment__\nHIGH\n4) __Confidence Level__\nLOW CONFIDENCE",
        "Threat Assessment: HIGH — explanation\n"
        "Confidence Level: low confidence (not high confidence)",
    ],
)
def test_generated_markdown_fields_are_supported(text):
    result = parse_assessment(text)
    assert (result.threat, result.confidence, result.issues) == ("HIGH", 0.3, ())
    assert annotate_assessment(text, result) == text


def test_analyst_requires_only_threat_field():
    result = parse_assessment("Threat Assessment: ELEVATED", required=("threat",))
    assert result.threat == "ELEVATED" and not result.issues
