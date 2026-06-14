from unittest.mock import patch

from graph_integrity.neo4j_client import Neo4jClient


def test_client_interface_is_importable():
    # Interface smoke test — patch the driver factory so no real driver/socket
    # is created (avoids ResourceWarning); only the public interface is checked.
    with patch("graph_integrity.neo4j_client.AsyncGraphDatabase.driver"):
        c = Neo4jClient("bolt://localhost:7687", "neo4j", "pw")
    assert hasattr(c, "run")
    assert hasattr(c, "close")
