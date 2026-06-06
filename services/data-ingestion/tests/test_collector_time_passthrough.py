"""Collectors pass their native source time into process_item.

Uses AST to inspect the *process_item call's* keyword arguments specifically,
rather than a plain substring on the module source — otherwise an unrelated
``published_at=`` kwarg elsewhere (e.g. on ``build_rss_payload``) would make the
RSS assertion a false-green and stop proving the process_item wiring.
"""

import ast
import inspect

from feeds import firms_collector, rss_collector, usgs_collector


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
