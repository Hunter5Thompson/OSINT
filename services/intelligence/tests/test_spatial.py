"""Contract tests for relation-specific Qdrant spatial filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

COUNTRY_SCOPE = "country:UKR"
COUNTRY_REVISION = "spatial-derive-v1-d30efa07e141"
ADMIN1_SCOPE = "admin1:iso3166-2:UA-14"
ADMIN1_REVISION = "spatial-derive-v1-4d1de888e0c7"
INCOMPATIBLE_REVISION = "spatial-derive-v1-000000000000"
CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "qdrant-spatial-payload-v1.json"
)


def _scope_token(
    *,
    scope_key: str = COUNTRY_SCOPE,
    kind: str = "country",
    derivation_revision: str = COUNTRY_REVISION,
    compatible: tuple[str, ...] | None = None,
):
    from spatial import ScopeKind, SpatialScopeTokenV1

    return SpatialScopeTokenV1(
        scope_key=scope_key,
        kind=ScopeKind(kind),
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision=derivation_revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=compatible or (derivation_revision,),
    )


def _point(
    point_id: int,
    *,
    occurrence: list[str],
    conflict: bool = False,
) -> models.PointStruct:
    return models.PointStruct(
        id=point_id,
        vector=[1.0, 0.0],
        payload={
            "spatial_about_scope_revision_tokens": [],
            "spatial_occurrence_scope_revision_tokens": occurrence,
            "spatial_conflict": conflict,
        },
    )


def _matching_ids(
    client: QdrantClient,
    query_filter: models.Filter,
) -> list[int | str]:
    points, _ = client.scroll(
        collection_name="spatial-contract",
        scroll_filter=query_filter,
        limit=10,
    )
    return [point.id for point in points]


def test_admin1_point_matches_child_and_parent_only_with_correlated_revision() -> None:
    from spatial import encode_scope_revision_token

    valid = _point(
        1,
        occurrence=[
            encode_scope_revision_token(COUNTRY_SCOPE, COUNTRY_REVISION),
            encode_scope_revision_token(ADMIN1_SCOPE, ADMIN1_REVISION),
        ],
    )
    cross_pair_poison = _point(
        2,
        occurrence=[
            encode_scope_revision_token(COUNTRY_SCOPE, ADMIN1_REVISION),
            encode_scope_revision_token(ADMIN1_SCOPE, COUNTRY_REVISION),
        ],
    )
    incompatible = _point(
        3,
        occurrence=[
            encode_scope_revision_token(COUNTRY_SCOPE, INCOMPATIBLE_REVISION),
            encode_scope_revision_token(ADMIN1_SCOPE, INCOMPATIBLE_REVISION),
        ],
    )

    client = QdrantClient(":memory:")
    try:
        client.create_collection(
            collection_name="spatial-contract",
            vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
        )
        client.upsert(
            collection_name="spatial-contract",
            points=[valid, cross_pair_poison, incompatible],
        )

        def occurrence_filter(scope_key: str, revision: str) -> models.Filter:
            return models.Filter(
                must=[
                    models.FieldCondition(
                        key="spatial_occurrence_scope_revision_tokens",
                        match=models.MatchAny(
                            any=[encode_scope_revision_token(scope_key, revision)]
                        ),
                    )
                ]
            )

        assert _matching_ids(
            client,
            occurrence_filter(COUNTRY_SCOPE, COUNTRY_REVISION),
        ) == [1]
        assert _matching_ids(
            client,
            occurrence_filter(ADMIN1_SCOPE, ADMIN1_REVISION),
        ) == [1]
    finally:
        client.close()


def test_scope_revision_token_encoding_is_injective_and_strict() -> None:
    from spatial import SpatialContractError, encode_scope_revision_token

    country = encode_scope_revision_token(COUNTRY_SCOPE, COUNTRY_REVISION)
    admin1 = encode_scope_revision_token(ADMIN1_SCOPE, ADMIN1_REVISION)

    assert country == f"sr1|{COUNTRY_SCOPE}|{COUNTRY_REVISION}"
    assert admin1 == f"sr1|{ADMIN1_SCOPE}|{ADMIN1_REVISION}"
    assert country != admin1
    assert country.split("|") == ["sr1", COUNTRY_SCOPE, COUNTRY_REVISION]

    with pytest.raises(SpatialContractError, match="scope"):
        encode_scope_revision_token("world", COUNTRY_REVISION)
    with pytest.raises(SpatialContractError, match="scope"):
        encode_scope_revision_token("country:UKR|poison", COUNTRY_REVISION)
    with pytest.raises(SpatialContractError, match="revision"):
        encode_scope_revision_token(COUNTRY_SCOPE, "spatial-v1-not-a-derivation")
    oversized_revision = f"spatial-derive-v{'9' * 200}-{'a' * 12}"
    with pytest.raises(SpatialContractError, match="229 ASCII bytes"):
        encode_scope_revision_token(COUNTRY_SCOPE, oversized_revision)


def test_lane_coverage_requires_named_exhaustive_accounting() -> None:
    from pydantic import ValidationError

    from spatial import SpatialLaneCoverageV1

    coverage = SpatialLaneCoverageV1(
        lane="analysis",
        total_points=100,
        filterable_points=45,
        conflict_points=5,
        stale_points=5,
        unsupported_points=10,
        unprojected_points=20,
        audit_only_points=10,
        inconsistent_points=5,
    )

    assert coverage.unprojected_points == 20
    assert coverage.audit_only_points == 10
    assert coverage.inconsistent_points == 5
    with pytest.raises(ValidationError, match="must equal total points"):
        SpatialLaneCoverageV1(
            lane="analysis",
            total_points=100,
            filterable_points=45,
            conflict_points=5,
            stale_points=5,
            unsupported_points=10,
            unprojected_points=20,
            audit_only_points=9,
            inconsistent_points=5,
        )


def test_shared_contract_pins_the_reviewed_ua14_pair_tokens() -> None:
    from spatial import (
        MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES,
        encode_scope_revision_token,
    )

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    token_contract = contract["scope_revision_token"]
    payload = contract["vectors"][0]["payload"]

    assert token_contract == {
        "prefix": "sr1",
        "separator": "|",
        "maximum_ascii_bytes": 229,
        "about_field": "spatial_about_scope_revision_tokens",
        "occurrence_field": "spatial_occurrence_scope_revision_tokens",
    }
    assert token_contract["maximum_ascii_bytes"] == (
        MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES
    )
    assert contract["conflict_admission"] == {
        "retrieval_authority": "positive-pair-tokens",
        "suppression_granularity": "same-relation-and-exact-scope",
        "record_conflict_fields": "unindexed-audit-only",
        "mixed_status": "filterable-when-any-token-is-admitted",
    }
    assert payload["spatial_occurrence_scope_revision_tokens"] == [
        encode_scope_revision_token(COUNTRY_SCOPE, COUNTRY_REVISION),
        encode_scope_revision_token(ADMIN1_SCOPE, ADMIN1_REVISION),
    ]


def test_world_scope_compiles_to_no_qdrant_filter() -> None:
    from spatial import RetrievalSpatialRelation, compile_qdrant_scope_filter

    token = _scope_token(scope_key="world", kind="world")

    assert compile_qdrant_scope_filter(
        token,
        RetrievalSpatialRelation.EITHER,
    ) is None


@pytest.mark.parametrize(
    ("relation", "relation_tree"),
    [
        (
            "about",
            {
                "key": "spatial_about_scope_revision_tokens",
                "match": {
                    "any": [
                        f"sr1|{COUNTRY_SCOPE}|{COUNTRY_REVISION}",
                        f"sr1|{COUNTRY_SCOPE}|{INCOMPATIBLE_REVISION}",
                    ]
                },
            },
        ),
        (
            "occurrence",
            {
                "key": "spatial_occurrence_scope_revision_tokens",
                "match": {
                    "any": [
                        f"sr1|{COUNTRY_SCOPE}|{COUNTRY_REVISION}",
                        f"sr1|{COUNTRY_SCOPE}|{INCOMPATIBLE_REVISION}",
                    ]
                },
            },
        ),
        (
            "either",
            {
                "should": [
                    {
                        "key": "spatial_about_scope_revision_tokens",
                        "match": {
                            "any": [
                                f"sr1|{COUNTRY_SCOPE}|{COUNTRY_REVISION}",
                                f"sr1|{COUNTRY_SCOPE}|{INCOMPATIBLE_REVISION}",
                            ]
                        },
                    },
                    {
                        "key": "spatial_occurrence_scope_revision_tokens",
                        "match": {
                            "any": [
                                f"sr1|{COUNTRY_SCOPE}|{COUNTRY_REVISION}",
                                f"sr1|{COUNTRY_SCOPE}|{INCOMPATIBLE_REVISION}",
                            ]
                        },
                    },
                ]
            },
        ),
    ],
)
def test_scope_filter_model_tree_is_relation_specific_and_compatibility_paired(
    relation: str,
    relation_tree: dict[str, object],
) -> None:
    from spatial import RetrievalSpatialRelation, compile_qdrant_scope_filter

    token = _scope_token(
        compatible=(COUNTRY_REVISION, INCOMPATIBLE_REVISION),
    )

    compiled = compile_qdrant_scope_filter(
        token,
        RetrievalSpatialRelation(relation),
    )

    assert compiled is not None
    assert compiled.model_dump(mode="json", exclude_none=True) == {
        "must": [relation_tree]
    }


def test_admin1_compiler_excludes_cross_pair_and_stale_points() -> None:
    from spatial import RetrievalSpatialRelation, compile_qdrant_scope_filter

    valid = _point(
        1,
        occurrence=[
            f"sr1|{COUNTRY_SCOPE}|{COUNTRY_REVISION}",
            f"sr1|{ADMIN1_SCOPE}|{ADMIN1_REVISION}",
        ],
    )
    cross_pair = _point(
        2,
        occurrence=[f"sr1|{ADMIN1_SCOPE}|{COUNTRY_REVISION}"],
    )
    stale = _point(
        3,
        occurrence=[f"sr1|{ADMIN1_SCOPE}|{INCOMPATIBLE_REVISION}"],
    )
    client = QdrantClient(":memory:")
    try:
        client.create_collection(
            collection_name="spatial-contract",
            vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
        )
        client.upsert(
            collection_name="spatial-contract",
            points=[valid, cross_pair, stale],
        )
        compiled = compile_qdrant_scope_filter(
            _scope_token(
                scope_key=ADMIN1_SCOPE,
                kind="admin1",
                derivation_revision=ADMIN1_REVISION,
            ),
            RetrievalSpatialRelation.OCCURRENCE,
        )
        assert compiled is not None
        assert _matching_ids(client, compiled) == [1]
    finally:
        client.close()


def test_scope_compiler_trusts_admitted_tokens_on_mixed_conflict_points() -> None:
    from spatial import RetrievalSpatialRelation, compile_qdrant_scope_filter

    mixed = _point(
        1,
        occurrence=[f"sr1|{COUNTRY_SCOPE}|{COUNTRY_REVISION}"],
        conflict=True,
    )
    client = QdrantClient(":memory:")
    try:
        client.create_collection(
            collection_name="spatial-contract",
            vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
        )
        client.upsert(collection_name="spatial-contract", points=[mixed])
        compiled = compile_qdrant_scope_filter(
            _scope_token(),
            RetrievalSpatialRelation.OCCURRENCE,
        )
        assert compiled is not None
        assert _matching_ids(client, compiled) == [1]
    finally:
        client.close()


def test_compiler_rejects_non_allowlisted_relation_and_field_injection() -> None:
    from pydantic import ValidationError

    from spatial import (
        SpatialContractError,
        compile_qdrant_scope_filter,
    )

    with pytest.raises(ValueError):
        _scope_token(scope_key="country:UKR|payload.poison")
    with pytest.raises(SpatialContractError, match="relation"):
        compile_qdrant_scope_filter(_scope_token(), "payload.poison")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        _scope_token(
            compatible=(COUNTRY_REVISION,)
            + tuple(
                f"spatial-derive-v1-{value:012x}"
                for value in range(8)
            ),
        )


def test_one_and_two_box_aoi_adapters_build_non_wrapping_geo_filters() -> None:
    from spatial import QdrantAoiBoxV1, compile_qdrant_aoi_filter

    west = QdrantAoiBoxV1(west=170.0, south=-10.0, east=180.0, north=10.0)
    east = QdrantAoiBoxV1(west=-180.0, south=-10.0, east=-170.0, north=10.0)

    single = compile_qdrant_aoi_filter((west,))
    segmented = compile_qdrant_aoi_filter((west, east))

    assert single.model_dump(mode="json", exclude_none=True) == {
        "must": [
            {
                "key": "geo",
                "geo_bounding_box": {
                    "top_left": {"lon": 170.0, "lat": 10.0},
                    "bottom_right": {"lon": 180.0, "lat": -10.0},
                },
            }
        ]
    }
    segmented_tree = segmented.model_dump(mode="json", exclude_none=True)
    assert segmented_tree["must"][0] == {
        "should": [
            single.model_dump(mode="json", exclude_none=True)["must"][0],
            {
                "key": "geo",
                "geo_bounding_box": {
                    "top_left": {"lon": -180.0, "lat": 10.0},
                    "bottom_right": {"lon": -170.0, "lat": -10.0},
                },
            },
        ]
    }

    with pytest.raises(ValueError, match="non-wrapping"):
        QdrantAoiBoxV1(west=170.0, south=-10.0, east=-170.0, north=10.0)
