from graph_integrity.reconcile_orphans import OrphanCandidate, find_orphans


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
