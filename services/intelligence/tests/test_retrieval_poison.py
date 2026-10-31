"""L04 invalid hits cannot hide a valid best hit or create lineage."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.qdrant_search import qdrant_search
from rag.corpus_policy import apply_tier_boost, validate_lane
from spatial import parse_spatial_application_marker
from tests.tool_runtime import invoke_runtime_tool_message

PROSE = "Synthetic source reports several changes in the region with sufficient detail."


def _hit(score, key):
    return {
        "source": "rss",
        "source_type": "rss",
        "provider": "unit.example",
        "content_hash": key,
        "title": key,
        "content": PROSE,
        "score": score,
    }


@pytest.mark.parametrize(
    "score", [float("nan"), float("inf"), -float("inf"), True, "0.9", None, 10**400]
)
def test_poison_score_does_not_hide_healthy_best(score):
    out = apply_tier_boost([_hit(0.12, "low"), _hit(score, "bad"), _hit(0.92, "best")])
    assert [row["title"] for row in out] == ["best", "low"]


@pytest.mark.parametrize("content", [["poison"], None, {"text": "poison"}, 9])
def test_nontext_content_isolated_between_healthy_neighbors(content):
    low, best = _hit(0.12, "low"), _hit(0.92, "best")
    assert validate_lane([low, {**_hit(0.5, "bad"), "content": content}, best], "analysis") == [
        low,
        best,
    ]


def test_nonfinite_final_scores_produce_no_valid_hits():
    assert apply_tier_boost([_hit(0.5, "bad")], lam=float("nan")) == []


async def test_tool_artifact_contains_only_valid_rendered_hits():
    hits = [
        _hit(0.12, "low"),
        {**_hit(0.5, "bad"), "content": ["poison"]},
        _hit(float("nan"), "bad-score"),
        _hit(0.92, "best"),
    ]
    with patch("agents.tools.qdrant_search.enhanced_search", AsyncMock(side_effect=[hits, []])):
        result = await invoke_runtime_tool_message(qdrant_search, {"query": "synthetic"})
    assert [item["title"] for item in result.artifact] == ["low", "best"]
    assert "bad-score" not in result.content and "poison" not in result.content


async def test_all_poison_returns_diagnosed_empty_without_lineage():
    with patch(
        "agents.tools.qdrant_search.enhanced_search",
        AsyncMock(side_effect=[[_hit(float("nan"), "bad")], []]),
    ):
        result = await invoke_runtime_tool_message(qdrant_search, {"query": "synthetic"})
    assert result.artifact == []
    assert "NO_VALID_RETRIEVAL_HITS" in result.content
    marker, _text = parse_spatial_application_marker(
        result.content, actual_tool_name="qdrant_search"
    )
    assert marker.completeness == "partial"
    assert marker.detail_code == "invalid-retrieval-hits"


async def test_rejected_hits_in_tier_callback_remain_visible_to_tool():
    async def retriever(query, **kwargs):
        hits = [_hit(0.12, "low"), _hit(float("nan"), "bad"), _hit(0.92, "best")]
        return kwargs["post_rerank"](hits)

    with patch("agents.tools.qdrant_search.enhanced_search", side_effect=retriever):
        result = await invoke_runtime_tool_message(qdrant_search, {"query": "synthetic"})
    marker, _text = parse_spatial_application_marker(
        result.content, actual_tool_name="qdrant_search"
    )
    assert marker.completeness == "partial"
    assert "bad" not in [item["title"] for item in result.artifact]
