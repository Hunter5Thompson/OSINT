"""Real-store tests must reject production defaults before any client is opened."""

import pytest

from integration_tests.disposable_stores import require_disposable_config

VALID = {
    "HN_TEST_NEO4J_URI": "bolt://127.0.0.1:17687",
    "HN_TEST_NEO4J_PASSWORD": "test-only",
    "HN_TEST_REDIS_URL": "redis://127.0.0.1:16379/0",
    "HN_TEST_QDRANT_URL": "http://127.0.0.1:16333",
    "HN_TEST_QDRANT_COLLECTION": "hn_gdelt_isolated_20261010",
    "HN_TEST_TEI_EMBED_URL": "http://127.0.0.1:8001",
}


@pytest.mark.parametrize("key", list(VALID))
def test_missing_explicit_input_is_rejected(key):
    inputs = {k: v for k, v in VALID.items() if k != key}
    with pytest.raises(ValueError, match="Explicit disposable"):
        require_disposable_config(inputs)


@pytest.mark.parametrize("key, value", [
    ("HN_TEST_NEO4J_URI", "bolt://127.0.0.1:7687"),
    ("HN_TEST_REDIS_URL", "redis://localhost:6379/0"),
    ("HN_TEST_QDRANT_URL", "http://127.0.0.1:6333"),
    ("HN_TEST_NEO4J_URI", "bolt://remote.example:17687"),
    ("HN_TEST_QDRANT_COLLECTION", "odin_intel"),
])
def test_productive_or_undeclared_store_is_rejected(key, value):
    with pytest.raises(ValueError, match="disposable"):
        require_disposable_config({**VALID, key: value})


def test_explicit_disposable_configuration_is_preserved():
    assert require_disposable_config(VALID) == VALID
