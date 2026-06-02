from rag import corpus_policy as cp


class TestLaneFilters:
    def test_analysis_filter_shape(self):
        f = cp.analysis_filter()
        should = f["should"]
        # source ∈ ANALYSIS_SOURCES (match any, extensible to future "nlm")
        assert {"key": "source", "match": {"any": sorted(cp.ANALYSIS_SOURCES)}} in should
        # NLM via notebook_id presence (raw source is "unknown" in legacy points)
        assert {"must_not": [{"is_empty": {"key": "notebook_id"}}]} in should

    def test_realtime_filter_shape(self):
        f = cp.realtime_filter()
        must = f["must"]
        assert {"key": "source", "match": {"value": "telegram"}} in must
        chan = next(c for c in must if c["key"] == "telegram_channel")
        allowed = set(chan["match"]["any"])
        assert {"wartranslated", "OSINTdefender"} <= allowed
        assert "rybar" not in allowed

    def test_constants_present(self):
        assert cp.ANALYSIS_POOL == 40
        assert cp.REALTIME_POOL == 20
        assert cp.RT_SCORE_THRESHOLD == 0.45
        assert cp.FINAL_K == 5
        assert cp.TELEGRAM_MAX == 1
        assert cp.TIER_BOOST_LAMBDA == 0.2
