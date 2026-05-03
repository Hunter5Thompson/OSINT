"""Live verification that constants.py Q/P-IDs still resolve to the labels we
recorded as comments. Marked `live` so it does NOT run on plain `pytest`
(pytest.ini has `addopts = -m "not live"` already). Run on demand:

    uv run pytest -m live tests/integration/test_constants_resolve_live.py
"""

from __future__ import annotations

import httpx
import pytest

from infra_atlas.constants import (
    PID_COORDINATE_LOCATION,
    PID_COUNTRY,
    PID_COUNTRY_ISO_ALPHA2,
    PID_IMAGE,
    PID_INSTANCE_OF,
    PID_LOCATED_IN,
    PID_NOMINAL_POWER,
    PID_OPERATOR,
    PID_OWNED_BY,
    PID_PRODUCTION_RATE,
    PID_SUBCLASS_OF,
    QID_DATA_CENTER,
    QID_LNG_TERMINAL,
    QID_OIL_REFINERY,
)

WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{id}.json"
USER_AGENT = "ODIN-infra-atlas-integration-test/0.1 (ai.zero.shot@gmail.com)"

EXPECTED = [
    (QID_OIL_REFINERY, "oil refinery"),
    (QID_LNG_TERMINAL, "liquefied natural gas terminal"),
    (QID_DATA_CENTER, "data center"),
    (PID_INSTANCE_OF, "instance of"),
    (PID_SUBCLASS_OF, "subclass of"),
    (PID_COORDINATE_LOCATION, "coordinate location"),
    (PID_OPERATOR, "operator"),
    (PID_OWNED_BY, "owned by"),
    (PID_COUNTRY, "country"),
    (PID_COUNTRY_ISO_ALPHA2, "ISO 3166-1 alpha-2 code"),
    (PID_LOCATED_IN, "located in the administrative territorial entity"),
    (PID_IMAGE, "image"),
    (PID_NOMINAL_POWER, "nominal power output"),
    (PID_PRODUCTION_RATE, "production rate"),
]


@pytest.mark.live
@pytest.mark.parametrize("entity_id,expected_label", EXPECTED)
def test_constant_label_matches_live_wikidata(entity_id: str, expected_label: str) -> None:
    resp = httpx.get(
        WIKIDATA_ENTITY_URL.format(id=entity_id),
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
    )
    resp.raise_for_status()
    label = resp.json()["entities"][entity_id]["labels"]["en"]["value"]
    assert label == expected_label, (
        f"Wikidata label drifted for {entity_id}: "
        f"expected {expected_label!r}, got {label!r}. "
        "Update constants.py comment OR pick a different ID."
    )
