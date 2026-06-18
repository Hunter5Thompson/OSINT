from graph.schema_whitelist import RELATIONSHIPS, schema_prompt_block


def test_procurement_relations_in_whitelist():
    for rel in ("PROCURES", "CONTRACTED_TO", "CONCERNS_SYSTEM"):
        assert rel in RELATIONSHIPS
        assert rel in schema_prompt_block()
