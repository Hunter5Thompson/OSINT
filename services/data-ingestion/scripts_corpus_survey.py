"""READ-ONLY corpus quality survey of Qdrant `odin_intel`. Quantifies junk chunks
(empty, base64-image blobs, keyword-soup / no prose) WITHOUT deleting anything.
Goal: diagnose scale + shape before defining a cleaning policy + dry-run."""
from __future__ import annotations

import re
from collections import Counter

import httpx

COLL = "http://localhost:6333/collections/odin_intel"
B64 = re.compile(r"base64,[A-Za-z0-9+/=]+")


def signals(p: dict) -> dict:
    # Mirror the read-path/_excerpt fallback: bare rss stores prose under `summary`,
    # not `content`. Reading only `content` falsely flags ~14k valid rss as empty.
    c = p.get("content") or p.get("summary") or p.get("description") or p.get("title") or ""
    stripped = c.strip()
    n = len(stripped)
    b64 = sum(len(m) for m in B64.findall(c))
    b64_frac = (b64 / n) if n else 0.0
    sentences = c.count(".") + c.count("!") + c.count("?")
    words = len(stripped.split())
    is_nlm = bool(p.get("notebook_id")) or p.get("source_type") == "notebooklm"
    # classify (NLM single-sentence claims are valid prose -> never keyword-soup)
    if n < 30:
        cat = "EMPTY"
    elif b64_frac > 0.30:
        cat = "IMAGE_HEAVY"
    elif (not is_nlm) and n >= 200 and sentences <= 1:
        cat = "LOW_PROSE"      # long text, ~no sentence structure = nav/keyword soup
    else:
        cat = "ok"
    return {"cat": cat, "n": n, "b64_frac": round(b64_frac, 2),
            "sentences": sentences, "words": words, "is_nlm": is_nlm,
            "provider": p.get("provider"), "source": p.get("source"),
            "title": p.get("title"), "preview": stripped[:90]}


def main() -> None:
    total = 0
    cats = Counter()
    by_provider_junk = Counter()
    by_source = Counter()
    samples: dict[str, list] = {"EMPTY": [], "IMAGE_HEAVY": [], "LOW_PROSE": []}
    # Retrievable ANALYSIS lane only (mirrors intelligence rag/corpus_policy.analysis_filter):
    # source in analysis sources OR NLM (notebook_id present), and NOT superseded.
    analysis_filter = {
        "should": [
            {"key": "source", "match": {"any": ["rss", "rss_fulltext", "suv_structured"]}},
            {"must_not": [{"is_empty": {"key": "notebook_id"}}]},
        ],
        "must_not": [{"key": "superseded_by_fulltext", "match": {"value": True}}],
    }
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False,
                "filter": analysis_filter}
        if offset is not None:
            body["offset"] = offset
        r = httpx.post(f"{COLL}/points/scroll", json=body, timeout=60).json()["result"]
        pts = r["points"]
        for pt in pts:
            total += 1
            s = signals(pt["payload"])
            cats[s["cat"]] += 1
            by_source[s["source"]] += 1
            if s["cat"] != "ok":
                by_provider_junk[s["provider"]] += 1
                if len(samples[s["cat"]]) < 6:
                    samples[s["cat"]].append(s)
        offset = r.get("next_page_offset")
        if offset is None:
            break

    junk = total - cats["ok"]
    print(f"=== odin_intel survey: {total} points ===")
    print(f"OK: {cats['ok']}  |  JUNK: {junk} ({100*junk/total:.1f}%)")
    for k in ("EMPTY", "IMAGE_HEAVY", "LOW_PROSE"):
        print(f"  {k}: {cats[k]}")
    print("\n=== points by source ===")
    for src, c in by_source.most_common():
        print(f"  {src}: {c}")
    print("\n=== top providers by junk count ===")
    for prov, c in by_provider_junk.most_common(12):
        print(f"  {c:>4}  {prov}")
    for cat, items in samples.items():
        print(f"\n=== sample {cat} ===")
        for it in items:
            print(f"  [{it['source']}|{it['provider']}] n={it['n']} sent={it['sentences']} "
                  f"b64={it['b64_frac']} :: {it['title']!r}")
            print(f"      {it['preview']!r}")


if __name__ == "__main__":
    main()
