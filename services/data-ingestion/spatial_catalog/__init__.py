"""Deterministic offline spatial-catalog contracts."""

from spatial_catalog.identity import (
    COUNTRY_CROSSWALK_PATH,
    CountryCrosswalk,
    CountryCrosswalkRecord,
    CountryIdentityResolutionError,
    InvalidScopeKeyError,
    ParsedScopeKey,
    load_country_crosswalk,
    normalize_scope_key_candidate,
    parse_scope_key,
    resolve_country,
)
from spatial_catalog.models import (
    AssetId,
    CatalogRevision,
    DerivationRevision,
    ScopeKey,
    ScopeKind,
)

__all__ = [
    "AssetId",
    "CatalogRevision",
    "COUNTRY_CROSSWALK_PATH",
    "CountryCrosswalk",
    "CountryCrosswalkRecord",
    "CountryIdentityResolutionError",
    "DerivationRevision",
    "InvalidScopeKeyError",
    "ParsedScopeKey",
    "ScopeKey",
    "ScopeKind",
    "load_country_crosswalk",
    "normalize_scope_key_candidate",
    "parse_scope_key",
    "resolve_country",
]
