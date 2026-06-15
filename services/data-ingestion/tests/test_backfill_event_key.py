from migrations.backfill_event_key import EventRow, plan_backfill


def test_plan_groups_duplicates_and_picks_lowest_id_survivor():
    rows = [
        EventRow(node_id=5, title="Strike on Kyiv", codebook_type="c.armed",
                 doc_url="http://u", doc_title="d"),
        EventRow(node_id=2, title="  strike on  KYIV ", codebook_type="c.armed",
                 doc_url="http://u", doc_title="d"),  # dup of above (normalized)
        EventRow(node_id=9, title="Sanctions on Iran", codebook_type="c.sanction",
                 doc_url="http://u", doc_title="d"),  # singleton
    ]
    plan = plan_backfill(rows)
    assert len(plan.assignments) == 3            # every node gets a key
    assert len(plan.merges) == 1                 # one merge group
    merge = plan.merges[0]
    assert merge.survivor_id == 2                # lowest node_id wins
    assert merge.loser_ids == [5]
    assert plan.key_for(2) == plan.key_for(5)
    assert plan.key_for(9) != plan.key_for(2)


def test_plan_counts_for_dry_run():
    rows = [
        EventRow(2, "a", "t", "http://u", "d"),
        EventRow(3, "a", "t", "http://u", "d"),
    ]
    plan = plan_backfill(rows)
    assert plan.total == 2
    assert plan.duplicate_count == 1   # one node to be merged away
    assert plan.group_count == 1


def test_plan_idempotent_on_already_deduped_rows():
    """Re-run after a successful apply: rows are already unique -> no merges, and the
    recomputed keys equal a fresh EventRow.event_key() (deterministic)."""
    rows = [
        EventRow(2, "Strike on Kyiv", "c.armed", "http://u", "d"),
        EventRow(9, "Sanctions on Iran", "c.sanction", "http://u", "d"),
    ]
    plan = plan_backfill(rows)
    assert plan.merges == []
    assert plan.duplicate_count == 0
    assert plan.key_for(2) == rows[0].event_key()
