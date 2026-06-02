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

    def test_constants_wired_to_settings(self):
        from config import settings
        # the constants must READ from settings (env-overridable), not be hardcoded
        assert settings.rag_tier_boost_lambda == cp.TIER_BOOST_LAMBDA
        assert settings.rag_analysis_pool == cp.ANALYSIS_POOL
        assert settings.rag_realtime_pool == cp.REALTIME_POOL
        assert settings.rag_realtime_score_threshold == cp.RT_SCORE_THRESHOLD
        assert settings.rag_final_k == cp.FINAL_K
        assert settings.rag_telegram_max == cp.TELEGRAM_MAX

    def test_constant_defaults(self):
        # pin the documented starting values
        assert (cp.TIER_BOOST_LAMBDA, cp.ANALYSIS_POOL, cp.REALTIME_POOL) == (0.2, 40, 20)
        assert (cp.RT_SCORE_THRESHOLD, cp.FINAL_K, cp.TELEGRAM_MAX) == (0.45, 5, 1)
