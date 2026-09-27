"""Source-owned coordinate evidence shared by graph and vector writers.

Names, theatre boxes and extracted prose never enter this adapter. A stable
source identity plus a valid coordinate pair is required for occurrence evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, TypedDict

from graph_integrity.spatial_normalizer import (
    RawLocationIdentity,
    SpatialNormalizationIndex,
    normalize_location,
    spatial_property_parameters,
)
from qdrant_spatial import (
    SpatialCrosswalkStatus,
    SpatialEvidenceKind,
    SpatialEvidenceV1,
    SpatialRelation,
    project_spatial_payload,
    unavailable_spatial_payload,
)


class GraphFragment(TypedDict):
    cypher: str
    parameters: dict[str, Any]


SOURCE_ID_FIELDS = {
    "usgs": "usgs_id",
    "firms": "content_hash",
    "ucdp": "ucdp_id",
    "eonet": "eonet_id",
    "gdacs": "gdacs_id",
}


def source_location(payload: Mapping[str, object]) -> RawLocationIdentity | None:
    source = payload.get("source")
    identity_field = SOURCE_ID_FIELDS.get(str(source))
    if identity_field is None or not payload.get(identity_field):
        return None
    if source == "ucdp" and str(payload.get("where_prec")) != "1":
        # UCDP where_prec 2..7 describe vicinity/areas/estimated points, not an
        # exact event location. Missing legacy precision cannot be reconstructed.
        return None
    latitude, longitude = payload.get("latitude"), payload.get("longitude")
    if latitude is None or longitude is None or (latitude == 0 and longitude == 0):
        return None
    try:
        return RawLocationIdentity(latitude=latitude, longitude=longitude)
    except ValueError:
        return None


def project_feed_spatial(
    payload: Mapping[str, object],
    index: SpatialNormalizationIndex,
) -> dict[str, object]:
    raw = source_location(payload)
    if raw is None:
        empty = project_spatial_payload([], index)
        empty.update(
            unavailable_spatial_payload(
                "source identity, precise location evidence or valid coordinates unavailable"
            )
        )
        empty["geo"] = None
        return empty
    source = str(payload["source"])
    return project_spatial_payload(
        [
            SpatialEvidenceV1(
                relation=SpatialRelation.OCCURRENCE,
                evidence_kind=(
                    SpatialEvidenceKind.SENSOR_COORDINATE
                    if source in {"usgs", "firms"}
                    else SpatialEvidenceKind.STRUCTURED_EVENT_LOCATION
                ),
                evidence_id=f"{source}:{payload[SOURCE_ID_FIELDS[source]]}",
                normalization=normalize_location(raw, index),
                confidence=1.0,
                crosswalk_status=SpatialCrosswalkStatus.NOT_REQUIRED,
            ),
        ],
        index,
    )


def _location_projection(
    payload: Mapping[str, object],
    index: SpatialNormalizationIndex,
) -> GraphFragment | None:
    """Parameterized graph projection of the same evidence used by Qdrant."""
    raw = source_location(payload)
    if raw is None:
        return None
    source = str(payload["source"])
    identity = f"{source}:{payload[SOURCE_ID_FIELDS[source]]}"
    loc_key = "sensor-observation:" + hashlib.sha256(identity.encode()).hexdigest()
    normalized = normalize_location(raw, index)
    return {
        "cypher": (
            " SET l.geo_basis = 'sensor_coordinate', l.source = $location_source, "
            " l.coordinate_basis = $coordinate_basis, "
            " l.source_time_start = $source_time_start, l.source_time_end = $source_time_end, "
            " l.lat = $latitude, l.lon = $longitude, "
            " l.geo = point({latitude: $latitude, longitude: $longitude}), "
            " l.country_iso3 = $country_iso3, l.country_scope_key = $country_scope_key, "
            " l.admin1_code = $admin1_code, l.admin2_code = $admin2_code, "
            " l.admin1_scope_key = $admin1_scope_key, l.admin2_scope_key = $admin2_scope_key, "
            " l.spatial_basis = $spatial_basis, l.spatial_precision = $spatial_precision, "
            " l.spatial_catalog_revision = $spatial_catalog_revision, "
            " l.spatial_derivation_revision = $spatial_derivation_revision, "
            " l.spatial_conflict = $spatial_conflict, "
            " l.spatial_conflict_scope_keys = $spatial_conflict_scope_keys "
        ),
        "parameters": {
            "loc_key": loc_key,
            "location_source": source,
            "coordinate_basis": {
                "usgs": "reported_epicenter",
                "firms": "thermal_observation",
                "ucdp": "ucdp_where_prec_1",
                "eonet": "reported_point",
                "gdacs": "reported_centroid",
            }[source],
            "source_time_start": next(
                (
                    payload[key]
                    for key in (
                        "event_time",
                        "acq_date",
                        "date_start",
                        "event_date",
                        "from_date",
                    )
                    if payload.get(key)
                ),
                None,
            ),
            "source_time_end": payload.get("date_end") or payload.get("to_date"),
            "latitude": raw.latitude,
            "longitude": raw.longitude,
            **spatial_property_parameters(normalized),
        },
    }


def observation_geo_fragment(
    payload: Mapping[str, object],
    index: SpatialNormalizationIndex,
) -> GraphFragment | None:
    projection = _location_projection(payload, index)
    if projection is None:
        return None
    return {
        **projection,
        "cypher": " MERGE (l:Location {loc_key: $loc_key}) "
        + projection["cypher"]
        + " MERGE (ev)-[:OCCURRED_AT]->(l)",
    }


def observation_refresh_fragment(
    payload: Mapping[str, object],
    index: SpatialNormalizationIndex,
) -> GraphFragment | None:
    """Refresh mutable source coordinates without inventing another Event."""
    projection = _location_projection(payload, index)
    if projection is None:
        source = str(payload.get("source"))
        identity_field = SOURCE_ID_FIELDS.get(source)
        if identity_field is None or not payload.get(identity_field):
            return None
        identity = f"{source}:{payload[identity_field]}"
        return {
            "cypher": """
MATCH (l:Location {loc_key: $loc_key})
SET l.lat = null, l.lon = null, l.geo = null,
    l.country_iso3 = null, l.country_scope_key = null,
    l.admin1_code = null, l.admin2_code = null,
    l.admin1_scope_key = null, l.admin2_scope_key = null,
    l.spatial_basis = null, l.spatial_precision = null,
    l.spatial_derivation_revision = null, l.spatial_conflict = false,
    l.spatial_conflict_scope_keys = [], l.spatial_catalog_revision = $catalog_revision
RETURN count(l) AS refreshed
""",
            "parameters": {
                "loc_key": "sensor-observation:" + hashlib.sha256(identity.encode()).hexdigest(),
                "catalog_revision": index.catalog_revision,
            },
        }
    return {
        **projection,
        "cypher": " MATCH (l:Location {loc_key: $loc_key}) "
        + projection["cypher"]
        + " RETURN count(l) AS refreshed",
    }
