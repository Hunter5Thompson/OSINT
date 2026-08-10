import pytest
from pydantic import ValidationError

from app.models.intel import (
    IntelQuery,
    RetrievalSpatialRelation,
    SpatialRunConsumerApplication,
)

SPATIAL_REF = {
    "schema_version": 1,
    "scope_key": "country:UKR",
    "catalog_revision": "spatial-v1-e76a16bff799",
    "boundary_policy": "odin-reference-v1",
}


def test_intel_query_accepts_public_http_image_url() -> None:
    query = IntelQuery(query="analyze", image_url="https://example.org/image.jpg")

    assert query.image_url == "https://example.org/image.jpg"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/image.jpg",
        "http://localhost/image.jpg",
        "http://127.0.0.1/image.jpg",
        "http://10.0.0.5/image.jpg",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/image.jpg",
        "http://camera.local/image.jpg",
    ],
)
def test_intel_query_rejects_non_public_image_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        IntelQuery(query="analyze", image_url=url)


def test_intel_query_defaults_spatial_relation_to_either() -> None:
    query = IntelQuery(query="analyze", spatial_scope=SPATIAL_REF)

    assert query.spatial_relation is RetrievalSpatialRelation.EITHER


def test_spatial_run_consumer_rejects_unrepresented_not_applicable_mode() -> None:
    with pytest.raises(ValidationError):
        SpatialRunConsumerApplication(
            status="applied",
            mode="not-applicable",  # type: ignore[arg-type]
            completeness="complete",
        )


@pytest.mark.parametrize(
    "override",
    [
        {"region": "Ukraine"},
        {"use_legacy": True},
    ],
)
def test_intel_query_rejects_legacy_controls_with_spatial_scope(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        IntelQuery(query="analyze", spatial_scope=SPATIAL_REF, **override)


@pytest.mark.parametrize(
    "untrusted_field",
    [
        {"kind": "country"},
        {"derivation_revision": "spatial-derive-v1-000000000000"},
        {
            "compatible_derivation_revisions": [
                "spatial-derive-v1-000000000000",
            ]
        },
    ],
)
def test_intel_query_rejects_browser_supplied_token_fields(
    untrusted_field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        IntelQuery(
            query="analyze",
            spatial_scope={**SPATIAL_REF, **untrusted_field},
        )
