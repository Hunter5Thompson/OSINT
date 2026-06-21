"""Generate a diverse Munin query set from ODIN's taxonomy (entities x templates).

Round-robins over categories so the set stays balanced, fills each template with an
entity, dedups, and assigns a stable 16-char id per query."""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path


def build_queries(entities: dict[str, list[str]], templates: list[str], target: int) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    pools = {cat: list(itertools.product(vals, templates)) for cat, vals in entities.items()}
    cats = list(pools)
    idx = 0
    while len(rows) < target and any(pools.values()):
        cat = cats[idx % len(cats)]
        idx += 1
        if not pools[cat]:
            continue
        ent, tmpl = pools[cat].pop(0)
        q = tmpl.format(e=ent)
        if q in seen:
            continue
        seen.add(q)
        rows.append(
            {"id": hashlib.sha1(q.encode("utf-8")).hexdigest()[:16], "query": q, "category": cat}
        )
    return rows


def write_queries(rows: list[dict], path: str) -> None:
    Path(path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))


if __name__ == "__main__":  # pragma: no cover
    import sys

    from munin_distill import taxonomy

    target = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    out = sys.argv[2] if len(sys.argv) > 2 else "artifacts/queries.jsonl"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    generated = build_queries(taxonomy.ENTITIES, taxonomy.TEMPLATES, target)
    write_queries(generated, out)
    print(f"wrote {len(generated)} queries -> {out}")
