from app.services.severity import (
    CANONICAL_ORDER,
    dominant_category,
    normalize_severity,
    severity_rank,
)


def test_canonical_order_is_fixed():
    assert CANONICAL_ORDER == ["unknown", "low", "medium", "high", "critical"]


def test_known_values_map_case_insensitively():
    assert normalize_severity("Low") == "low"
    assert normalize_severity("HIGH") == "high"
    assert normalize_severity("critical") == "critical"


def test_synonyms_collapse_deterministically():
    assert normalize_severity("moderate") == "medium"
    assert normalize_severity("medium") == "medium"
    assert normalize_severity("elevated") == "high"
    assert normalize_severity("warning") == "low"
    assert normalize_severity("severe") == "critical"
    assert normalize_severity("extreme") == "critical"


def test_null_and_garbage_become_unknown_never_random():
    assert normalize_severity(None) == "unknown"
    assert normalize_severity("") == "unknown"
    assert normalize_severity("  ") == "unknown"
    assert normalize_severity("banana") == "unknown"
    assert normalize_severity(5) == "unknown"  # non-str


def test_severity_rank_orders_unknown_lowest_critical_highest():
    assert severity_rank("unknown") < severity_rank("low") < severity_rank("critical")
    # raw values are normalized first
    assert severity_rank("elevated") == severity_rank("high")


def test_dominant_category_is_modal_with_priority_tiebreak():
    # plurality wins (one outlier never repaints)
    assert dominant_category(["civil"] * 200 + ["military"]) == "civil"
    # exact tie -> fixed priority order (military outranks civil)
    assert dominant_category(["civil", "military"]) == "military"
    # empty -> "other"
    assert dominant_category([]) == "other"
    # None/blank categories ignored, fall back to "other" if nothing left
    assert dominant_category([None, ""]) == "other"
