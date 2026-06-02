"""Static country Almanac loader and deterministic signal matching."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models.almanac import AlmanacSignalItem, CountryAlmanac
from app.models.signals import SignalEnvelope

DEFAULT_ALMANAC_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "country_almanac.json"
)


class CountryAlmanacStore:
    def __init__(self, path: Path = DEFAULT_ALMANAC_PATH) -> None:
        self.path = path
        self._by_id: dict[str, CountryAlmanac] | None = None
        self.factbook_revision: str = ""
        self.refreshed_at: str = ""
        # Eager-load so `_meta` (factbook_revision / refreshed_at) is available
        # on the store immediately; the singleton loads this once.
        self._ensure_loaded()

    def get_country(self, country_id: str) -> CountryAlmanac | None:
        self._ensure_loaded()
        assert self._by_id is not None
        return self._by_id.get(_norm_id(country_id))

    def match_signals(
        self,
        country_id: str,
        envelopes: list[SignalEnvelope],
        limit: int = 5,
    ) -> list[AlmanacSignalItem]:
        country = self.get_country(country_id)
        if country is None:
            return []
        matches: list[AlmanacSignalItem] = []
        for envelope in envelopes:
            if _matches_country(country, envelope):
                matches.append(_signal_item(envelope))
            if len(matches) >= limit:
                break
        return matches

    def _ensure_loaded(self) -> None:
        if self._by_id is not None:
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        meta = raw.get("_meta") or {}
        self.factbook_revision = str(meta.get("factbook_revision", ""))
        self.refreshed_at = str(meta.get("refreshed_at", ""))
        by_id: dict[str, CountryAlmanac] = {}
        for item in raw.get("countries", []):
            country = CountryAlmanac.model_validate(item)
            by_id[_norm_id(country.id)] = country
            by_id[_norm_id(country.m49)] = country
            if country.iso3:
                by_id[_norm_id(country.iso3)] = country
        self._by_id = by_id


@lru_cache(maxsize=1)
def get_country_almanac_store() -> CountryAlmanacStore:
    return CountryAlmanacStore()


def _norm_id(value: str) -> str:
    return value.strip().upper()


def _norm_name(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def _payload_extra(envelope: SignalEnvelope) -> dict[str, Any]:
    return envelope.payload.model_extra or {}


def _payload_value(envelope: SignalEnvelope, key: str) -> object:
    if hasattr(envelope.payload, key):
        return getattr(envelope.payload, key)
    return _payload_extra(envelope).get(key)


def _matches_country(country: CountryAlmanac, envelope: SignalEnvelope) -> bool:
    iso_fields = ("iso3", "country_iso3", "country_code")
    if country.iso3:
        target_iso = _norm_id(country.iso3)
        for field in iso_fields:
            value = _payload_value(envelope, field)
            if isinstance(value, str) and _norm_id(value) == target_iso:
                return True

    for field in ("m49", "country_m49"):
        value = _payload_value(envelope, field)
        if isinstance(value, str | int) and str(value).strip() == country.m49:
            return True

    target_name = _norm_name(country.name)
    for field in ("country", "country_name", "location_country"):
        value = _payload_value(envelope, field)
        if isinstance(value, str) and _norm_name(value) == target_name:
            return True
    return False


def _signal_item(envelope: SignalEnvelope) -> AlmanacSignalItem:
    return AlmanacSignalItem(
        event_id=envelope.event_id,
        ts=envelope.ts,
        type=envelope.type,
        title=envelope.payload.title,
        severity=envelope.payload.severity,
        source=envelope.payload.source,
        url=envelope.payload.url,
    )
