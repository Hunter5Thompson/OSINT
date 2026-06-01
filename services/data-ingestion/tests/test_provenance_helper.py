from __future__ import annotations

import pytest

from feeds.provenance import DATASET_PROVIDERS, dataset_provenance, provenance_fields


def test_provenance_fields_required():
    out = provenance_fields(source_type="rss", provider="reuters.com")
    assert out["source_type"] == "rss"
    assert out["provider"] == "reuters.com"
    assert "published_at" not in out  # omitted when None


def test_provenance_fields_optional_published():
    out = provenance_fields(
        source_type="rss", provider="bbc.com", published_at="2026-05-31T08:00:00+00:00",
    )
    assert out["published_at"] == "2026-05-31T08:00:00+00:00"


def test_invalid_source_type_raises():
    with pytest.raises(ValueError):
        provenance_fields(source_type="unknown", provider="x")  # not a write type
    with pytest.raises(ValueError):
        provenance_fields(source_type="rss", provider="")


def test_dataset_provenance_lookup():
    out = dataset_provenance("usgs")
    assert out == {"source_type": "dataset", "provider": "usgs.gov"}
    assert "firms" in DATASET_PROVIDERS


def test_dataset_provenance_unknown_source_raises():
    with pytest.raises(KeyError):
        dataset_provenance("not-a-dataset")
