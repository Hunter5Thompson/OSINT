from unittest.mock import AsyncMock, patch

from pipeline import _resolve_timeline, process_item
from tests.test_pipeline import _make_settings, _mock_neo4j_response, _mock_vllm_response


def test_precedence_occurred_wins():
    at, basis = _resolve_timeline(
        occurred_at="2026-05-01T00:00:00+00:00",
        observed_at="2026-05-02T00:00:00+00:00",
        published_at="2026-05-03T00:00:00+00:00",
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-01T00:00:00+00:00" and basis == "occurred"


def test_falls_back_to_ingested():
    at, basis = _resolve_timeline(
        occurred_at=None, observed_at=None, published_at=None,
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-04T00:00:00+00:00" and basis == "ingested"


def test_malformed_occurred_is_dropped_not_fabricated():
    # malformed LLM hint -> not used; falls through to ingested, never now()
    at, basis = _resolve_timeline(
        occurred_at="last tuesday", observed_at=None, published_at=None,
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-04T00:00:00+00:00" and basis == "ingested"


def test_tz_naive_iso_is_normalized_to_utc():
    at, basis = _resolve_timeline(
        occurred_at="2026-05-01T00:00:00", observed_at=None, published_at=None,
        ingested_at="2026-05-04T00:00:00+00:00",
    )
    assert at == "2026-05-01T00:00:00+00:00" and basis == "occurred"


async def test_event_write_includes_timeline_at():
    """The Event CREATE statement carries timeline_at/time_basis; a structured
    occurred_at kwarg wins and is normalized to tz-aware UTC."""
    vllm = _mock_vllm_response(events=[{
        "title": "x", "summary": "y", "codebook_type": "military.airstrike",
        "severity": "high", "confidence": 0.9,
    }])
    neo = _mock_neo4j_response()

    with patch("pipeline.httpx.AsyncClient") as cls:
        mc = AsyncMock()
        mc.post.side_effect = [vllm, neo]
        cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await process_item(
            title="t", text="x", url="http://e/1", source="usgs",
            settings=_make_settings(), occurred_at="2026-05-01T00:00:00Z",
        )
        neo_call = mc.post.call_args_list[1]

    stmt = neo_call.kwargs["json"]["statements"]
    ev_stmt = next(s for s in stmt if "ev:Event" in s["statement"])
    assert "timeline_at: datetime($timeline_at)" in ev_stmt["statement"]
    assert ev_stmt["parameters"]["timeline_at"] == "2026-05-01T00:00:00+00:00"
    assert ev_stmt["parameters"]["time_basis"] == "occurred"


async def test_event_write_falls_back_to_ingested_without_structured_time():
    """No structured time + no LLM hint -> time_basis 'ingested', never fabricated
    as 'occurred'."""
    vllm = _mock_vllm_response(events=[{
        "title": "x", "summary": "y", "codebook_type": "military.airstrike",
        "severity": "low", "confidence": 0.5,
    }])
    neo = _mock_neo4j_response()

    with patch("pipeline.httpx.AsyncClient") as cls:
        mc = AsyncMock()
        mc.post.side_effect = [vllm, neo]
        cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await process_item(
            title="t", text="x", url="http://e/2", source="rss",
            settings=_make_settings(),
        )
        neo_call = mc.post.call_args_list[1]

    ev_stmt = next(
        s for s in neo_call.kwargs["json"]["statements"] if "ev:Event" in s["statement"]
    )
    assert ev_stmt["parameters"]["time_basis"] == "ingested"
    assert ev_stmt["parameters"]["timeline_at"]  # non-empty ISO string
