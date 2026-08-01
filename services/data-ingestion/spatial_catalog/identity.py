"""Canonical scope-key parsing and normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, StrictStr, StringConstraints, model_validator

from spatial_catalog.models import ScopeKey, ScopeKind, StrictFrozenModel

COUNTRY_CROSSWALK_PATH: Final = Path(__file__).resolve().parent / "data" / "country_crosswalk.json"

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


class CountryIdentityResolutionError(ValueError):
    """A source code has no explicit reviewed country disposition."""


@dataclass(frozen=True, slots=True)
class ParsedScopeKey:
    canonical: str
    kind: ScopeKind
    namespace: str | None
    canonical_code: str | None


type SourceIdentifier = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9._-]+$"),
]
type SourceCode = Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
type Iso3 = Annotated[
    StrictStr,
    StringConstraints(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$"),
]
type M49 = Annotated[
    StrictStr,
    StringConstraints(min_length=3, max_length=3, pattern=r"^[0-9]{3}$"),
]


class CrosswalkAlias(StrictFrozenModel):
    source_system: SourceIdentifier
    code_system: SourceIdentifier
    code: SourceCode


class CrosswalkProvenance(StrictFrozenModel):
    review_status: Literal["approved"]
    policy_revision: Literal["odin-reference-v1"]
    seed_release: SourceIdentifier
    review_note: Annotated[StrictStr, StringConstraints(min_length=1, max_length=300)]


class CountryCrosswalkRecord(StrictFrozenModel):
    record_id: SourceCode
    source_system: Literal["natural-earth-admin0"]
    source_code_system: Literal["natural-earth-topo-id"]
    source_code: SourceCode
    source_label: Annotated[StrictStr, StringConstraints(min_length=1, max_length=120)]
    disposition: Literal["scope", "non_scope_feature"]
    scope_key: ScopeKey | None
    canonical_iso3: Iso3 | None
    canonical_m49: M49 | None
    almanac_iso3: Iso3 | None
    almanac_gec: Annotated[
        StrictStr,
        StringConstraints(min_length=0, max_length=2, pattern=r"^(?:[a-z]{2})?$"),
    ]
    aliases: tuple[CrosswalkAlias, ...] = Field(default_factory=tuple)
    representation_id: SourceIdentifier
    dispute_status: Literal["none", "disputed", "multiple-representations"]
    non_scope_reason: Literal["disputed-territory-context"] | None
    provenance: CrosswalkProvenance

    @model_validator(mode="after")
    def validate_disposition(self) -> CountryCrosswalkRecord:
        if self.canonical_iso3 == "XKX":
            raise ValueError("XKX is not an official canonical ISO3")
        if self.disposition == "non_scope_feature":
            if self.scope_key is not None:
                raise ValueError("non-scope feature must not declare a scope key")
            if self.non_scope_reason is None:
                raise ValueError("non-scope feature requires a reviewed reason")
            return self

        if self.scope_key is None:
            raise ValueError("scope disposition requires a canonical scope key")
        if self.non_scope_reason is not None:
            raise ValueError("scope disposition must not declare a non-scope reason")
        parsed = parse_scope_key(self.scope_key)
        if parsed.namespace == "iso3166-1" and parsed.canonical_code != self.canonical_iso3:
            raise ValueError("ISO3 scope key must match canonical_iso3")
        if parsed.namespace == "m49" and parsed.canonical_code != self.canonical_m49:
            raise ValueError("M49 scope key must match canonical_m49")
        if parsed.namespace == "odin" and (
            not self.aliases or self.dispute_status == "none"
        ):
            raise ValueError("ODIN country scope requires aliases and a dispute record")
        return self


class CountryCrosswalk(StrictFrozenModel):
    schema_version: Literal[1]
    release: Literal["spatial-crosswalk-v1"]
    boundary_policy: Literal["odin-reference-v1"]
    records: tuple[CountryCrosswalkRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_identities(self) -> CountryCrosswalk:
        record_ids: set[str] = set()
        canonical_keys: set[str] = set()
        source_keys: set[tuple[str, str]] = set()
        for record in self.records:
            if record.record_id in record_ids:
                raise ValueError(f"duplicate crosswalk record ID: {record.record_id}")
            record_ids.add(record.record_id)
            if record.scope_key is not None:
                if record.scope_key in canonical_keys:
                    raise ValueError(f"duplicate canonical scope key: {record.scope_key}")
                canonical_keys.add(record.scope_key)

            identities = ((record.source_system, record.source_code),) + tuple(
                (alias.source_system, alias.code) for alias in record.aliases
            )
            for identity in identities:
                if identity in source_keys:
                    raise ValueError(
                        "duplicate source identity: " f"{identity[0]}:{identity[1]}"
                    )
                source_keys.add(identity)
        return self


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


def load_country_crosswalk(path: Path = COUNTRY_CROSSWALK_PATH) -> CountryCrosswalk:
    """Load the single reviewed registry; no frontend or display-name fallback."""

    return CountryCrosswalk.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_country(
    registry: CountryCrosswalk,
    *,
    source_system: str,
    source_code: str,
) -> CountryCrosswalkRecord:
    """Purely resolve an explicit source-system/code pair through the registry."""

    for record in registry.records:
        if (record.source_system, record.source_code) == (source_system, source_code):
            return record
        if any(
            (alias.source_system, alias.code) == (source_system, source_code)
            for alias in record.aliases
        ):
            return record
    raise CountryIdentityResolutionError(
        f"UNRESOLVED_COUNTRY_IDENTITY: {source_system}:{source_code}"
    )


def validate_natural_earth_coverage(
    registry: CountryCrosswalk,
    features: tuple[tuple[str, str], ...] | list[tuple[str, str]],
) -> None:
    """Fail if any Admin-0 feature lacks a reviewed scope/non-scope disposition."""

    for source_code, label in features:
        try:
            resolve_country(
                registry,
                source_system="natural-earth-admin0",
                source_code=source_code,
            )
        except CountryIdentityResolutionError as exc:
            raise CountryIdentityResolutionError(
                f"UNRESOLVED_COUNTRY_IDENTITY: {source_code} ({label})"
            ) from exc
