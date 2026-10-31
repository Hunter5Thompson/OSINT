"""L06 exactly one list marker and complete heading aliases."""

import pytest

from app.models.intel import IntelAnalysis
from app.services.briefing import parse_munin_report
from app.services.report_store import build_hydration_patch


@pytest.mark.parametrize(
    ("line", "finding"),
    [
        ("- -12C", "-12C"),
        ("1. Bridge destroyed", "Bridge destroyed"),
        ("1) Bridge destroyed", "Bridge destroyed"),
        ("* Item", "Item"),
        ("• Item", "Item"),
        ("- **Important**", "**Important**"),
    ],
)
def test_list_marker_is_removed_once(line, finding):
    assert parse_munin_report(f"## Key Findings\n{line}").findings == [finding]


@pytest.mark.parametrize(
    "heading", ["Key Findings appendix", "Findings methodology", "Unrelated Erkenntnisse"]
)
def test_similar_finding_headings_are_not_aliases(heading):
    original = f"## {heading}\n- Original content"
    report = parse_munin_report(original)
    assert report.findings == []
    assert report.body_paragraphs == [original]


def test_similar_summary_heading_does_not_replace_real_summary():
    original = "## Executive Summary appendix\nWrong.\n## Executive Summary\nRight."
    assert parse_munin_report(original).context == "Right."


@pytest.mark.parametrize(
    ("summary", "findings"),
    [
        ("Executive Summary", "Key Findings"),
        ("Summary", "Findings"),
        ("Zusammenfassung", "Erkenntnisse"),
        ("1. **Executive Summary:**", "2) **Key Findings:**"),
    ],
)
def test_complete_heading_aliases_and_generated_markdown(summary, findings):
    report = parse_munin_report(f"## {summary}\nBrief.\n## {findings}\n- Item")
    assert report.context == "Brief." and report.findings == ["Item"]


def test_report_hydration_keeps_negative_value_and_numbered_finding():
    analysis = IntelAnalysis(
        query="synthetic",
        analysis="## Executive Summary\nBrief.\n## Key Findings\n- -12C\n1. Bridge destroyed",
    )
    patch = build_hydration_patch(analysis, country_name="Synthetic")
    assert patch.findings == ["-12C", "Bridge destroyed"]
    assert patch.context == "Brief."
