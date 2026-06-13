from datetime import UTC, datetime

from app.cypher.incident_write import INCIDENT_UPSERT
from app.models.incident import Incident, IncidentStatus
from app.services._loc_key import incident_key
from app.services.incident_store import _upsert_params


def test_incident_upsert_wires_location():
    assert "loc_key" in INCIDENT_UPSERT
    assert ":Location" in INCIDENT_UPSERT
    assert "OCCURRED_AT" in INCIDENT_UPSERT
    assert "country_centroid" not in INCIDENT_UPSERT  # incidents are precise
    assert "geo_basis" in INCIDENT_UPSERT


def test_incident_upsert_location_is_conditional_on_coords():
    assert "FOREACH" in INCIDENT_UPSERT


def test_upsert_params_sets_loc_key():
    rec = Incident(
        id="inc1", kind="manual", title="t", severity="low",
        coords=(48.0, 37.8), location="Donetsk", status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC), sources=[], layer_hints=[], timeline=[],
    )
    params = _upsert_params(rec, 0)
    assert params["loc_key"] == "incident:donetsk"
    assert params["lat"] == 48.0 and params["lon"] == 37.8


def test_vendored_loc_key_matches_canonical():
    assert incident_key("Donetsk", 48.0, 37.8) == "incident:donetsk"
    assert incident_key("", 48.0, 37.8) == "geo:48.000,37.800"
