import pytest
from pydantic import ValidationError

from app.models.spatial import ScopeKind, SpatialScopeTokenV1
from app.models.timeline import (
    EventSample,
    SpatialApplicationV1,
    SpatialCompleteness,
    SpatialFilterMode,
    TrackPoint,
    TrackSample,
    WindowResponse,
)

CATALOG_REVISION = "spatial-v1-0123456789ab"
DERIVATION_REVISION = "spatial-derive-v1-0123456789ab"


def _legacy_global_application() -> SpatialApplicationV1:
    return SpatialApplicationV1(
        requested_scope_key=None,
        catalog_revision=None,
        derivation_revision=None,
        boundary_policy=None,
        relation="occurs-in",
        mode=SpatialFilterMode.GLOBAL,
        completeness=SpatialCompleteness.COMPLETE,
        included_count=0,
        excluded_unlocated_count=0,
        excluded_conflict_count=0,
        excluded_stale_revision_count=0,
        excluded_unsupported_count=0,
    )


def test_event_sample_defaults_nullable():
    s = EventSample(id="ev-1", time="2026-05-01T00:00:00Z", time_basis="indexed")
    assert s.kind == "event"
    assert s.title is None and s.severity is None and s.lat is None


def test_track_sample_roundtrip():
    s = TrackSample(
        id="abc123",
        icao24="abc123",
        points=[TrackPoint(ts_ms=1_700_000_000_000, lat=1.0, lon=2.0)],
    )
    assert s.kind == "track"
    assert s.points[0].ts_ms == 1_700_000_000_000


def test_window_response_shape():
    r = WindowResponse(
        domain="events", tier="coarse",
        t_start="2026-05-01T00:00:00Z", t_end="2026-05-02T00:00:00Z",
        bbox=None, samples=[], total_count=0, truncated=False,
        spatial_application=_legacy_global_application(),
    )
    assert r.truncated is False and r.samples == []


def test_structured_spatial_scope_token_requires_current_compatible_revision():
    token = SpatialScopeTokenV1(
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        catalog_revision=CATALOG_REVISION,
        derivation_revision=DERIVATION_REVISION,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(DERIVATION_REVISION,),
    )

    assert token.schema_version == 1
    assert token.scope_key == "country:UKR"
    assert token.compatible_derivation_revisions == (DERIVATION_REVISION,)


def test_spatial_scope_token_rejects_invalid_revision_and_unknown_schema():
    base = {
        "scope_key": "country:UKR",
        "kind": "country",
        "catalog_revision": CATALOG_REVISION,
        "derivation_revision": DERIVATION_REVISION,
        "boundary_policy": "odin-reference-v1",
        "compatible_derivation_revisions": [DERIVATION_REVISION],
    }

    with pytest.raises(ValidationError):
        SpatialScopeTokenV1.model_validate({**base, "catalog_revision": "latest"})
    with pytest.raises(ValidationError):
        SpatialScopeTokenV1.model_validate({**base, "schema_version": 2})
    with pytest.raises(ValidationError):
        SpatialScopeTokenV1.model_validate({**base, "unexpected": True})


def test_new_client_world_token_is_echoed_without_becoming_legacy_tokenless_global():
    application = SpatialApplicationV1(
        requested_scope_key="world",
        catalog_revision=CATALOG_REVISION,
        derivation_revision=DERIVATION_REVISION,
        boundary_policy="odin-reference-v1",
        relation="occurs-in",
        mode="global",
        completeness="complete",
        included_count=7,
        excluded_unlocated_count=0,
        excluded_conflict_count=0,
        excluded_stale_revision_count=0,
        excluded_unsupported_count=0,
    )

    assert application.requested_scope_key == "world"
    assert application.catalog_revision == CATALOG_REVISION
    assert application.derivation_revision == DERIVATION_REVISION
    assert application.boundary_policy == "odin-reference-v1"
    assert application.mode is SpatialFilterMode.GLOBAL


def test_spatial_application_requires_reported_unsupported_count():
    payload = _legacy_global_application().model_dump(mode="json")
    payload.pop("excluded_unsupported_count")

    with pytest.raises(ValidationError):
        SpatialApplicationV1.model_validate(payload)


def test_legacy_tokenless_global_application_has_explicit_global_semantics():
    application = _legacy_global_application()

    assert application.requested_scope_key is None
    assert application.catalog_revision is None
    assert application.mode is SpatialFilterMode.GLOBAL
    assert application.completeness is SpatialCompleteness.COMPLETE


def test_bbox_application_accounts_distinct_included_and_excluded_records():
    application = SpatialApplicationV1(
        requested_scope_key="country:FJI",
        catalog_revision=CATALOG_REVISION,
        derivation_revision=DERIVATION_REVISION,
        boundary_policy="odin-reference-v1",
        relation="intersects",
        mode="bbox_approximate",
        completeness="partial",
        included_count=11,
        excluded_unlocated_count=3,
        excluded_conflict_count=2,
        excluded_stale_revision_count=1,
        excluded_unsupported_count=4,
    )

    assert application.relation == "intersects"
    assert application.included_count == 11
    assert application.excluded_unlocated_count == 3
    assert application.excluded_conflict_count == 2
    assert application.excluded_stale_revision_count == 1
    assert application.excluded_unsupported_count == 4


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("relation", "contains"),
        ("mode", "best_effort"),
        ("completeness", "unknown"),
    ],
)
def test_spatial_application_rejects_unknown_schema_and_enums(field: str, value: object):
    payload = _legacy_global_application().model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError):
        SpatialApplicationV1.model_validate(payload)


def test_spatial_application_rejects_unknown_fields():
    payload = _legacy_global_application().model_dump(mode="json")
    payload["precision_hint"] = "exact"

    with pytest.raises(ValidationError):
        SpatialApplicationV1.model_validate(payload)


from app.models.timeline import (  # noqa: E402
    EventDetail,
    GeoEvent,
    HistogramBucket,
    HistogramResponse,
    Notable,
)


def test_histogram_bucket_defaults():
    b = HistogramBucket(ts="2026-06-01T00:00:00Z", count=3, dominant_category="civil")
    assert b.by_category == {} and b.by_severity == {}


def test_histogram_response_shape():
    r = HistogramResponse(
        t_start="a", t_end="b", bucket_ms=1000, buckets=[],
        notables=[], geo_events=[], total_count=0,
        geo_located_count=0, geo_truncated=False,
        spatial_application=_legacy_global_application(),
    )
    assert r.notables == [] and r.geo_truncated is False


def test_notable_and_geo_and_detail():
    n = Notable(id="e1", time="t", time_basis="indexed", severity="high",
                is_incident=False, rank=0)
    g = GeoEvent(id="e1", time="t", codebook_type="military.x", severity="high",
                 lat=1.0, lon=2.0, is_incident=False)
    d = EventDetail(id="e1", time="t", time_basis="indexed")
    assert n.severity == "high" and g.lat == 1.0 and d.title is None
