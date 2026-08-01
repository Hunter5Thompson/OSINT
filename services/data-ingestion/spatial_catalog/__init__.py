"""Deterministic offline spatial-catalog contracts."""

from spatial_catalog.identity import (
    InvalidScopeKeyError,
    ParsedScopeKey,
    normalize_scope_key_candidate,
    parse_scope_key,
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
    "DerivationRevision",
    "InvalidScopeKeyError",
    "ParsedScopeKey",
    "ScopeKey",
    "ScopeKind",
    "normalize_scope_key_candidate",
    "parse_scope_key",
]
