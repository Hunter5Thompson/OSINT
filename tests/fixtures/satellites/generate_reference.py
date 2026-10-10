"""Reproduce WGS72 reference vectors with the separately pinned C++ implementation.

Run in an isolated environment containing sgp4==2.27, passing the frozen G05
evidence directory and this fixture directory. Never fetch a live orbital feed.
"""

import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sgp4
from sgp4 import omm
from sgp4.api import WGS72, Satrec, accelerated, jday


def main() -> None:
    evidence, destination = map(Path, sys.argv[1:])
    assert sgp4.__version__ == "2.27" and accelerated
    metadata = json.loads((evidence / "python-sgp4-pypi.json").read_text())
    description = metadata["info"]["description"]
    line1 = re.search(r"^>>> s = '(1 25544[^']+)'$", description, re.MULTILINE)[1]
    line2 = re.search(r"^>>> t = '(2 25544[^']+)'$", description, re.MULTILINE)[1]
    for line in (line1, line2):
        assert len(line) == 69
        assert sum(int(c) if c.isdigit() else c == "-" for c in line[:68]) % 10 == int(line[68])
    feed = json.loads((evidence / "primary-gp-last-30-days.json").read_text())
    fields = next(row for row in feed if row["NORAD_CAT_ID"] == 100651)
    cases = [
        {
            "name": "ISS (ZARYA)",
            "norad_id": 25544,
            "orbit": {"format": "tle", "line1": line1, "line2": line2},
            "start": "2019-12-09T20:42:00Z",
        },
        {
            "name": fields["OBJECT_NAME"],
            "norad_id": fields["NORAD_CAT_ID"],
            "orbit": {"format": "omm", "elements": fields},
            "start": fields["EPOCH"][:23] + "Z",
        },
    ]
    for case in cases:
        orbit = case["orbit"]
        if orbit["format"] == "tle":
            record = Satrec.twoline2rv(orbit["line1"], orbit["line2"], WGS72)
        else:
            record = Satrec()
            omm.initialize(record, orbit["elements"], WGS72)
        case["vectors"] = []
        for hours in (0, -1, 1, 24, 168):
            moment = datetime.fromisoformat(case["start"].replace("Z", "+00:00")) + timedelta(
                hours=hours
            )
            jd, fraction = jday(
                moment.year,
                moment.month,
                moment.day,
                moment.hour,
                moment.minute,
                moment.second + moment.microsecond / 1e6,
            )
            error, position, velocity = record.sgp4(jd, fraction)
            assert error == 0
            case["vectors"].append(
                {
                    "utc": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "position_teme_km": position,
                    "velocity_teme_km_s": velocity,
                }
            )
    result = {
        "reference": {
            "package": "sgp4",
            "version": "2.27",
            "accelerated_cpp": True,
            "gravity": "WGS72",
            "frame": "TEME",
            "position_tolerance_km": 0.01,
            "velocity_tolerance_km_s": 0.00001,
        },
        "cases": cases,
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "reference-vectors.json").write_text(json.dumps(result, indent=2) + "\n")
    (destination / "celestrak-100651.json").write_text(json.dumps(fields, indent=2) + "\n")
    (destination / "iss-valid.tle").write_text("ISS (ZARYA)\n" + line1 + "\n" + line2 + "\n")
    source = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "reference_package": "sgp4==2.27",
        "accelerated_cpp": accelerated,
        "reference_source_url": "https://pypi.org/project/sgp4/2.27/",
        "reference_sdist_sha256": hashlib.sha256(
            (evidence / "sgp4-2.27.tar.gz").read_bytes()
        ).hexdigest(),
        "iss_input": (
            "Exact TLE pair from the published 2.27 package description; "
            "checksums verified, unchanged"
        ),
        "gp_input": next(
            row
            for row in json.loads((evidence / "primary-source-check.json").read_text())
            if row.get("artifact") == "primary-gp-last-30-days.json"
        ),
        "limits": (
            "Mathematical regression fixtures, not current ISS/physical location verification. "
            "GP epoch microseconds retained; evaluation instants use exact UTC milliseconds."
        ),
    }
    (destination / "sources.json").write_text(json.dumps(source, indent=2) + "\n")


if __name__ == "__main__":
    main()
