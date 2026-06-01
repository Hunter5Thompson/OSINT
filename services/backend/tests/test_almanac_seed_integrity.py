"""Guardrails for the SHIPPED country almanac artifact (not synthetic fixtures).

These encode the two defects that left the Almanac empty in the running container:
  1. data/country_almanac.json was missing from the image (Dockerfile only COPYed app/),
  2. the seed shipped iso3=null for 166/177 countries while the frontend keys by iso3,
     so almost every country 404'd.
"""

import json
from pathlib import Path

from app.services.country_almanac import DEFAULT_ALMANAC_PATH, get_country_almanac_store

# Disputed / non-ISO entries that legitimately have no ISO 3166-1 alpha-3 code.
# They carry a non-numeric m49 ("undefined") and remain resolvable by `id`.
_NO_ISO3_ALLOWLIST = {"Kosovo", "N. Cyprus", "Somaliland"}


def test_shipped_seed_exists_and_loads() -> None:
    assert DEFAULT_ALMANAC_PATH.exists(), f"seed missing at {DEFAULT_ALMANAC_PATH}"
    data = json.loads(DEFAULT_ALMANAC_PATH.read_text(encoding="utf-8"))
    assert data.get("countries"), "seed has no countries"


def test_every_iso_country_has_iso3() -> None:
    """Any entry with a numeric m49 must carry an iso3 — the frontend keys by iso3."""
    data = json.loads(DEFAULT_ALMANAC_PATH.read_text(encoding="utf-8"))
    missing = [
        c["name"]
        for c in data["countries"]
        if not c.get("iso3")
        and str(c.get("m49", "")).isdigit()
        and c.get("name") not in _NO_ISO3_ALLOWLIST
    ]
    assert missing == [], f"numeric-m49 countries without iso3 (frontend will 404): {missing}"


def test_store_resolves_major_countries_by_iso3() -> None:
    store = get_country_almanac_store()
    for iso3 in ["USA", "DEU", "CHN", "FRA", "GBR", "BRA", "ZAF", "IND", "RUS", "JPN"]:
        assert store.get_country(iso3) is not None, f"{iso3} not resolvable by iso3"


def test_seed_is_enriched_not_stub() -> None:
    """Guard against regression to placeholder stubs: the vast majority of countries
    must carry real facts (Population) and a capital, not just 'Map entity'/'M49 code'."""
    data = json.loads(DEFAULT_ALMANAC_PATH.read_text(encoding="utf-8"))
    countries = data["countries"]

    def has_population(c: dict) -> bool:
        return any(
            f.get("label") == "Population"
            for section in c["facts"].values()
            for f in section
        )

    with_pop = [c for c in countries if has_population(c)]
    with_capital = [c for c in countries if c.get("capital")]
    # 174/177 are ISO-matchable (Kosovo / N. Cyprus / Somaliland are not in REST Countries).
    n = len(countries)
    assert len(with_pop) >= 170, f"only {len(with_pop)}/{n} countries carry Population"
    assert len(with_capital) >= 170, f"only {len(with_capital)}/{n} countries have a capital"


def test_backend_image_packages_data_dir() -> None:
    """The image must contain the seed — Dockerfile must COPY data/ (root cause 1)."""
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY data/" in dockerfile, "Dockerfile must COPY data/ so the seed ships in the image"
