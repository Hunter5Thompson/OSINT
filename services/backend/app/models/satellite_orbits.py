"""Versioned, additive orbit API and cache contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.orbit_elements import OMMElements, normalize_omm, parse_tle_pair


class OrbitContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TLEOrbit(OrbitContract):
    format: Literal["tle"]
    line1: str
    line2: str

    @model_validator(mode="after")
    def valid_pair(self) -> Self:
        parse_tle_pair(self.line1, self.line2)
        return self


class OMMOrbit(OrbitContract):
    format: Literal["omm"]
    elements: OMMElements

    @field_validator("elements", mode="before")
    @classmethod
    def validate_elements(cls, value: object) -> OMMElements:
        return normalize_omm(value)


class OrbitSatellite(OrbitContract):
    norad_id: int = Field(strict=True, ge=1, le=999999999)
    name: str = Field(min_length=1)
    orbit: Annotated[TLEOrbit | OMMOrbit, Field(discriminator="format")]
    category: str
    inclination_deg: float = Field(ge=0, le=180)
    period_min: float = Field(gt=0)
    operator_country: str | None
    satellite_type: str

    @model_validator(mode="after")
    def consistent_catalog_id(self) -> Self:
        if isinstance(self.orbit, OMMOrbit):
            if self.norad_id != self.orbit.elements["NORAD_CAT_ID"]:
                raise ValueError("metadata/OMM NORAD identifiers disagree")
        elif self.norad_id != parse_tle_pair(self.orbit.line1, self.orbit.line2).norad_id:
            raise ValueError("metadata/TLE NORAD identifiers disagree")
        return self


class OrbitRejection(OrbitContract):
    index: int = Field(strict=True, ge=0)
    code: Literal["invalid", "unsupported"]
    reason: str


class OrbitGroupCoverage(OrbitContract):
    group: str
    status: Literal["ok", "partial", "failed"]
    accepted_records: int = Field(strict=True, ge=0)
    rejected_invalid: int = Field(strict=True, ge=0)
    rejected_unsupported: int = Field(strict=True, ge=0)
    rejections: list[OrbitRejection]
    failure_code: Literal["transport", "invalid_payload", "no_usable_records"] | None = None

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        invalid = sum(item.code == "invalid" for item in self.rejections)
        unsupported = sum(item.code == "unsupported" for item in self.rejections)
        if (invalid, unsupported) != (self.rejected_invalid, self.rejected_unsupported):
            raise ValueError("rejection counts disagree with diagnostics")
        expected = "failed" if self.failure_code else "partial" if self.rejections else "ok"
        if self.status != expected:
            raise ValueError("group status disagrees with diagnostics")
        if self.status == "failed" and self.accepted_records:
            raise ValueError("failed group cannot claim accepted records")
        return self


class OrbitCoverage(OrbitContract):
    completeness: Literal["complete", "partial"]
    groups: list[OrbitGroupCoverage] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_completeness(self) -> Self:
        complete = all(group.status == "ok" for group in self.groups)
        if (self.completeness == "complete") != complete:
            raise ValueError("completeness disagrees with group results")
        if all(group.status == "failed" for group in self.groups):
            raise ValueError("no usable group is not a successful snapshot")
        names = [group.group for group in self.groups]
        if len(set(names)) != len(names):
            raise ValueError("duplicate group diagnostics")
        return self


class OrbitSnapshot(OrbitContract):
    schema_version: Literal[1]
    fetched_at: datetime
    satellites: list[OrbitSatellite]
    coverage: OrbitCoverage

    @field_validator("schema_version", mode="before")
    @classmethod
    def literal_version(cls, value: object) -> Literal[1]:
        if type(value) is not int or value != 1:
            raise ValueError("expected integer schema version 1")
        return 1

    @field_validator("fetched_at", mode="before")
    @classmethod
    def explicit_fetch_time(cls, value: object) -> str | datetime:
        if not isinstance(value, (str, datetime)):
            raise ValueError("fetch time must be an explicit timestamp")
        return value

    @field_validator("fetched_at")
    @classmethod
    def utc_fetch_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("fetch time requires a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def unique_satellites(self) -> Self:
        ids = [row.norad_id for row in self.satellites]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate snapshot NORAD identifiers")
        accepted = sum(group.accepted_records for group in self.coverage.groups)
        if len(ids) > accepted or bool(ids) != bool(accepted):
            raise ValueError("snapshot satellites disagree with accepted source records")
        return self
