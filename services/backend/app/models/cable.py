"""Submarine cable and landing point data models."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubmarineCable(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: str
    name: str
    color: str = "#00bcd4"
    is_planned: bool = False
    owners: str | None = None
    capacity_tbps: float | None = None
    length_km: float | None = None
    rfs: str | None = None
    url: str | None = None
    landing_point_ids: list[str] = Field(default_factory=list)
    coordinates: list[list[list[float]]]  # MultiLineString

    @field_validator("capacity_tbps", "length_km")
    @classmethod
    def validate_nonnegative_finite(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("cable measurements must be finite and nonnegative")
        return value

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, lines: list[list[list[float]]]) -> list[list[list[float]]]:
        if not lines:
            raise ValueError("cable needs at least one line")
        for line in lines:
            if len(line) < 2:
                raise ValueError("cable line needs at least two points")
            for point in line:
                if len(point) < 2:
                    raise ValueError("cable point needs longitude and latitude")
                lon, lat = point[:2]
                if any(not math.isfinite(component) for component in point):
                    raise ValueError("cable coordinates must be finite")
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValueError("cable coordinates out of range")
        return lines


class LandingPoint(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: str
    name: str
    country: str | None = None
    latitude: float
    longitude: float

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, value: float) -> float:
        if not math.isfinite(value) or not -90 <= value <= 90:
            raise ValueError("latitude out of range")
        return value

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, value: float) -> float:
        if not math.isfinite(value) or not -180 <= value <= 180:
            raise ValueError("longitude out of range")
        return value


class CableDataset(BaseModel):
    cables: list[SubmarineCable]
    landing_points: list[LandingPoint]
    source: Literal["live", "fallback"]
