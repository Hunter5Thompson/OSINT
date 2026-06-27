"""Tests for the Sonnet canonical-promotion gate (relations_judge).

The gate is a fail-closed precision filter that sits AFTER the deterministic
type-gate: it asks a cloud LLM (Sonnet) whether each canonical-eligible relation
should actually be promoted to the graph. By design:

  * It NEVER imports anthropic — the client is injected (so these tests run in
    the base venv without the optional `notebooklm` extra, and so the gate can
    never make a network call unless a caller hands it a real client).
  * Any transport / parse / refusal / truncation problem -> "abstain" (the
    relation stays a candidate). Fail-closed errors are NOT cached.
  * Only a clean model verdict (approve|reject|abstain) is cached, keyed by
    relation_hash | model_id | rubric_version.
  * The payload sent to the model contains ONLY the relation + endpoint types +
    evidence — never the transcript, notebook id, or provenance.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import nlm_ingest.relations_judge as rj
from nlm_ingest.relation_validator import CanonicalRelation, relation_hash
from nlm_ingest.relations_judge import (
    DEFAULT_JUDGE_MODEL,
    RUBRIC_VERSION,
    build_user_payload,
    cache_key,
    judge_relation,
    rubric_text,
)

# --- fakes -----------------------------------------------------------------

class _FakeMessages:
    def __init__(self, responder):
        self._responder = responder
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responder(kwargs)


class _FakeClient:
    def __init__(self, responder):
        self.messages = _FakeMessages(responder)


def _resp(decision="approve", reason="ok", *, stop_reason="end_turn", text=None,
          thinking_first=False):
    body = text if text is not None else json.dumps({"decision": decision, "reason": reason})
    blocks = []
    if thinking_first:
        blocks.append(SimpleNamespace(type="thinking", thinking="deliberating"))
    blocks.append(SimpleNamespace(type="text", text=body))
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def _responder(*args, **kw):
    """Build a responder callable returning a fixed response (or raising)."""
    def inner(_kwargs):
        return _resp(*args, **kw)
    return inner


def _raiser(exc=None):
    err = exc if exc is not None else RuntimeError("boom")

    def inner(_kwargs):
        raise err
    return inner


def _rel(rel_type="OPERATES", source="Germany", source_type="COUNTRY",
         target="F-35", target_type="AIRCRAFT",
         evidence="Germany operates the F-35 in active service."):
    rh = relation_hash((source, source_type), rel_type, (target, target_type), evidence)
    return CanonicalRelation(
        rel_type=rel_type, source=source, source_type=source_type,
        target=target, target_type=target_type, confidence=0.9, evidence=evidence,
        notebook_id="nb-secret", source_kind="transcript", source_id="src-secret",
        prompt_version="v8", extraction_model="qwen",
        relation_hash=rh, provenance_key="pk-secret", symmetric=False,
    )


# --- cache key -------------------------------------------------------------

def test_cache_key_binds_hash_model_rubric():
    k = cache_key("HASH", "claude-sonnet-4-6", "v1")
    assert k == "HASH|claude-sonnet-4-6|v1"
    assert cache_key("HASH", "m1", "v1") != cache_key("HASH", "m2", "v1")
    assert cache_key("HASH", "m1", "v1") != cache_key("HASH", "m1", "v2")


# --- happy-path verdicts are returned and cached ---------------------------

async def test_approve_returned_and_cached():
    client = _FakeClient(_responder("approve", "evidence clearly supports it"))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "approve"
    assert v.cached is False
    assert v.model_id == DEFAULT_JUDGE_MODEL
    assert v.rubric_version == RUBRIC_VERSION
    key = cache_key(_rel().relation_hash, DEFAULT_JUDGE_MODEL, RUBRIC_VERSION)
    assert cache[key]["decision"] == "approve"


async def test_reject_returned_and_cached():
    client = _FakeClient(_responder("reject", "planned, not in service"))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "reject"
    assert len(cache) == 1


async def test_model_abstain_returned_and_cached():
    client = _FakeClient(_responder("abstain", "ambiguous evidence"))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "abstain"
    assert v.error is None
    assert len(cache) == 1  # a real model abstain IS cached


# --- cache hit short-circuits the API --------------------------------------

async def test_cache_hit_skips_api():
    rel = _rel()
    key = cache_key(rel.relation_hash, DEFAULT_JUDGE_MODEL, RUBRIC_VERSION)
    cache = {key: {"decision": "approve", "reason": "prior"}}
    client = _FakeClient(_raiser())  # would raise if called
    v = await judge_relation(rel, client=client, cache=cache)
    assert v.decision == "approve"
    assert v.cached is True
    assert client.messages.calls == []  # no API call


async def test_different_rubric_version_misses_cache(monkeypatch):
    monkeypatch.setitem(rj._RUBRICS, "v2", "TEST v2 rubric: approve reject abstain")
    rel = _rel()
    key_v1 = cache_key(rel.relation_hash, DEFAULT_JUDGE_MODEL, "v1")
    cache = {key_v1: {"decision": "approve", "reason": "prior"}}
    client = _FakeClient(_responder("reject", "v2 rubric rejects"))
    v = await judge_relation(rel, client=client, cache=cache, rubric_version="v2")
    assert v.decision == "reject"  # did NOT reuse the v1 cache entry
    assert client.messages.calls  # made a fresh call


async def test_unknown_rubric_raises_loudly():
    # An unknown rubric is a config/deploy bug, not a per-relation transient
    # error: it must raise, NOT silently fail-closed-abstain every relation.
    client = _FakeClient(_responder("approve"))
    with pytest.raises(KeyError):
        await judge_relation(_rel(), client=client, cache={}, rubric_version="nope")


# --- fail-closed paths: abstain, NOT cached --------------------------------

async def test_transport_error_fail_closed_uncached():
    client = _FakeClient(_raiser(ConnectionError("529 overloaded")))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "abstain"
    assert v.error is not None
    assert cache == {}  # transient failure must NOT poison the cache


async def test_invalid_json_fail_closed_uncached():
    client = _FakeClient(_responder(text="this is not json"))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "abstain"
    assert v.error is not None
    assert cache == {}


async def test_bad_decision_value_fail_closed_uncached():
    client = _FakeClient(_responder(text=json.dumps({"decision": "maybe", "reason": "x"})))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "abstain"
    assert cache == {}


async def test_refusal_stop_reason_fail_closed_uncached():
    client = _FakeClient(_responder("approve", stop_reason="refusal"))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "abstain"
    assert cache == {}


async def test_max_tokens_truncation_fail_closed_uncached():
    # Truncated JSON + max_tokens stop -> fail-closed, uncached.
    client = _FakeClient(_responder(stop_reason="max_tokens", text='{"decision": "appr'))
    cache: dict = {}
    v = await judge_relation(_rel(), client=client, cache=cache)
    assert v.decision == "abstain"
    assert cache == {}


# --- response parsing skips thinking blocks --------------------------------

async def test_thinking_block_is_skipped():
    client = _FakeClient(_responder("approve", thinking_first=True))
    v = await judge_relation(_rel(), client=client, cache={})
    assert v.decision == "approve"


# --- payload minimality + security framing ---------------------------------

async def test_payload_contains_only_relation_types_evidence():
    rel = _rel()
    client = _FakeClient(_responder("approve"))
    await judge_relation(rel, client=client, cache={})
    kwargs = client.messages.calls[0]
    content = kwargs["messages"][0]["content"]
    # present: the four typed fields + evidence
    assert rel.rel_type in content
    assert rel.source in content and rel.source_type in content
    assert rel.target in content and rel.target_type in content
    assert rel.evidence in content
    # absent: provenance / transcript identifiers must never leave the box
    assert "nb-secret" not in content
    assert "src-secret" not in content
    assert "pk-secret" not in content


async def test_no_tools_are_offered_to_the_judge():
    client = _FakeClient(_responder("approve"))
    await judge_relation(_rel(), client=client, cache={})
    kwargs = client.messages.calls[0]
    assert not kwargs.get("tools")  # the judge has no tools / no web search


async def test_evidence_is_framed_as_untrusted():
    payload = build_user_payload(_rel())
    low = payload.lower()
    assert "untrusted" in low or "not as instructions" in low or "data" in low
    assert "<evidence>" in payload and "</evidence>" in payload


async def test_structured_output_format_is_requested():
    client = _FakeClient(_responder("approve"))
    await judge_relation(_rel(), client=client, cache={})
    kwargs = client.messages.calls[0]
    fmt = kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    enum = fmt["schema"]["properties"]["decision"]["enum"]
    assert set(enum) == {"approve", "reject", "abstain"}


def test_rubric_text_is_stable_and_nonempty():
    t = rubric_text("v1")
    assert isinstance(t, str) and len(t) > 200
    # the rubric must name the three decisions and the abstain-on-doubt rule
    for token in ("approve", "reject", "abstain"):
        assert token in t
