import polars as pl

from gdelt_raw.schemas import GDELTEventWrite
from gdelt_raw.transform import canonicalize_events


def test_canonical_events_carry_geo():
    raw = pl.DataFrame({
        "event_id": ["gdelt:event:1"], "event_code": ["193"],
        "event_root_code": [19], "quad_class": [4], "goldstein_scale": [-6.5],
        "avg_tone": [-4.0], "num_mentions": [3], "num_sources": [2],
        "num_articles": [3], "date_added": [20260613221500], "fraction_date": [2026.4],
        "actor1_code": ["RUS"], "actor1_name": ["RUSSIA"],
        "actor2_code": ["UKR"], "actor2_name": ["UKRAINE"],
        "source_url": ["https://x"], "codebook_type": ["conflict.armed"],
        "filter_reason": ["tactical"],
        "action_geo_lat": [48.0], "action_geo_long": [37.8],
        "action_geo_fullname": ["Donetsk, Ukraine"],
        "action_geo_country_code": ["UP"], "action_geo_feature_id": ["-1044367"],
    })
    out = canonicalize_events(raw)
    assert out["action_geo_lat"][0] == 48.0
    assert out["action_geo_fullname"][0] == "Donetsk, Ukraine"


def test_contract_accepts_optional_geo():
    ev = GDELTEventWrite(
        event_id="gdelt:event:1", cameo_code="193", cameo_root=19, quad_class=4,
        goldstein=-6.5, avg_tone=-4.0, num_mentions=3, num_sources=2, num_articles=3,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://x", codebook_type="conflict.armed", filter_reason="tactical",
        action_geo_lat=48.0, action_geo_long=37.8, action_geo_fullname="Donetsk, Ukraine",
        action_geo_country_code="UP", action_geo_feature_id="-1044367",
    )
    assert ev.action_geo_lat == 48.0
    ev2 = GDELTEventWrite(
        event_id="gdelt:event:2", cameo_code="010", cameo_root=1, quad_class=1,
        goldstein=0.0, avg_tone=0.0, num_mentions=1, num_sources=1, num_articles=1,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://y", codebook_type="other.unclassified", filter_reason="tactical",
    )
    assert ev2.action_geo_lat is None
