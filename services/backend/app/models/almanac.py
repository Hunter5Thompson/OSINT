"""Models for the WorldReport country Almanac."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AlmanacCapital(BaseModel):
    name: str
    lat: float
    lon: float


class AlmanacFact(BaseModel):
    label: str
    value: str


class AlmanacFacts(BaseModel):
    profile: list[AlmanacFact] = Field(default_factory=list)
    people: list[AlmanacFact] = Field(default_factory=list)
    government: list[AlmanacFact] = Field(default_factory=list)
    economy: list[AlmanacFact] = Field(default_factory=list)
    security: list[AlmanacFact] = Field(default_factory=list)


class CountryAlmanac(BaseModel):
    id: str
    iso3: str | None = None
    m49: str
    name: str
    region: str = ""
    subregion: str = ""
    capital: AlmanacCapital | None = None
    facts: AlmanacFacts = Field(default_factory=AlmanacFacts)
    updated_at: str
    source_note: str


class AlmanacSignalItem(BaseModel):
    event_id: str
    ts: str
    type: str
    title: str
    severity: str
    source: str
    url: str = ""


class AlmanacSignalResponse(BaseModel):
    country_id: str
    items: list[AlmanacSignalItem]
