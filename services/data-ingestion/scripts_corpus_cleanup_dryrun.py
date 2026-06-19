"""TIER-2 DRY-RUN (read-only, NO deletion): list the analysis-lane points the read-path
content gate now drops — i.e. the real delete/archive candidates. Uses the EXACT gate
predicate (feeds.content_quality.content_junk_reason) on the same content->summary->
description->title fallback the read-path uses. Writes candidate IDs + reasons; deletes
nothing."""
from __future__ import annotations

import json
from collections import Counter

import httpx

from feeds.content_quality import content_junk_reason

COLL = "http://localhost:6333/collections/odin_intel"
OUT = "/home/deadpool-ultra/ODIN/odin-data/notebooklm/cleanup_candidates.json"

ANALYSIS_FILTER = {
    "should": [
        {"key": "source", "match": {"any": ["rss", "rss_fulltext", "suv_structured"]}},
        {"must_not": [{"is_empty": {"key": "notebook_id"}}]},
    ],
    "must_not": [{"key": "superseded_by_fulltext", "match": {"value": True}}],
}


def fallback_text(p: dict) -> str:
    return p.get("content") or p.get("summary") or p.get("description") or p.get("title") or ""


def main() -> None:
    total = 0
    by_reason = Counter()
    by_provider = Counter()
    by_source = Counter()
    candidates = []
    samples: dict[str, list] = {}
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False, "filter": ANALYSIS_FILTER}
        if offset is not None:
            body["offset"] = offset
        r = httpx.post(f"{COLL}/points/scroll", json=body, timeout=60).json()["result"]
        for pt in r["points"]:
            total += 1
            pl = pt["payload"]
            reason = content_junk_reason(fallback_text(pl))
            if reason is None:
                continue
            by_reason[reason] += 1
            by_source[pl.get("source")] += 1
            by_provider[pl.get("provider")] += 1
            candidates.append({"id": pt["id"], "reason": reason,
                               "source": pl.get("source"), "provider": pl.get("provider"),
                               "title": pl.get("title")})
            samples.setdefault(reason, [])
            if len(samples[reason]) < 5:
                samples[reason].append(
                    {"provider": pl.get("provider"), "title": (pl.get("title") or "")[:70],
                     "text": fallback_text(pl)[:110]})
        offset = r.get("next_page_offset")
        if offset is None:
            break

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)
    pct = (100 * len(candidates) / total) if total else 0.0
    print(f"=== TIER-2 DRY-RUN (analysis lane: {total} points) ===")
    print(f"DELETE/ARCHIVE CANDIDATES: {len(candidates)} ({pct:.2f}%)  "
          f"-> ids written to {OUT}  (NOTHING DELETED)")
    print(f"by reason:   {dict(by_reason)}")
    print(f"by source:   {dict(by_source)}")
    print("top providers:")
    for prov, c in by_provider.most_common(10):
        print(f"  {c:>4}  {prov}")
    for reason, items in samples.items():
        print(f"\n--- sample {reason} ---")
        for it in items:
            print(f"  [{it['provider']}] {it['title']!r}")
            print(f"      {it['text']!r}")


if __name__ == "__main__":
    main()
