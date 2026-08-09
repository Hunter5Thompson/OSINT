"""Pure spatial contracts for Qdrant projection and retrieval.

The relation-specific payload field supplies the relation.  Each value stored in
that field atomically pairs one canonical non-global scope key with the derivation
revision that belongs to that scope.
"""

from __future__ import annotations

import re
from typing import Final

SCOPE_REVISION_TOKEN_PREFIX: Final = "sr1"
SCOPE_REVISION_TOKEN_SEPARATOR: Final = "|"

_SCOPE_KEY = re.compile(
    r"^(?:"
    r"country:[A-Z]{3}|"
    r"country:m49:[0-9]{3}|"
    r"country:odin:[a-z0-9][a-z0-9._-]{0,79}|"
    r"admin1:iso3166-2:[A-Z]{2}-[A-Z0-9]{1,3}|"
    r"admin1:gbopen:[A-Za-z0-9._-]{1,80}|"
    r"admin2:[A-Za-z0-9._-]{1,24}:[A-Za-z0-9._-]{1,80}"
    r")$"
)
_DERIVATION_REVISION = re.compile(r"^spatial-derive-v[0-9]+-[a-f0-9]{12,64}$")


class SpatialContractError(ValueError):
    """A value cannot cross the spatial payload seam safely."""


def encode_scope_revision_token(scope_key: str, derivation_revision: str) -> str:
    """Return the injective V1 keyword for one scope/revision assignment.

    ``|`` is excluded by both input grammars.  Splitting a valid token into its
    three components therefore recovers exactly the original pair without a hash
    or collision domain.  ``world`` is intentionally not materialized.
    """

    if not isinstance(scope_key, str) or _SCOPE_KEY.fullmatch(scope_key) is None:
        raise SpatialContractError("invalid non-global scope key")
    if (
        not isinstance(derivation_revision, str)
        or _DERIVATION_REVISION.fullmatch(derivation_revision) is None
    ):
        raise SpatialContractError("invalid derivation revision")
    return (
        f"{SCOPE_REVISION_TOKEN_PREFIX}{SCOPE_REVISION_TOKEN_SEPARATOR}"
        f"{scope_key}{SCOPE_REVISION_TOKEN_SEPARATOR}{derivation_revision}"
    )


__all__ = [
    "SCOPE_REVISION_TOKEN_PREFIX",
    "SCOPE_REVISION_TOKEN_SEPARATOR",
    "SpatialContractError",
    "encode_scope_revision_token",
]
