from graph_integrity.neo4j_client import Neo4jClient


def test_client_exposes_run_and_close():
    # Constructed lazily — no connection until first run().
    c = Neo4jClient("bolt://localhost:7687", "neo4j", "pw")
    assert hasattr(c, "run")
    assert hasattr(c, "close")
