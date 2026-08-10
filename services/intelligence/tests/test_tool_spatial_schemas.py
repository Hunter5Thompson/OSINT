"""Model-visible tool schemas must not expose trusted runtime inputs."""

from agents.tools.graph_query import query_knowledge_graph
from agents.tools.qdrant_search import qdrant_search
from agents.tools.vision import analyze_image


def _properties(tool) -> set[str]:  # type: ignore[no-untyped-def]
    schema = tool.tool_call_schema.model_json_schema()
    return set(schema.get("properties", {}))


def test_retrieval_and_vision_tool_schemas_hide_runtime_controls() -> None:
    assert _properties(qdrant_search) == {"query"}
    assert _properties(query_knowledge_graph) == {"question"}
    assert _properties(analyze_image) == {"question"}

    forbidden = {"scope", "spatial_scope", "spatial_relation", "region", "image_url"}
    for tool in (qdrant_search, query_knowledge_graph, analyze_image):
        assert _properties(tool).isdisjoint(forbidden)
