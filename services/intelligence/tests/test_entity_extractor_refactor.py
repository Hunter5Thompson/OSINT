"""Tests that entity_extractor uses GraphClient instead of raw HTTP."""

from unittest.mock import AsyncMock
import pytest

from extraction.entity_extractor import EntityExtractor, ExtractionResult, ExtractedEntity

# Valid entity types (must match the whitelist in ExtractedEntity)
VALID_TYPES = {"Person", "Organization", "Country", "Location", "Facility", "Commodity", "Event"}


class TestEntityTypeWhitelist:
    """Finding #1: ExtractedEntity.type must be whitelisted, not free-form str."""

    def test_valid_types_accepted(self):
        for t in VALID_TYPES:
            e = ExtractedEntity(name="X", type=t, mention="X", context="ctx")
            assert e.type == t

    def test_injection_type_rejected(self):
        """A crafted type like 'Person} SET n.pwned=true WITH n MERGE (x:Hacked {name: $name'
        must not be accepted."""
        with pytest.raises(ValueError):
            ExtractedEntity(
                name="X",
                type='Person} SET n.pwned=true WITH n MERGE (x:Hacked {name: $name',
                mention="X",
                context="ctx",
            )

    def test_arbitrary_string_rejected(self):
        with pytest.raises(ValueError):
            ExtractedEntity(name="X", type="NotAValidType", mention="X", context="ctx")


class TestWritePathUsesParameterizedCypher:
    """Finding #2: Write path must not use f-string label interpolation."""

    async def test_no_fstring_interpolation_in_cypher(self):
        """The Cypher passed to run_query must NOT contain the entity type
        as an interpolated label. It must use $type as a parameter."""
        mock_graph = AsyncMock()
        mock_graph.run_query.return_value = [{"d": "ok"}]

        extractor = EntityExtractor(
            vllm_url="http://localhost:8000",
            graph_client=mock_graph,
        )

        result = ExtractionResult(entities=[
            ExtractedEntity(name="NATO", type="Organization", mention="NATO forces", context="ctx"),
        ])

        await extractor.write_to_neo4j(result, "Doc", "http://test.com", "rss")

        # Check all Cypher strings passed to run_query
        for call in mock_graph.run_query.call_args_list:
            cypher = call.args[0] if call.args else call.kwargs.get("cypher", "")
            # The literal word "Organization" must NOT appear in the Cypher string
            assert "Organization" not in cypher, (
                f"Entity type interpolated into Cypher (injection risk): {cypher}"
            )


class TestWritePathUsesTemplates:
    """Verify write_to_neo4j uses imported template constants, not inline strings."""

    async def test_cypher_matches_template_constants(self):
        from graph.write_templates import UPSERT_DOCUMENT, UPSERT_ENTITY_WITH_MENTION

        mock_graph = AsyncMock()
        mock_graph.run_query.return_value = [{"d": "ok"}]

        extractor = EntityExtractor(
            vllm_url="http://localhost:8000",
            graph_client=mock_graph,
        )
        result = ExtractionResult(entities=[
            ExtractedEntity(name="NATO", type="Organization", mention="NATO forces", context="ctx"),
        ])
        await extractor.write_to_neo4j(result, "Doc", "http://test.com", "rss")

        calls = mock_graph.run_query.call_args_list
        # First call: Document upsert
        assert calls[0].args[0] == UPSERT_DOCUMENT
        # Second call: Entity+Mentions upsert
        assert calls[1].args[0] == UPSERT_ENTITY_WITH_MENTION


class TestEntityExtractorUsesGraphClient:
    async def test_write_to_neo4j_calls_graph_client(self):
        mock_graph = AsyncMock()
        mock_graph.run_query.return_value = [{"d": "ok"}]

        extractor = EntityExtractor(
            vllm_url="http://localhost:8000",
            graph_client=mock_graph,
        )

        result = ExtractionResult(entities=[
            ExtractedEntity(
                name="NATO",
                type="Organization",
                mention="NATO forces",
                context="NATO deployed troops",
            ),
        ])

        count = await extractor.write_to_neo4j(result, "Test Doc", "http://test.com", "rss")

        assert count == 1
        assert mock_graph.run_query.call_count >= 2  # Document + Entity

    async def test_write_to_neo4j_no_entities(self):
        mock_graph = AsyncMock()
        extractor = EntityExtractor(
            vllm_url="http://localhost:8000",
            graph_client=mock_graph,
        )
        count = await extractor.write_to_neo4j(
            ExtractionResult(entities=[]), "Title", "http://x.com"
        )
        assert count == 0
        mock_graph.run_query.assert_not_called()

    async def test_write_to_neo4j_without_graph_client_returns_zero(self):
        extractor = EntityExtractor(vllm_url="http://localhost:8000")
        result = ExtractionResult(entities=[
            ExtractedEntity(name="X", type="Person", mention="X", context="ctx"),
        ])
        count = await extractor.write_to_neo4j(result, "Title", "http://x.com")
        assert count == 0
