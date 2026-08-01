"""Canonical scope-key parsing and normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from spatial_catalog.models import ScopeKind

_LEXICAL_SCOPE_KEY: Final = re.compile(r"^[A-Za-z0-9:._-]+$")
_NORMALIZABLE_ISO3: Final = re.compile(r"^country:([A-Za-z]{3})$")
_NORMALIZABLE_ISO3166_2: Final = re.compile(
    r"^admin1:iso3166-2:([A-Za-z]{2})-([A-Za-z0-9]{1,3})$"
)
_NON_OFFICIAL_LEGACY_ISO3: Final = frozenset({"XKX"})

_SCOPE_KEY_PATTERNS: Final[tuple[tuple[ScopeKind, str | None, re.Pattern[str]], ...]] = (
    (ScopeKind.WORLD, None, re.compile(r"^world$")),
    (ScopeKind.COUNTRY, "iso3166-1", re.compile(r"^country:([A-Z]{3})$")),
    (ScopeKind.COUNTRY, "m49", re.compile(r"^country:m49:([0-9]{3})$")),
    (
        ScopeKind.COUNTRY,
        "odin",
        re.compile(r"^country:odin:([a-z0-9][a-z0-9._-]{0,79})$"),
    ),
    (
        ScopeKind.ADMIN1,
        "iso3166-2",
        re.compile(r"^admin1:iso3166-2:([A-Z]{2}-[A-Z0-9]{1,3})$"),
    ),
    (
        ScopeKind.ADMIN1,
        "gbopen",
        re.compile(r"^admin1:gbopen:([A-Za-z0-9._-]{1,80})$"),
    ),
    (
        ScopeKind.ADMIN2,
        None,
        re.compile(r"^admin2:([A-Za-z0-9._-]{1,24}):([A-Za-z0-9._-]{1,80})$"),
    ),
)


class InvalidScopeKeyError(ValueError):
    """A candidate failed lexical or semantic scope-key validation."""


@dataclass(frozen=True, slots=True)
class ParsedScopeKey:
    canonical: str
    kind: ScopeKind
    namespace: str | None
    canonical_code: str | None


def _invalid(candidate: object) -> InvalidScopeKeyError:
    return InvalidScopeKeyError(f"INVALID_SCOPE_KEY: {candidate!r}")


def _validate_lexical_candidate(candidate: str) -> None:
    try:
        byte_length = len(candidate.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise _invalid(candidate) from exc
    if not 1 <= byte_length <= 128 or _LEXICAL_SCOPE_KEY.fullmatch(candidate) is None:
        raise _invalid(candidate)


def normalize_scope_key_candidate(candidate: str) -> str:
    """Uppercase only ISO-owned code segments; never trim or decode input."""

    if not isinstance(candidate, str):
        raise _invalid(candidate)
    _validate_lexical_candidate(candidate)

    iso3 = _NORMALIZABLE_ISO3.fullmatch(candidate)
    if iso3 is not None:
        return f"country:{iso3.group(1).upper()}"
    iso3166_2 = _NORMALIZABLE_ISO3166_2.fullmatch(candidate)
    if iso3166_2 is not None:
        return f"admin1:iso3166-2:{iso3166_2.group(1).upper()}-{iso3166_2.group(2).upper()}"
    return candidate


def parse_scope_key(candidate: str) -> ParsedScopeKey:
    """Parse a candidate against the closed V1 grammar.

    Registry membership remains a catalog concern.  XKX is the one explicitly
    forbidden pseudo-ISO spelling: the reviewed registry resolves it only as a
    legacy alias for ``country:odin:kosovo``.
    """

    canonical = normalize_scope_key_candidate(candidate)
    for kind, fixed_namespace, pattern in _SCOPE_KEY_PATTERNS:
        match = pattern.fullmatch(canonical)
        if match is None:
            continue
        if kind is ScopeKind.WORLD:
            return ParsedScopeKey(canonical, kind, None, None)
        if kind is ScopeKind.ADMIN2:
            return ParsedScopeKey(canonical, kind, match.group(1), match.group(2))
        code = match.group(1)
        if fixed_namespace == "iso3166-1" and code in _NON_OFFICIAL_LEGACY_ISO3:
            raise _invalid(candidate)
        return ParsedScopeKey(canonical, kind, fixed_namespace, code)
    raise _invalid(candidate)
