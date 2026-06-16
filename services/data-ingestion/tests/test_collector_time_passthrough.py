"""Collectors pass their native source time into process_item.

Uses AST to inspect the *process_item call's* keyword arguments specifically,
rather than a plain substring on the module source — otherwise an unrelated
``published_at=`` kwarg elsewhere (e.g. on ``build_rss_payload``) would make the
RSS assertion a false-green and stop proving the process_item wiring.
"""

import ast
import inspect

from feeds import firms_collector, gdelt_collector, rss_collector, usgs_collector


def _process_item_kwargs(module) -> set[str]:
    """Names of all keyword arguments passed to any process_item(...) call."""
    tree = ast.parse(inspect.getsource(module))
    kwargs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "process_item":
                kwargs.update(k.arg for k in node.keywords if k.arg)
    return kwargs


def test_rss_passes_published_at():
    assert "published_at" in _process_item_kwargs(rss_collector)


def test_usgs_passes_occurred_at():
    assert "occurred_at" in _process_item_kwargs(usgs_collector)


def test_firms_passes_observed_at():
    assert "observed_at" in _process_item_kwargs(firms_collector)


def test_firms_observed_at_normal_hhmm():
    assert firms_collector._firms_observed_at("2026-05-01", "1430") == "2026-05-01T14:30:00+00:00"


def test_firms_observed_at_zfills_three_digit_time():
    assert firms_collector._firms_observed_at("2026-05-01", "345") == "2026-05-01T03:45:00+00:00"


def test_firms_observed_at_empty_time_is_none_not_fabricated_midnight():
    # missing acq_time must NOT fabricate a midnight 'observed' instant
    assert firms_collector._firms_observed_at("2026-05-01", "") is None
    assert firms_collector._firms_observed_at("2026-05-01", None) is None


def test_firms_observed_at_no_date_is_none():
    assert firms_collector._firms_observed_at("", "1430") is None


def test_gdelt_passes_observed_at():
    assert "observed_at" in _process_item_kwargs(gdelt_collector)
