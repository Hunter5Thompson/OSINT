"""Explicit source time axes must not collapse into publication/factual freshness."""
import json
from datetime import UTC, datetime

import pytest

from rag.evidence import (
    evidence_artifact,
    evidence_items_from_artifact,
    pack_with_lineage,
    to_evidence_item,
)


def test_distinct_explicit_axes_are_normalized_and_reach_prompt_and_artifact():
    item = to_evidence_item({
        "source_type": "dataset", "provider": "fixture.example.invalid",
        "doc_id": "synthetic-time", "title": "synthetic", "content": "synthetic",
        "published_at": "2021-04-05T03:00:00+03:00",
        "observed_at": "2020-02-03T09:00:00-03:00",
        "ingested_at": "2026-10-10T02:00:00+02:00", "score": 0.9,
    })
    body, artifact = pack_with_lineage([item], budget=3000)
    metadata = json.loads(body.splitlines()[0].removeprefix("[EVIDENCE] "))
    assert metadata["published_at"] == "2021-04-05T00:00:00+00:00"
    assert metadata.get("observed_at") == "2020-02-03T12:00:00+00:00"
    assert metadata.get("ingested_at") == "2026-10-10T00:00:00+00:00"
    assert metadata.get("verification_status") == "unverified"
    hydrated = evidence_items_from_artifact(artifact)[0]
    assert getattr(hydrated, "observed_at", None) == datetime(2020, 2, 3, 12, tzinfo=UTC)
    assert getattr(hydrated, "ingested_at", None) == datetime(2026, 10, 10, tzinfo=UTC)


def test_bad_or_other_time_axes_do_not_fabricate_publication_or_observation():
    item = to_evidence_item({
        "source_type": "dataset", "provider": "fixture.example.invalid", "score": 0.9,
        "title": "synthetic", "content": "synthetic", "observed_at": "broken",
        "ingested_at": "2026-10-10T00:00:00Z", "gdelt_date": "2020-01-01",
        "event_time": "2020-01-02", "acq_date": "2020-01-03",
    })
    body, _ = pack_with_lineage([item], budget=3000)
    metadata = json.loads(body.splitlines()[0].removeprefix("[EVIDENCE] "))
    assert metadata["published_at"] is None and metadata.get("observed_at") is None
    assert metadata.get("ingested_at") == "2026-10-10T00:00:00+00:00"


def test_self_declared_verified_artifact_is_not_accepted_as_fact_checked():
    item = to_evidence_item({"title": "synthetic", "content": "synthetic", "score": 0.9})
    forged = evidence_artifact([item])
    forged[0]["verification_status"] = "verified"
    assert evidence_items_from_artifact(forged) == []


@pytest.mark.parametrize("axis", ["published_at", "observed_at", "ingested_at"])
def test_utc_underflow_is_unknown_without_losing_other_evidence(axis):
    item = to_evidence_item({
        "title": "synthetic", "content": "synthetic", "score": 0.9,
        "source_type": "dataset", "provider": "fixture.example.invalid",
        axis: "0001-01-01T00:00:00+23:00",
    })
    assert item.excerpt == "synthetic"
    assert getattr(item.source if axis == "published_at" else item, axis) is None


@pytest.mark.parametrize("axis", ["published_at", "observed_at", "ingested_at"])
def test_numeric_date_like_value_is_not_reinterpreted_as_an_iso_time(axis):
    item = to_evidence_item({"title": "synthetic", "content": "synthetic", "score": .9,
        "source_type": "dataset", "provider": "fixture.example.invalid", axis: 20261010})
    assert getattr(item.source if axis == "published_at" else item, axis) is None
