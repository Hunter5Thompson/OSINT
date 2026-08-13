from datetime import UTC, datetime

from app.cypher.incident_write import INCIDENT_UPSERT
from app.models.incident import Incident, IncidentStatus
from app.services._loc_key import incident_key
from app.services.incident_store import _upsert_params
from app.services.spatial_catalog import IncidentSpatialProjection


def test_incident_upsert_wires_location():
    assert "loc_key" in INCIDENT_UPSERT
    assert ":Location" in INCIDENT_UPSERT
    assert "OCCURRED_AT" in INCIDENT_UPSERT
    assert "country_centroid" not in INCIDENT_UPSERT  # incidents are precise
    assert "geo_basis" in INCIDENT_UPSERT


def test_incident_upsert_wires_catalog_owned_spatial_fields():
    for field in (
        "country_scope_key",
        "admin1_scope_key",
        "admin2_scope_key",
        "spatial_basis",
        "spatial_precision",
        "spatial_catalog_revision",
        "spatial_derivation_revision",
        "spatial_conflict",
        "spatial_conflict_scope_keys",
        "spatial_derivation_status",
    ):
        assert f"l.{field} = ${field}" in INCIDENT_UPSERT


def test_incident_upsert_location_is_conditional_on_coords():
    assert "FOREACH" in INCIDENT_UPSERT


def test_upsert_params_sets_loc_key():
    rec = Incident(
        id="inc1", kind="manual", title="t", severity="low",
        coords=(48.0, 37.8), location="Donetsk", status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC), sources=[], layer_hints=[], timeline=[],
    )
    params = _upsert_params(rec, 0)
    assert params["loc_key"] == "incident:donetsk@48.000,37.800"
    assert params["lat"] == 48.0 and params["lon"] == 37.8


def test_upsert_params_carries_incident_spatial_projection():
    rec = Incident(
        id="inc1", kind="manual", title="t", severity="low",
        coords=(48.0, 37.8), location="Donetsk", status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC), sources=[], layer_hints=[], timeline=[],
    )
    projection = IncidentSpatialProjection(
        spatial_catalog_revision="spatial-v1-e76a16bff799",
        spatial_derivation_revision="spatial-derive-v1-d30efa07e141",
        country_scope_key="country:UKR",
        admin1_scope_key="admin1:UKR:UA-14",
        admin2_scope_key=None,
        spatial_basis="coordinate",
        spatial_precision="point",
        spatial_conflict=False,
        spatial_conflict_scope_keys=(),
        spatial_derivation_status="resolved",
    )

    params = _upsert_params(rec, 0, projection)

    assert params["spatial_write"] is True
    assert params["country_scope_key"] == "country:UKR"
    assert params["admin1_scope_key"] == "admin1:UKR:UA-14"
    assert params["admin2_scope_key"] is None
    assert params["spatial_catalog_revision"] == "spatial-v1-e76a16bff799"
    assert params["spatial_derivation_revision"] == "spatial-derive-v1-d30efa07e141"
    assert params["spatial_conflict"] is False
    assert params["spatial_conflict_scope_keys"] == []
    assert params["spatial_derivation_status"] == "resolved"


def test_vendored_loc_key_matches_canonical():
    assert incident_key("Donetsk", 48.0, 37.8) == "incident:donetsk@48.000,37.800"
    assert incident_key("", 48.0, 37.8) == "geo:48.000,37.800"


def test_incident_upsert_skips_null_island():
    # (0,0) is the non-spatial sentinel (ClusterStore map:no_pin) -> no Location
    assert "($lat = 0.0 AND $lon = 0.0)" in INCIDENT_UPSERT
