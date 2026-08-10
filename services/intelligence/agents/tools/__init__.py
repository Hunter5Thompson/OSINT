from langchain_core.tools import BaseTool

from agents.tools.capabilities import CAPABILITY_MATRIX
from agents.tools.capabilities import blocked_tool_names as blocked_tool_names
from agents.tools.classify import classify_event
from agents.tools.gdelt_query import gdelt_query
from agents.tools.graph_query import query_knowledge_graph
from agents.tools.qdrant_search import qdrant_search
from agents.tools.rss_fetch import rss_fetch
from agents.tools.vision import analyze_image
from graph.state import AgentState

_REGISTERED_TOOLS = [
    qdrant_search,
    query_knowledge_graph,
    classify_event,
    analyze_image,
    gdelt_query,
    rss_fetch,
]
_TOOLS_BY_NAME = {tool.name: tool for tool in _REGISTERED_TOOLS}
_CAPABILITY_NAMES = {capability.name for capability in CAPABILITY_MATRIX}
if _TOOLS_BY_NAME.keys() != _CAPABILITY_NAMES:
    raise RuntimeError("tool registry must exactly match the closed capability matrix")

ALL_TOOLS: list[BaseTool] = [
    _TOOLS_BY_NAME[capability.name] for capability in CAPABILITY_MATRIX
]


def tools_for_state(state: AgentState) -> list[BaseTool]:
    """Bind only capabilities permitted by the immutable run state."""

    blocked = set(blocked_tool_names(state))
    return [tool for tool in ALL_TOOLS if tool.name not in blocked]
