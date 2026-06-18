from graph.schema_whitelist import RELATIONSHIPS, schema_prompt_block


def test_operates_in_whitelist():
    assert "OPERATES" in RELATIONSHIPS
    assert "HEADQUARTERED_IN" in RELATIONSHIPS  # Slice-1 edge, previously missing
    assert "OPERATES" in schema_prompt_block()
    assert "HEADQUARTERED_IN" in schema_prompt_block()
