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


class TestTierBoost:
    def _rss(self, feed, content, score, rerank):
        return {"source": "rss", "feed_name": feed, "content": content,
                "title": content, "score": score, "rerank_score": rerank}

    def test_credibility_of_rss_and_nlm(self):
        assert cp.credibility_of(self._rss("CSIS", "x", 0.9, 5.0)) == 0.82
        assert cp.credibility_of(self._rss("Local Paper", "x", 0.9, 5.0)) == 0.60
        nlm = {"notebook_id": "nb1", "content": "claim", "title": "t", "score": 0.9}
        assert cp.credibility_of(nlm) == 0.60  # notebooklm baseline

    def test_near_tie_flips_to_higher_credibility(self):
        # In a realistic pool, two near-tie middle items differ by a small
        # fraction of the span; the think-tank's credibility flips the order.
        pool = [
            self._rss("Filler Low", "lo", 0.5, 0.0),     # establishes min
            self._rss("Filler High", "hi", 0.5, 10.0),   # establishes max (span)
            self._rss("Local Paper", "a", 0.9, 5.05),    # cred 0.60, slightly MORE relevant
            self._rss("CSIS", "b", 0.9, 5.00),           # cred 0.82, slightly less relevant
        ]
        out = cp.apply_tier_boost(pool)
        csis_idx = next(i for i, r in enumerate(out) if r["feed_name"] == "CSIS")
        local_idx = next(i for i, r in enumerate(out) if r["feed_name"] == "Local Paper")
        assert csis_idx < local_idx   # think-tank overtakes the near-tie local source

    def test_large_relevance_gap_not_flipped(self):
        local = self._rss("Local Paper", "a", 0.9, 10.0)  # much more relevant
        tank = self._rss("CSIS", "b", 0.9, 0.0)
        out = cp.apply_tier_boost([local, tank])
        assert out[0]["feed_name"] == "Local Paper"

    def test_max_equals_min_sorts_by_credibility_no_zerodiv(self):
        local = self._rss("Local Paper", "a", 0.5, 3.0)
        tank = self._rss("CSIS", "b", 0.5, 3.0)  # identical rerank scores
        out = cp.apply_tier_boost([local, tank])
        assert out[0]["feed_name"] == "CSIS"

    def test_falls_back_to_dense_score_without_rerank_score(self):
        a = {"source": "rss", "feed_name": "CSIS", "content": "a", "title": "a", "score": 0.8}
        b = {"source": "rss", "feed_name": "Local Paper",
             "content": "b", "title": "b", "score": 0.2}
        out = cp.apply_tier_boost([a, b])  # no rerank_score key
        assert out[0]["feed_name"] == "CSIS"
        assert "tier_score" in out[0]
