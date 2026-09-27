"""Unit tests for Telegram detector helpers."""
import pytest

from app.services.incident_promoter.detectors.telegram import (
    _domain_of,
    _jaccard_5gram,
    _normalize_title,
    _shingles,
)


def test_normalize_lowercases_strips_urls_and_punctuation():
    raw = "BREAKING: Strike on Kharkiv https://t.me/foo/123 — confirmed!!"
    assert _normalize_title(raw) == "breaking strike on kharkiv confirmed"


def test_shingles_of_short_text_returns_single_token_tuple():
    assert _shingles("a b") == {("a", "b")}


def test_shingles_5gram_for_long_text():
    s = _shingles("alpha bravo charlie delta echo foxtrot")
    # 2 windows of 5 tokens each
    assert ("alpha", "bravo", "charlie", "delta", "echo") in s
    assert ("bravo", "charlie", "delta", "echo", "foxtrot") in s


def test_jaccard_5gram_identical_is_one():
    a = _shingles("strike on kharkiv overnight powerful")
    b = _shingles("strike on kharkiv overnight powerful")
    assert _jaccard_5gram(a, b) == 1.0


def test_jaccard_5gram_disjoint_is_zero():
    a = _shingles("alpha bravo charlie delta echo")
    b = _shingles("zulu yankee xray whisky victor")
    assert _jaccard_5gram(a, b) == 0.0


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://t.me/OSINTdefender/12345", "t.me"),
        ("http://example.com/path", "example.com"),
        ("", ""),
        (None, ""),
    ],
)
def test_domain_of(url, expected):
    assert _domain_of(url) == expected


def _tg_envelope(signal_envelope_factory, title: str, url: str = "https://t.me/x/1"):
    return signal_envelope_factory(source="telegram", title=title, url=url)


def test_telegram_pre_trigger_and_ignition(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    cfg = PromoterConfig.from_env()
    det = TelegramTopicDetector(config=cfg, clock=fake_clock)
    titles = [
        "Russian strike on Kharkiv overnight powerful explosions reported",
        "Kharkiv overnight strike with powerful explosions reported Russia",
        "Powerful overnight strike on Kharkiv Russia explosions",
    ]
    h1 = det.detect(_tg_envelope(signal_envelope_factory, titles[0]))
    h2 = det.detect(_tg_envelope(signal_envelope_factory, titles[1]))
    h3 = det.detect(_tg_envelope(signal_envelope_factory, titles[2]))
    assert h1 is None and h2 is None
    assert h3 is not None
    assert h3.detector_id == "telegram"
    assert h3.cluster_key.startswith("telegram:topic:")
    assert h3.severity == "elevated"
    assert h3.coords is None
    assert len(h3.contributing_signal_ids) == 3


def test_telegram_does_not_match_unrelated_titles(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    det = TelegramTopicDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det.detect(_tg_envelope(signal_envelope_factory, "strike on kharkiv overnight powerful"))
    h = det.detect(_tg_envelope(signal_envelope_factory, "election results in argentina"))
    assert h is None
    # two separate centroids
    assert len(det._centroids) == 2  # noqa: SLF001


def test_telegram_domain_match_boost_lowers_threshold(signal_envelope_factory, fake_clock):
    """Marginal-overlap pair (Jaccard=0.5) matches with domain boost, not without."""
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    # Constructed shingle sets:
    # t1 → {(a,b,c,d,e), (b,c,d,e,f), (c,d,e,f,g)}
    # t2 → {(a,b,c,d,e), (b,c,d,e,f), (c,d,e,f,z)}
    # intersection=2, union=4 ⇒ Jaccard=0.50 — above 0.45 boost, below 0.55 default.
    t1 = "alpha bravo charlie delta echo foxtrot golf"
    t2 = "alpha bravo charlie delta echo foxtrot zulu"

    # Different domains → no boost → 2 separate centroids
    det_no_boost = TelegramTopicDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det_no_boost.detect(_tg_envelope(signal_envelope_factory, t1, url="https://t.me/a/1"))
    det_no_boost.detect(_tg_envelope(signal_envelope_factory, t2, url="https://example.com/x"))
    assert len(det_no_boost._centroids) == 2  # noqa: SLF001

    # Same domain → boost → single centroid
    det_with_boost = TelegramTopicDetector(config=PromoterConfig.from_env(), clock=fake_clock)
    det_with_boost.detect(_tg_envelope(signal_envelope_factory, t1, url="https://t.me/a/1"))
    det_with_boost.detect(_tg_envelope(signal_envelope_factory, t2, url="https://t.me/a/2"))
    assert len(det_with_boost._centroids) == 1  # noqa: SLF001


def test_telegram_lru_evicts_at_capacity(signal_envelope_factory, fake_clock):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    det = TelegramTopicDetector(
        config=PromoterConfig.from_env(), clock=fake_clock, max_centroids=3
    )
    for i in range(4):
        det.detect(_tg_envelope(
            signal_envelope_factory,
            title=f"unique topic number {i} alpha bravo charlie delta echo",
            url=f"https://t.me/u{i}/1",
        ))
    assert len(det._centroids) == 3  # noqa: SLF001


@pytest.mark.parametrize("advance_seconds", [0, 60])
def test_telegram_newest_centroid_survives_full_capacity_and_ignites(
    signal_envelope_factory, fake_clock, advance_seconds
):
    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    cfg = PromoterConfig.from_env()
    cfg = cfg.__class__(**{**cfg.__dict__, "telegram_min_hits": 3})
    det = TelegramTopicDetector(config=cfg, clock=fake_clock, max_centroids=1)
    old_title = "alpha bravo charlie delta echo foxtrot golf"
    new_title = "zulu yankee xray whisky victor hotel india"

    for _ in range(3):
        old_hit = det.detect(_tg_envelope(signal_envelope_factory, old_title))
    assert old_hit is not None
    old_key = old_hit.cluster_key
    if advance_seconds:
        fake_clock.advance(advance_seconds)

    assert det.detect(_tg_envelope(signal_envelope_factory, new_title)) is None
    new_key = next(iter(det._centroids))  # noqa: SLF001
    assert new_key != old_key
    assert old_key not in det._centroids  # noqa: SLF001
    assert det.detect(_tg_envelope(signal_envelope_factory, new_title)) is None
    ignition = det.detect(_tg_envelope(signal_envelope_factory, new_title))

    assert ignition is not None
    assert ignition.cluster_key == new_key
    update = det.detect(_tg_envelope(signal_envelope_factory, new_title))
    assert update is not None
    assert update.cluster_key == new_key


def test_telegram_suppressed_topic_cannot_evict_active_centroid_at_capacity(
    signal_envelope_factory, fake_clock
):
    from datetime import timedelta

    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    det = TelegramTopicDetector(
        config=PromoterConfig.from_env(), clock=fake_clock, max_centroids=1
    )
    suppressed_title = "alpha bravo charlie delta echo foxtrot golf"
    active_title = "zulu yankee xray whisky victor hotel india"
    for _ in range(3):
        suppressed_hit = det.detect(_tg_envelope(signal_envelope_factory, suppressed_title))
    assert suppressed_hit is not None
    suppressed_key = suppressed_hit.cluster_key
    det.on_cluster_terminated(
        suppressed_key, suppress_until=fake_clock() + timedelta(hours=1)
    )

    assert det.detect(_tg_envelope(signal_envelope_factory, active_title)) is None
    active_key = next(iter(det._centroids))  # noqa: SLF001
    assert active_key != suppressed_key
    fake_clock.advance(1)

    assert det.detect(_tg_envelope(signal_envelope_factory, suppressed_title)) is None
    assert list(det._centroids) == [active_key]  # noqa: SLF001
    assert suppressed_key not in det._centroids  # noqa: SLF001


def test_telegram_on_cluster_terminated_with_suppress(signal_envelope_factory, fake_clock):
    from datetime import timedelta

    from app.services.incident_promoter.config import PromoterConfig
    from app.services.incident_promoter.detectors.telegram import TelegramTopicDetector

    cfg = PromoterConfig.from_env()
    det = TelegramTopicDetector(config=cfg, clock=fake_clock)
    for _ in range(3):
        det.detect(_tg_envelope(
            signal_envelope_factory,
            "strike on kharkiv overnight powerful explosions reported",
        ))
    cluster_key = next(iter(det._centroids.values())).cluster_key  # noqa: SLF001
    until = fake_clock() + timedelta(hours=1)
    det.on_cluster_terminated(cluster_key, suppress_until=until)
    # During cooldown nothing accumulates and nothing is emitted
    for _ in range(5):
        assert det.detect(_tg_envelope(
            signal_envelope_factory,
            "strike on kharkiv overnight powerful explosions reported",
        )) is None
