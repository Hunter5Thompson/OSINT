from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graph_integrity.neo4j_client import Neo4jClient


def test_client_interface_is_importable():
    # Interface smoke test — patch the driver factory so no real driver/socket
    # is created (avoids ResourceWarning); only the public interface is checked.
    with patch("graph_integrity.neo4j_client.AsyncGraphDatabase.driver"):
        c = Neo4jClient("bolt://localhost:7687", "neo4j", "pw")
    assert hasattr(c, "run")
    assert hasattr(c, "explain")
    assert hasattr(c, "close")


@pytest.mark.asyncio
async def test_explain_returns_json_safe_plan_and_binds_parameters() -> None:
    result = MagicMock()
    result.consume = AsyncMock(
        return_value=MagicMock(
            plan={
                "operator_type": "NodeIndexSeek",
                "arguments": {"Details": "Location(country_scope_key)"},
                "children": [],
            }
        )
    )
    session = MagicMock(run=AsyncMock(return_value=result))
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)
    driver = MagicMock()
    driver.session.return_value = session_context

    with patch(
        "graph_integrity.neo4j_client.AsyncGraphDatabase.driver",
        return_value=driver,
    ):
        client = Neo4jClient("bolt://localhost:7687", "neo4j", "pw")

    query = "EXPLAIN MATCH (l:Location) WHERE l.country_scope_key = $key RETURN l"
    plan = await client.explain(query, {"key": "country:UKR"})

    assert plan["operator_type"] == "NodeIndexSeek"
    session.run.assert_awaited_once_with(query, {"key": "country:UKR"})


@pytest.mark.asyncio
async def test_explain_rejects_non_explain_query() -> None:
    with patch("graph_integrity.neo4j_client.AsyncGraphDatabase.driver"):
        client = Neo4jClient("bolt://localhost:7687", "neo4j", "pw")

    with pytest.raises(ValueError, match="requires an EXPLAIN query"):
        await client.explain("MATCH (n) RETURN n")
