from app.models.timeline import EventSample, TrackPoint, TrackSample, WindowResponse


def test_event_sample_defaults_nullable():
    s = EventSample(id="ev-1", time="2026-05-01T00:00:00Z", time_basis="indexed")
    assert s.kind == "event"
    assert s.title is None and s.severity is None and s.lat is None


def test_track_sample_roundtrip():
    s = TrackSample(
        id="abc123",
        icao24="abc123",
        points=[TrackPoint(ts_ms=1_700_000_000_000, lat=1.0, lon=2.0)],
    )
    assert s.kind == "track"
    assert s.points[0].ts_ms == 1_700_000_000_000


def test_window_response_shape():
    r = WindowResponse(
        domain="events", tier="coarse",
        t_start="2026-05-01T00:00:00Z", t_end="2026-05-02T00:00:00Z",
        bbox=None, samples=[], total_count=0, truncated=False,
    )
    assert r.truncated is False and r.samples == []
