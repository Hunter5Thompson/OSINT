"""Shared fixture matrix at each independently packaged service boundary."""

import json
from pathlib import Path

import pytest

from app.orbit_elements import OrbitElementError, normalize_omm, parse_tle_pair

FIXTURES = Path(__file__).resolve().parents[4] / "tests/fixtures/satellites"
CASES = json.loads((FIXTURES / "decoder-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_orbit_decoder_matrix(case: dict[str, object]) -> None:
    def decode() -> int:
        if case["format"] == "omm":
            return normalize_omm(case["elements"])["NORAD_CAT_ID"]
        return parse_tle_pair(str(case["line1"]), str(case["line2"])).norad_id

    if "error" in case:
        with pytest.raises(OrbitElementError) as caught:
            decode()
        assert caught.value.code == case["error"]
    else:
        assert decode() == case["norad_id"]


def test_valid_iss_uses_fixed_column_mean_motion() -> None:
    _, line1, line2 = (FIXTURES / "iss-valid.tle").read_text().splitlines()
    result = parse_tle_pair(line1, line2)
    assert result.inclination_deg == 51.6439
    assert 1440 / result.mean_motion == pytest.approx(92.8970243678141)
    assert result.epoch.startswith("2019-12-09T")
