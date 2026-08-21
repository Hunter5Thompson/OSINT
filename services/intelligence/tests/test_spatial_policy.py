from __future__ import annotations

import pytest
from qdrant_client import models

from rag import corpus_policy


def _spatial_filter() -> models.Filter:
    from spatial import (
        RetrievalSpatialRelation,
        ScopeKind,
        SpatialScopeTokenV1,
        compile_qdrant_scope_filter,
    )

    token = SpatialScopeTokenV1(
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision="spatial-derive-v1-d30efa07e141",
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=("spatial-derive-v1-d30efa07e141",),
    )
    compiled = compile_qdrant_scope_filter(
        token,
        RetrievalSpatialRelation.EITHER,
    )
    assert compiled is not None
    return compiled


@pytest.mark.parametrize(
    "base_factory",
    [corpus_policy.analysis_filter, corpus_policy.realtime_filter],
)
def test_spatial_filter_nests_without_mutating_or_weakening_corpus_policy(
    base_factory,
) -> None:
    from spatial import combine_filters

    base = base_factory()
    assert isinstance(base, models.Filter)
    before = base.model_dump(mode="json", exclude_none=True)
    spatial = _spatial_filter()

    combined = combine_filters(base, spatial)

    assert base.model_dump(mode="json", exclude_none=True) == before
    assert combined.model_dump(mode="json", exclude_none=True) == {
        "must": [
            before,
            spatial.model_dump(mode="json", exclude_none=True),
        ]
    }


def test_world_none_returns_the_original_corpus_filter_object() -> None:
    from spatial import combine_filters

    base = corpus_policy.analysis_filter()

    assert combine_filters(base, None) is base
