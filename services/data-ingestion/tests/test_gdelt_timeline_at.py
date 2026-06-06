from gdelt_raw.writers.neo4j_writer import MERGE_EVENT


def test_merge_event_sets_timeline_at_on_create_and_match():
    assert "timeline_at = datetime($date_added)" in MERGE_EVENT
    assert "time_basis = 'indexed'" in MERGE_EVENT
    # present in both ON CREATE and ON MATCH blocks
    create_block, _, match_block = MERGE_EVENT.partition("ON MATCH SET")
    assert "timeline_at" in create_block and "timeline_at" in match_block
    assert "time_basis" in create_block and "time_basis" in match_block
