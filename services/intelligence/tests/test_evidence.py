import json

from rag.evidence import format_evidence_pack, to_evidence_item


class TestSourceClass:
    def test_realtime_marker_in_evidence_line(self):
        item = to_evidence_item({
            "source": "telegram", "telegram_channel": "wartranslated",
            "title": "lead", "content": "raw lead", "score": 0.5,
            "source_class": "realtime",
        })
        assert item.source_class == "realtime"
        pack = format_evidence_pack([item], budget=2000)
        meta_line = next(ln for ln in pack.splitlines() if ln.startswith("[EVIDENCE] "))
        meta = json.loads(meta_line[len("[EVIDENCE] "):])
        assert meta["source_class"] == "realtime"

    def test_analysis_item_has_no_source_class_key(self):
        item = to_evidence_item({
            "source": "rss", "feed_name": "CSIS", "title": "t",
            "summary": "s", "score": 0.5,
        })
        assert item.source_class is None
        pack = format_evidence_pack([item], budget=2000)
        meta_line = next(ln for ln in pack.splitlines() if ln.startswith("[EVIDENCE] "))
        assert "source_class" not in json.loads(meta_line[len("[EVIDENCE] "):])
