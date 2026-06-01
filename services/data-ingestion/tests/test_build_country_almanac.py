from infra_atlas.almanac_clean import (
    clean_html,
    format_composite,
    is_plausible_capital,
    latest_year_value,
)
from infra_atlas.almanac_constants import FACTBOOK_REVISION


def test_clean_html_strips_tags_and_unescapes():
    assert clean_html("<b>note:</b> a &amp; b<br>c") == "note: a & b c"
    assert clean_html("<strong>x</strong> <em>y</em>") == "x y"
    assert clean_html("2.3% (2024 est.)") == "2.3% (2024 est.)"  # year suffix kept

def test_latest_year_value_picks_newest():
    field = {
        "Inflation rate (consumer prices) 2023": {"text": "5.9% (2023 est.)"},
        "Inflation rate (consumer prices) 2024": {"text": "2.3% (2024 est.)"},
        "note": "<b>note:</b> annual",
    }
    assert latest_year_value(field) == "2.3% (2024 est.)"

def test_latest_year_value_handles_flat_text():
    assert latest_year_value({"text": "$4.6 trillion (2024 est.)"}) == "$4.6 trillion (2024 est.)"

def test_format_composite():
    field = {
        "agriculture": {"text": "0.8% (2024 est.)"},
        "industry": {"text": "25.8% (2024 est.)"},
        "services": {"text": "63.9% (2024 est.)"},
        "note": "x",
    }
    assert format_composite(field, ["agriculture", "industry", "services"]) == (
        "agriculture 0.8% (2024 est.) · industry 25.8% (2024 est.) · services 63.9% (2024 est.)"
    )

def test_is_plausible_capital():
    assert is_plausible_capital(52.52, 13.40, 51.0, 9.0) is True
    assert is_plausible_capital(-13.28, 27.14, 24.2, -12.9) is False  # swapped El Aaiún, far
    assert is_plausible_capital(95.0, 0.0, 0.0, 0.0) is False          # lat out of range


def test_render_is_deterministic_and_covers(tmp_path):
    import json

    from infra_atlas import build_country_almanac as b

    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    b.render(out_path=out1, refreshed_at="2026-06-01")
    b.render(out_path=out2, refreshed_at="2026-06-01")
    assert out1.read_text() == out2.read_text()           # byte-identical
    seed = json.loads(out1.read_text())
    assert len(seed["countries"]) == 177
    ids = [c["id"] for c in seed["countries"]]
    assert len(ids) == len(set(ids))                       # no id collision
    assert seed["_meta"]["factbook_revision"] == FACTBOOK_REVISION
