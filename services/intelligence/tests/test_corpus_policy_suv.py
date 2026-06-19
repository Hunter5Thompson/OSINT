# services/intelligence/tests/test_corpus_policy_suv.py
from rag.corpus_policy import ANALYSIS_SOURCES, validate_lane


def _r(**kw):
    # default to valid prose so the content-quality gate (analysis lane) doesn't drop
    # rows that exist to test source/source_type logic; override `content` to test the gate.
    kw.setdefault("content", "NATO expands its eastern flank with several new brigades.")
    return kw


def test_suv_structured_in_analysis_sources():
    assert "suv_structured" in ANALYSIS_SOURCES


def test_keeps_valid_analysis_pairs():
    rows = [
        _r(source="rss", source_type="rss"),
        _r(source="rss_fulltext", source_type="rss"),
        _r(source="suv_structured", source_type="dataset"),
        _r(notebook_id="nb1", source_type="notebooklm"),
        _r(source="rss"),                       # legacy None source_type
    ]
    assert validate_lane(rows, "analysis") == rows


def test_drops_notebook_with_wrong_source_type():
    rows = [
        _r(notebook_id="nb1", source_type="notebooklm"),  # valid -> keep
        _r(notebook_id="nb2", source_type="rss"),         # wrong type -> drop
    ]
    assert validate_lane(rows, "analysis") == [rows[0]]


def test_drops_mismatched_pairs():
    rows = [
        _r(source="rss", source_type="dataset"),         # leak attempt -> drop
        _r(source="suv_structured", source_type="rss"),  # wrong type -> drop
        _r(source="rss", source_type="gdelt"),           # existing AC-2 -> still drop
        _r(source="firms", source_type="dataset"),       # not an analysis source -> drop
    ]
    assert validate_lane(rows, "analysis") == []


def test_analysis_source_branch_wins_over_notebook_id():
    # when a row has BOTH an analysis `source` and a `notebook_id`, the stricter
    # pair-validation (source branch) must apply, not the looser notebook check.
    row_ok = _r(source="suv_structured", source_type="dataset", notebook_id="nb1")
    row_bad = _r(source="suv_structured", source_type="rss", notebook_id="nb1")
    assert validate_lane([row_ok], "analysis") == [row_ok]
    assert validate_lane([row_bad], "analysis") == []
