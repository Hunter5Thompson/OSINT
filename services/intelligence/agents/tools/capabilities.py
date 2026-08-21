"""Closed capability policy for tools bound to one immutable run state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from graph.state import AgentState
from spatial import ScopeKind, SpatialScopeTokenV1


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """Declarative availability rule for one registered ReAct tool."""

    name: str
    allowed_scoped: bool
    requires_attached_image: bool = False


CAPABILITY_MATRIX: Final[tuple[ToolCapability, ...]] = (
    ToolCapability("qdrant_search", allowed_scoped=True),
    ToolCapability("query_knowledge_graph", allowed_scoped=True),
    ToolCapability("classify_event", allowed_scoped=True),
    ToolCapability(
        "analyze_image",
        allowed_scoped=True,
        requires_attached_image=True,
    ),
    ToolCapability("gdelt_query", allowed_scoped=False),
    ToolCapability("rss_fetch", allowed_scoped=False),
)

_CAPABILITIES_BY_NAME: Final[Mapping[str, ToolCapability]] = MappingProxyType(
    {capability.name: capability for capability in CAPABILITY_MATRIX}
)


def is_non_global_state(state: AgentState) -> bool:
    """Return whether the pinned run scope must enforce scoped capabilities."""

    scope = state.get("spatial_scope")
    if scope is None:
        return False
    if isinstance(scope, SpatialScopeTokenV1):
        return scope.kind is not ScopeKind.WORLD
    return True


def tool_allowed_for_state(tool_name: str, state: AgentState) -> bool:
    """Fail closed for unknown tools and evaluate the declared capability rule."""

    capability = _CAPABILITIES_BY_NAME.get(tool_name)
    if capability is None:
        return False
    if capability.requires_attached_image and not state.get("image_url"):
        return False
    return not is_non_global_state(state) or capability.allowed_scoped


def blocked_tool_names(state: AgentState) -> tuple[str, ...]:
    """Return deterministic unavailable capabilities in matrix order."""

    return tuple(
        capability.name
        for capability in CAPABILITY_MATRIX
        if not tool_allowed_for_state(capability.name, state)
    )
