from graph_integrity.reconcile_orphans import (
    OrphanCandidate,
    candidate_from_payload,
    find_orphans,
)


def test_find_orphans_returns_points_whose_url_has_no_document():
    points = [
        OrphanCandidate(point_id=1, title="a", url="http://have"),
        OrphanCandidate(point_id=2, title="b", url="http://missing"),
    ]
    existing_doc_urls = {"http://have"}
    orphans = find_orphans(points, existing_doc_urls)
    assert [o.point_id for o in orphans] == [2]


def test_find_orphans_empty_when_all_present():
    points = [OrphanCandidate(1, "a", "http://have")]
    assert find_orphans(points, {"http://have"}) == []


def test_find_orphans_excludes_empty_url():
    """A point with an empty url is not a healable orphan (no source to re-key on)."""
    points = [OrphanCandidate(point_id=3, title="c", url="")]
    assert find_orphans(points, set()) == []


def test_candidate_from_payload_accepts_live_rss_gdelt():
    c = candidate_from_payload(1, {"source": "rss", "url": "http://a", "title": "t"})
    assert c is not None and c.point_id == 1 and c.url == "http://a"
    g = candidate_from_payload(2, {"source": "gdelt", "url": "http://b", "title": "t"})
    assert g is not None


def test_candidate_from_payload_rejects_other_sources_and_missing_fields():
    ft = candidate_from_payload(3, {"source": "rss_fulltext", "url": "http://c", "title": "t"})
    assert ft is None
    assert candidate_from_payload(4, {"source": "nlm", "url": "http://d", "title": "t"}) is None
    assert candidate_from_payload(5, {"source": "rss", "url": "", "title": "t"}) is None
    assert candidate_from_payload(6, {"source": "rss", "url": "http://e", "title": ""}) is None
    assert candidate_from_payload(7, {"url": "http://f", "title": "t"}) is None  # no source


def test_find_orphans_dedupes_by_url():
    from graph_integrity.reconcile_orphans import OrphanCandidate, find_orphans
    pts = [
        OrphanCandidate(1, "t", "http://dup"),
        OrphanCandidate(2, "t", "http://dup"),   # same url, different chunk/point
        OrphanCandidate(3, "t", "http://other"),
    ]
    orphans = find_orphans(pts, set())
    assert [o.url for o in orphans] == ["http://dup", "http://other"]  # one per url
