"""Structured GDELT ActionGeo evidence adapters."""

from __future__ import annotations

from gdelt_raw.schemas import GDELTEventWrite
from graph_integrity.spatial_normalizer import CountryCodeSystem, RawLocationIdentity


def raw_location_identity_for_event(
    event: GDELTEventWrite,
) -> RawLocationIdentity | None:
    """Return only structured codes/coordinates; reject GDELT's 0/0 sentinel."""

    latitude = event.action_geo_lat
    longitude = event.action_geo_long
    if latitude == 0.0 and longitude == 0.0:
        return None
    if (latitude is None) != (longitude is None):
        latitude = None
        longitude = None
    if not event.action_geo_country_code and latitude is None:
        return None
    return RawLocationIdentity(
        country_code=event.action_geo_country_code or None,
        country_code_system=(
            CountryCodeSystem.GDELT_GEC
            if event.action_geo_country_code
            else None
        ),
        latitude=latitude,
        longitude=longitude,
    )


__all__ = ["raw_location_identity_for_event"]
