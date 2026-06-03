class TestFormatRow:
    def test_format_top5_row(self):
        from scripts.measure_corpus_scoping import format_hits

        hits = [
            {"source": "rss", "feed_name": "CSIS", "tier_score": 0.91},
            {"source": "gdelt_gkg", "title": "gdelt:gkg:1"},
        ]
        line = format_hits(hits)
        assert "rss:CSIS" in line
        assert "gdelt_gkg" in line

    def test_queries_constant(self):
        from scripts.measure_corpus_scoping import QUERIES
        assert len(QUERIES) == 6
