"""Canonical GP-JSON decoder, vendored byte-for-byte into each Python service.

Only the CelesTrak EARTH/TEME/UTC/SGP4 contract is supported. Angles are degrees,
mean motion is revolutions/day and epoch precision is preserved to microseconds.
This decoder validates orbital inputs; it does not verify physical locations.
"""

from __future__ import annotations

import math
import re
from calendar import isleap
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, TypedDict


class OrbitElementError(ValueError):
    """A malformed or explicitly unsupported orbital input."""

    def __init__(self, code: Literal["invalid", "unsupported"], reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class OMMElements(TypedDict):
    OBJECT_NAME: str
    OBJECT_ID: str
    NORAD_CAT_ID: int
    EPOCH: str
    MEAN_MOTION: float
    ECCENTRICITY: float
    INCLINATION: float
    RA_OF_ASC_NODE: float
    ARG_OF_PERICENTER: float
    MEAN_ANOMALY: float
    BSTAR: float
    MEAN_MOTION_DOT: float
    MEAN_MOTION_DDOT: float
    EPHEMERIS_TYPE: int
    CLASSIFICATION_TYPE: str
    ELEMENT_SET_NO: int
    REV_AT_EPOCH: int
    CENTER_NAME: str
    REF_FRAME: str
    TIME_SYSTEM: str
    MEAN_ELEMENT_THEORY: str


@dataclass(frozen=True)
class TLEElements:
    norad_id: int
    inclination_deg: float
    mean_motion: float
    epoch: str


def parse_tle_pair(line1: str, line2: str) -> TLEElements:
    """Validate fixed columns, checksums, paired IDs and SGP4 ranges.

    Alpha-5 is diagnosed separately and is intentionally not guessed/converted.
    TLE strings remain unchanged; this function only returns decoded metadata.
    """
    for number, line in ((1, line1), (2, line2)):
        if len(line) != 69 or not line.startswith(f"{number} "):
            raise OrbitElementError("invalid", f"TLE line {number}: expected 69 fixed columns")
        if re.fullmatch(r"[A-HJ-NP-Z][0-9]{4}", line[2:7]):
            raise OrbitElementError("unsupported", "TLE Alpha-5 catalog ID is not qualified")
        if not re.fullmatch(r" *[0-9]+", line[2:7]):
            raise OrbitElementError("invalid", "TLE catalog ID: expected decimal fixed columns")
        checksum = (
            sum(
                int(char) if char.isascii() and char.isdigit() else char == "-"
                for char in line[:68]
            )
            % 10
        )
        if not line[68].isascii() or not line[68].isdigit() or checksum != int(line[68]):
            raise OrbitElementError("invalid", f"TLE line {number}: checksum mismatch")
    norad = int(line1[2:7])
    if norad <= 0 or norad != int(line2[2:7]):
        raise OrbitElementError("invalid", "TLE line catalog IDs must agree and be positive")
    for line, columns in ((line1, (8, 17, 32, 43, 52, 61, 63)), (line2, (7, 16, 25, 33, 42, 51))):
        if any(line[column] != " " for column in columns):
            raise OrbitElementError("invalid", "TLE fixed-column separators are invalid")
    if line1[7] not in "UCS" or not re.fullmatch(r"[0-9]{5}\.[0-9]{8}", line1[18:32]):
        raise OrbitElementError("invalid", "TLE classification/epoch grammar is invalid")
    if not re.fullmatch(r"[ +\-]\.[0-9]{8}", line1[33:43]):
        raise OrbitElementError("invalid", "TLE mean motion derivative grammar is invalid")
    if any(
        not re.fullmatch(r"[ +\-][0-9]{5}[+\-][0-9]", value)
        for value in (line1[44:52], line1[53:61])
    ):
        raise OrbitElementError("invalid", "TLE exponent grammar is invalid")
    if not line1[62].isascii() or not line1[62].isdigit():
        raise OrbitElementError("invalid", "TLE ephemeris type grammar is invalid")
    if line1[62] != "0":
        raise OrbitElementError("unsupported", "TLE ephemeris type: only SGP4 (0) is supported")
    if not line1[64:68].strip().isascii() or not line1[64:68].strip().isdigit():
        raise OrbitElementError("invalid", "TLE element set number is invalid")
    if not line2[63:68].strip().isascii() or not line2[63:68].strip().isdigit():
        raise OrbitElementError("invalid", "TLE revolution number is invalid")
    epoch_year = int(line1[18:20])
    epoch_year += 1900 if epoch_year >= 57 else 2000
    day = float(line1[20:32])
    if not 1 <= day < 366 + isleap(epoch_year):
        raise OrbitElementError("invalid", "TLE epoch day is outside its calendar year")
    epoch = datetime(epoch_year, 1, 1, tzinfo=UTC) + timedelta(days=day - 1)
    if any(
        not re.fullmatch(r" *[0-9]{1,3}\.[0-9]{4}", field)
        for field in (line2[8:16], line2[17:25], line2[34:42], line2[43:51])
    ):
        raise OrbitElementError("invalid", "TLE angle fixed-column grammar is invalid")
    if not re.fullmatch(r" *[0-9]{1,2}\.[0-9]{8}", line2[52:63]):
        raise OrbitElementError("invalid", "TLE mean motion fixed-column grammar is invalid")
    try:
        inclination = float(line2[8:16])
        ascending = float(line2[17:25])
        pericenter = float(line2[34:42])
        anomaly = float(line2[43:51])
        mean_motion = float(line2[52:63])
    except ValueError as exc:
        raise OrbitElementError("invalid", "TLE numeric fixed columns are invalid") from exc
    if not re.fullmatch(r"[0-9]{7}", line2[26:33]):
        raise OrbitElementError("invalid", "TLE eccentricity grammar is invalid")
    if not all(
        math.isfinite(value) for value in (inclination, ascending, pericenter, anomaly, mean_motion)
    ):
        raise OrbitElementError("invalid", "TLE numbers must be finite")
    if not 0 <= inclination <= 180 or any(
        not 0 <= angle < 360 for angle in (ascending, pericenter, anomaly)
    ):
        raise OrbitElementError("invalid", "TLE angle outside orbital range")
    if mean_motion <= 0 or not math.isfinite(1440.0 / mean_motion):
        raise OrbitElementError("invalid", "TLE mean motion must be positive")
    return TLEElements(
        norad,
        inclination,
        mean_motion,
        epoch.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


def _number(fields: dict[object, object], key: str) -> float:
    value = fields.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise OrbitElementError("invalid", f"{key}: expected a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise OrbitElementError("invalid", f"{key}: expected a finite number") from exc
    if not math.isfinite(number):
        raise OrbitElementError("invalid", f"{key}: expected a finite number")
    return number


def _integer(fields: dict[object, object], key: str, low: int, high: int) -> int:
    value = fields.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise OrbitElementError("invalid", f"{key}: expected an integer")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
        raise OrbitElementError("invalid", f"{key}: expected an unsigned decimal integer")
    if isinstance(value, str):
        value = value.lstrip("0") or "0"
        if len(value) > len(str(high)):
            raise OrbitElementError("invalid", f"{key}: outside supported integer range")
    number = int(value)
    if not low <= number <= high:
        raise OrbitElementError("invalid", f"{key}: outside supported range {low}..{high}")
    return number


def _range(
    fields: dict[object, object],
    key: str,
    low: float,
    high: float,
    *,
    upper_inclusive: bool = False,
) -> float:
    number = _number(fields, key)
    if number < low or (number > high if upper_inclusive else number >= high):
        raise OrbitElementError("invalid", f"{key}: outside orbital range")
    return number


def _epoch(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]{1,6})?(?:Z|[+\-][0-9]{2}:[0-9]{2})?",
        value,
    ):
        raise OrbitElementError("invalid", "EPOCH: expected an ISO date and time")
    try:
        epoch = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # CelesTrak omits the redundant TIME_SYSTEM=UTC and the UTC suffix.
        if epoch.tzinfo is None:
            epoch = epoch.replace(tzinfo=UTC)
        return epoch.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError) as exc:
        raise OrbitElementError("invalid", "EPOCH: invalid UTC date and time") from exc


def normalize_omm(value: object) -> OMMElements:
    """Normalize one GP-JSON record; reject unsupported explicit metadata."""
    if not isinstance(value, dict):
        raise OrbitElementError("invalid", "record: expected a JSON object")
    fields: dict[object, object] = value
    for key, expected in (
        ("CENTER_NAME", "EARTH"),
        ("REF_FRAME", "TEME"),
        ("TIME_SYSTEM", "UTC"),
        ("MEAN_ELEMENT_THEORY", "SGP4"),
    ):
        if fields.get(key, expected) != expected:
            raise OrbitElementError("unsupported", f"{key}: only {expected} is supported")
    ephemeris = _integer(fields, "EPHEMERIS_TYPE", 0, 9)
    if ephemeris != 0:
        raise OrbitElementError("unsupported", "EPHEMERIS_TYPE: only GP SGP4 (0) is supported")
    norad = _integer(fields, "NORAD_CAT_ID", 1, 999999999)
    classification = fields.get("CLASSIFICATION_TYPE")
    if classification not in ("U", "C", "S"):
        raise OrbitElementError("invalid", "CLASSIFICATION_TYPE: expected U, C or S")
    name = fields.get("OBJECT_NAME", f"NORAD {norad}")
    object_id = fields.get("OBJECT_ID", "")
    if not isinstance(name, str) or not name.strip() or not isinstance(object_id, str):
        raise OrbitElementError("invalid", "OBJECT_NAME/OBJECT_ID: expected strings")
    mean_motion = _number(fields, "MEAN_MOTION")
    if mean_motion <= 0 or not math.isfinite(1440.0 / mean_motion):
        raise OrbitElementError("invalid", "MEAN_MOTION: expected positive revolutions/day")
    return {
        "OBJECT_NAME": name.strip(),
        "OBJECT_ID": object_id,
        "NORAD_CAT_ID": norad,
        "EPOCH": _epoch(fields.get("EPOCH")),
        "MEAN_MOTION": mean_motion,
        "ECCENTRICITY": _range(fields, "ECCENTRICITY", 0, 1),
        "INCLINATION": _range(fields, "INCLINATION", 0, 180, upper_inclusive=True),
        "RA_OF_ASC_NODE": _range(fields, "RA_OF_ASC_NODE", 0, 360),
        "ARG_OF_PERICENTER": _range(fields, "ARG_OF_PERICENTER", 0, 360),
        "MEAN_ANOMALY": _range(fields, "MEAN_ANOMALY", 0, 360),
        "BSTAR": _number(fields, "BSTAR"),
        "MEAN_MOTION_DOT": _number(fields, "MEAN_MOTION_DOT"),
        "MEAN_MOTION_DDOT": _number(fields, "MEAN_MOTION_DDOT"),
        "EPHEMERIS_TYPE": ephemeris,
        "CLASSIFICATION_TYPE": str(classification),
        "ELEMENT_SET_NO": _integer(fields, "ELEMENT_SET_NO", 0, 999999999),
        "REV_AT_EPOCH": _integer(fields, "REV_AT_EPOCH", 0, 999999999),
        "CENTER_NAME": "EARTH",
        "REF_FRAME": "TEME",
        "TIME_SYSTEM": "UTC",
        "MEAN_ELEMENT_THEORY": "SGP4",
    }
