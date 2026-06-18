"""Pydantic model for one SUV Hauptwaffensysteme table row."""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class WeaponSystemRow(BaseModel):
    muster: str                       # "Muster" column = the weapon-system name
    type_raw: str | None = None       # "Typ" column (e.g. "Kampfpanzer")
    count: int | None = None          # parsed from "Anzahl"
    count_raw: str | None = None       # original "Anzahl" string (provenance)
    service_end: int | None = None    # parsed year from "Nutzungsdauerende"
    note: str | None = None           # "Notiz"
    page_slug: str                    # which sub-page → operator
    suv_url: str                      # the sub-page URL (per-page; a valid join key)

    @field_validator("muster")
    @classmethod
    def _muster_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("weapon-system name (Muster) must be non-empty")
        return v

    @property
    def name(self) -> str:
        """Match/gate interface: the entity name is the Muster column."""
        return self.muster
