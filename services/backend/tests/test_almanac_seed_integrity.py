"""Guardrails for the SHIPPED country almanac artifact (not synthetic fixtures).

These encode the two defects that left the Almanac empty in the running container:
  1. data/country_almanac.json was missing from the image (Dockerfile only COPYed app/),
  2. the seed shipped iso3=null for 166/177 countries while the frontend keys by iso3,
     so almost every country 404'd.

Seed is now Factbook-based with a _meta block and coverage classes.
"""

import json
import re
from pathlib import Path

from app.services.country_almanac import DEFAULT_ALMANAC_PATH

# Matches actual HTML markup tags (e.g. <a href=...>, <br/>) but NOT math/text
# uses of "<" such as "<1%" that appear legitimately in CIA Factbook values.
_HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")

REST_FALLBACK = {"ESH", "PSE"}        # no usable single Factbook profile
PARTIAL = {"ATA"}                     # Factbook has no economy
MAP_STUB_NAMES = {"N. Cyprus", "Somaliland"}


def _data():
    return json.loads(DEFAULT_ALMANAC_PATH.read_text(encoding="utf-8"))


def test_exactly_177_and_unique_ids():
    cs = _data()["countries"]
    assert len(cs) == 177
    ids = [c["id"] for c in cs]
    assert len(ids) == len(set(ids)), "duplicate seed id (map collision)"


def test_factbook_countries_have_economy_and_security():
    cs = _data()["countries"]
    def has(c, sec): return len(c["facts"][sec]) > 0
    offenders = []
    for c in cs:
        if c["iso3"] in REST_FALLBACK or c["iso3"] in PARTIAL or c["name"] in MAP_STUB_NAMES:
            continue
        if not (has(c, "economy") and has(c, "security")):
            offenders.append(c["name"])
    assert offenders == [], f"Factbook-profile countries missing economy/security: {offenders}"


def test_no_raw_html_in_values():
    # Guard against unstripped HTML markup in fact values.
    # Note: CIA Factbook legitimately uses "<1%" comparisons; we check for HTML tags only.
    bad = [c["name"] for c in _data()["countries"]
           for sec in c["facts"].values() for f in sec if _HTML_TAG_RE.search(f["value"])]
    assert bad == []


def test_capital_coverage_and_meta():
    cs = _data()["countries"]
    assert sum(1 for c in cs if c.get("capital")) >= 170
    assert _data()["_meta"]["factbook_revision"]


def test_backend_image_packages_data_dir() -> None:
    """The image must contain the seed — Dockerfile must COPY data/ (root cause 1)."""
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY data/" in dockerfile, "Dockerfile must COPY data/ so the seed ships in the image"
