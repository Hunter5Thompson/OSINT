import json
from pathlib import Path

from app.models.signals import SignalEnvelope, SignalPayload
from app.services.country_almanac import CountryAlmanacStore


def _write_data(tmp_path: Path) -> Path:
    data = {
        "countries": [
            {
                "id": "GRC",
                "iso3": "GRC",
                "m49": "300",
                "name": "Greece",
                "region": "Europe",
                "subregion": "Southern Europe",
                "capital": {"name": "Athens", "lat": 37.98, "lon": 23.73},
                "facts": {
                    "profile": [{"label": "Area", "value": "131,957 sq km"}],
                    "people": [{"label": "Population", "value": "10.4M"}],
                    "government": [],
                    "economy": [],
                    "security": [],
                },
                "updated_at": "2026-05-19",
                "source_note": "test",
            },
            {
                "id": "732",
                "iso3": None,
                "m49": "732",
                "name": "W. Sahara",
                "region": "Africa",
                "subregion": "Northern Africa",
                "capital": None,
                "facts": {
                    "profile": [],
                    "people": [],
                    "government": [],
                    "economy": [],
                    "security": [],
                },
                "updated_at": "2026-05-19",
                "source_note": "test",
            },
        ]
    }
    p = tmp_path / "country_almanac.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _signal(**payload: object) -> SignalEnvelope:
    return SignalEnvelope(
        event_id="0001768651200000-000001",
        ts="2026-05-19T10:20:00.000Z",
        type="signal.rss",
        payload=SignalPayload(redis_id="1-0", **payload),
    )


def test_lookup_resolves_iso3_case_insensitively(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    country = store.get_country("grc")
    assert country is not None
    assert country.name == "Greece"
    assert country.capital is not None
    assert country.capital.name == "Athens"


def test_lookup_resolves_m49_fallback(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    country = store.get_country("732")
    assert country is not None
    assert country.name == "W. Sahara"
    assert country.iso3 is None


def test_lookup_returns_none_for_unknown(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    assert store.get_country("missing") is None


def test_signal_matching_prefers_explicit_iso3(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    matches = store.match_signals("GRC", [_signal(title="irrelevant", country_iso3="grc")])
    assert [item.event_id for item in matches] == ["0001768651200000-000001"]
    assert matches[0].title == "irrelevant"


def test_signal_matching_allows_exact_country_name_field(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    matches = store.match_signals("GRC", [_signal(title="Athens update", country_name="Greece")])
    assert len(matches) == 1


def test_signal_matching_rejects_title_substring(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    matches = store.match_signals("GRC", [_signal(title="Greece mentioned in title")])
    assert matches == []
