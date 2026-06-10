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


from app.models.timeline import (  # noqa: E402
    EventDetail,
    GeoEvent,
    HistogramBucket,
    HistogramResponse,
    Notable,
)


def test_histogram_bucket_defaults():
    b = HistogramBucket(ts="2026-06-01T00:00:00Z", count=3, dominant_category="civil")
    assert b.by_category == {} and b.by_severity == {}


def test_histogram_response_shape():
    r = HistogramResponse(
        t_start="a", t_end="b", bucket_ms=1000, buckets=[],
        notables=[], geo_events=[], total_count=0,
        geo_located_count=0, geo_truncated=False,
    )
    assert r.notables == [] and r.geo_truncated is False


def test_notable_and_geo_and_detail():
    n = Notable(id="e1", time="t", time_basis="indexed", severity="high",
                is_incident=False, rank=0)
    g = GeoEvent(id="e1", time="t", codebook_type="military.x", severity="high",
                 lat=1.0, lon=2.0, is_incident=False)
    d = EventDetail(id="e1", time="t", time_basis="indexed")
    assert n.severity == "high" and g.lat == 1.0 and d.title is None
