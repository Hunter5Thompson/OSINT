from munin_distill.query_gen import build_queries

ENTITIES = {"country": ["Iran", "China"], "company": ["Rheinmetall"]}
TEMPLATES = ["Aktuelle Lage zu {e}?", "Bedrohungseinschätzung {e}"]


def test_builds_unique_balanced_queries():
    rows = build_queries(ENTITIES, TEMPLATES, target=6)
    qs = [r["query"] for r in rows]
    assert len(qs) == len(set(qs))          # no duplicates
    assert all(r["category"] in ENTITIES for r in rows)
    assert all("{e}" not in q for q in qs)  # templates filled
    assert len(rows) <= 6


def test_round_robin_balances_categories():
    rows = build_queries(ENTITIES, TEMPLATES, target=4)
    # first two picks should span two different categories (round-robin), not both 'country'
    assert {rows[0]["category"], rows[1]["category"]} == {"country", "company"}


def test_ids_are_stable_and_unique():
    rows = build_queries(ENTITIES, TEMPLATES, target=6)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    assert all(len(i) == 16 for i in ids)
