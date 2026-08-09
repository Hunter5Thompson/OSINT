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


def _point(point_id: int, *, occurrence: list[str]) -> models.PointStruct:
    return models.PointStruct(
        id=point_id,
        vector=[1.0, 0.0],
        payload={
            "spatial_about_scope_revision_tokens": [],
            "spatial_occurrence_scope_revision_tokens": occurrence,
            "spatial_conflict": False,
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
                    ),
                    models.FieldCondition(
                        key="spatial_conflict",
                        match=models.MatchValue(value=False),
                    ),
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


def test_shared_contract_pins_the_reviewed_ua14_pair_tokens() -> None:
    from spatial import encode_scope_revision_token

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
    assert payload["spatial_occurrence_scope_revision_tokens"] == [
        encode_scope_revision_token(COUNTRY_SCOPE, COUNTRY_REVISION),
        encode_scope_revision_token(ADMIN1_SCOPE, ADMIN1_REVISION),
    ]
