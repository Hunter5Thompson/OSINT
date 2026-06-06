from unittest.mock import AsyncMock, patch

from pipeline import _normalize_iso, _resolve_timeline, process_item
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


def test_normalize_iso_rejects_non_string_input():
    # contract: str | None. A non-string truthy value must drop to None, not crash
    # (so a stray non-str hint falls back to ingested rather than discarding the
    # whole document write under the broad except).
    assert _normalize_iso(123) is None
    assert _normalize_iso(1_714_521_600) is None
    assert _normalize_iso({"x": 1}) is None
    assert _normalize_iso(True) is None


async def _event_params(events, **kwargs) -> dict:
    """Run process_item against mocked vLLM+Neo4j and return the Event statement params."""
    vllm = _mock_vllm_response(events=events)
    neo = _mock_neo4j_response()
    with patch("pipeline.httpx.AsyncClient") as cls:
        mc = AsyncMock()
        mc.post.side_effect = [vllm, neo]
        cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await process_item(
            title="t", text="x", url="http://e/1", source="usgs",
            settings=_make_settings(), **kwargs,
        )
        neo_call = mc.post.call_args_list[1]
    stmts = neo_call.kwargs["json"]["statements"]
    ev_stmt = next(s for s in stmts if "ev:Event" in s["statement"])
    assert "timeline_at: datetime($timeline_at)" in ev_stmt["statement"]
    return ev_stmt["parameters"]


_EV = {
    "title": "x", "summary": "y", "codebook_type": "military.airstrike",
    "severity": "high", "confidence": 0.9,
}


async def test_event_write_includes_timeline_at():
    """A structured occurred_at kwarg is stamped + normalized to tz-aware UTC."""
    params = await _event_params([_EV], occurred_at="2026-05-01T00:00:00Z")
    assert params["timeline_at"] == "2026-05-01T00:00:00+00:00"
    assert params["time_basis"] == "occurred"


async def test_event_write_falls_back_to_ingested_without_structured_time():
    """No structured time + no LLM hint -> time_basis 'ingested', never fabricated."""
    params = await _event_params([_EV])
    assert params["time_basis"] == "ingested"
    assert params["timeline_at"]  # non-empty ISO string


async def test_structured_occurred_beats_llm_timestamp_hint():
    """Both present: the structured kwarg wins over the LLM 'timestamp' hint."""
    params = await _event_params(
        [{**_EV, "timestamp": "2030-01-01T00:00:00Z"}],
        occurred_at="2026-05-01T00:00:00Z",
    )
    assert params["timeline_at"] == "2026-05-01T00:00:00+00:00"
    assert params["time_basis"] == "occurred"


async def test_llm_timestamp_hint_used_when_no_structured_time():
    """Only the LLM hint present: it is used (basis 'occurred')."""
    params = await _event_params([{**_EV, "timestamp": "2026-03-15T12:00:00Z"}])
    assert params["timeline_at"] == "2026-03-15T12:00:00+00:00"
    assert params["time_basis"] == "occurred"


async def test_malformed_llm_timestamp_hint_falls_back_to_ingested_in_write():
    """A garbage LLM hint is dropped at the write level -> ingested fallback."""
    from datetime import datetime

    params = await _event_params([{**_EV, "timestamp": "last tuesday"}])
    assert params["time_basis"] == "ingested"
    # timeline_at must still be a parseable ISO instant (the honest ingest time)
    datetime.fromisoformat(params["timeline_at"])
