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


class TestGuardAndMerge:
    def test_validate_analysis_drops_cross_lane(self, caplog):
        rss = {"source": "rss", "feed_name": "CSIS"}
        nlm = {"source": "unknown", "notebook_id": "nb1"}
        junk = {"source": "gdelt_gkg", "doc_id": "gdelt:gkg:1"}
        firms = {"source": "firms"}
        kept = cp.validate_lane([rss, nlm, junk, firms], "analysis")
        assert kept == [rss, nlm]

    def test_validate_realtime_only_allowlisted(self):
        ok = {"source": "telegram", "telegram_channel": "wartranslated"}
        bad = {"source": "telegram", "telegram_channel": "rybar"}
        assert cp.validate_lane([ok, bad], "realtime") == [ok]

    def test_merge_caps_one_realtime_at_end(self):
        analysis = [{"id": i} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated"}]
        out = cp.merge_lanes(analysis, realtime)
        assert len(out) == 5
        assert out[:4] == analysis[:4]
        assert out[4]["source_class"] == "realtime"

    def test_merge_no_realtime_keeps_five_analysis(self):
        analysis = [{"id": i} for i in range(5)]
        out = cp.merge_lanes(analysis, [])
        assert out == analysis[:5]
        assert all("source_class" not in r for r in out)

    def test_validate_rejects_inconsistent_source_type(self):
        # raw source says rss but canonical source_type says gdelt -> reject
        bad = {"source": "rss", "feed_name": "x", "source_type": "gdelt"}
        good = {"source": "rss", "feed_name": "CSIS", "source_type": "rss"}
        assert cp.validate_lane([good, bad], "analysis") == [good]

    def test_validate_realtime_rejects_inconsistent_source_type(self):
        bad = {"source": "telegram", "telegram_channel": "wartranslated",
               "source_type": "rss"}
        assert cp.validate_lane([bad], "realtime") == []

    def test_merge_uses_telegram_max(self):
        analysis = [{"id": i} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated"},
                    {"source": "telegram", "telegram_channel": "OSINTdefender"}]
        out = cp.merge_lanes(analysis, realtime)
        assert sum(1 for r in out if r.get("source_class") == "realtime") == cp.TELEGRAM_MAX
        assert len(out) == 5

    def test_merge_empty_analysis_with_realtime(self):
        out = cp.merge_lanes([], [{"source": "telegram", "telegram_channel": "wartranslated"}])
        assert len(out) == 1
        assert out[0]["source_class"] == "realtime"

    def test_merge_respects_final_k_when_telegram_max_exceeds_it(self):
        # misconfig guard: telegram_max > final_k must NOT exceed final_k total
        analysis = [{"id": i} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated"},
                    {"source": "telegram", "telegram_channel": "OSINTdefender"},
                    {"source": "telegram", "telegram_channel": "liveuamap"}]
        out = cp.merge_lanes(analysis, realtime, final_k=2, telegram_max=3)
        assert len(out) == 2  # never more than final_k


class TestFulltextReadPath:
    def test_analysis_sources_includes_fulltext(self):
        assert frozenset({"rss", "rss_fulltext"}) == cp.ANALYSIS_SOURCES

    def test_analysis_filter_allows_fulltext_and_excludes_superseded(self):
        f = cp.analysis_filter()
        assert {"key": "source", "match": {"any": sorted(cp.ANALYSIS_SOURCES)}} in f["should"]
        assert {"key": "superseded_by_fulltext", "match": {"value": True}} in f["must_not"]

    def test_validate_lane_keeps_fulltext_chunk(self):
        chunk = {"source": "rss_fulltext", "source_type": "rss", "feed_name": "CSIS"}
        assert cp.validate_lane([chunk], "analysis") == [chunk]

    def test_validate_lane_drops_superseded_teaser(self):
        teaser = {"source": "rss", "feed_name": "CSIS", "superseded_by_fulltext": True}
        assert cp.validate_lane([teaser], "analysis") == []
