import time

from app.models.signals import SignalEnvelope, SignalPayload
from app.services.signal_stream import SignalStream

# Base ms on current wall-clock so entries fall INSIDE the prune window.
# `_prune()` drops anything older than `now - window_seconds`; a fixed past
# epoch would be pruned away regardless of how large the window is. This
# matches the convention in tests/unit/test_signals_stream.py.
_BASE_MS = int(time.time() * 1000)


def _env(ms: int, title: str) -> SignalEnvelope:
    return SignalEnvelope(
        event_id=f"{ms:013d}-000000", ts="2026-06-01T10:00:00.000Z",
        type="signal.rss",
        payload=SignalPayload(
            title=title, severity="low", source="x",
            redis_id=f"{ms}-0", country="Germany",
        ),
    )


def test_snapshot_returns_newest_first_over_full_buffer():
    s = SignalStream(max_size=100, window_seconds=99999)
    for i in range(60):
        s._buffer.append(_env(_BASE_MS + i, f"t{i}"))
    snap = s.snapshot()
    assert len(snap) == 60                       # not capped at 50
    assert snap[0].payload.title == "t59"        # newest first


def test_snapshot_prunes_stale():
    s = SignalStream(max_size=100, window_seconds=0)  # everything is stale
    s._buffer.append(_env(1, "old"))
    assert s.snapshot() == []


def test_match_signals_keeps_freshest_five_from_many():
    from app.services.country_almanac import get_country_almanac_store
    get_country_almanac_store.cache_clear()
    store = get_country_almanac_store()
    s = SignalStream(max_size=100, window_seconds=99999)
    for i in range(12):                                   # 12 Germany matches
        s._buffer.append(_env(_BASE_MS + i, f"de{i}"))
    matched = store.match_signals("DEU", s.snapshot(), limit=5)
    assert len(matched) == 5
    assert matched[0].title == "de11"                     # freshest first
