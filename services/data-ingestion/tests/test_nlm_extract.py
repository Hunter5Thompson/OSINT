import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nlm_ingest.extract import (
    extract_context,
    extract_with_qwen,
    load_prompt,
    review_with_claude,
)
from nlm_ingest.schemas import (
    CANONICAL_ENTITY_TYPES,
    Extraction,
    ExtractionSource,
)


def _make_source(text: str = "NATO expanded eastward. China opposes this.") -> ExtractionSource:
    return ExtractionSource(
        notebook_id="nb1",
        source_id="transcript",
        source_kind="transcript",
        text=text,
    )


_QWEN_RESPONSE = {
    "entities": [
        {"name": "NATO", "type": "ORGANIZATION", "aliases": [], "confidence": 0.95},
        {"name": "China", "type": "COUNTRY", "aliases": ["PRC"], "confidence": 0.9},
    ],
    "relations": [
        {
            "source": "China", "target": "NATO", "type": "COMPETES_WITH",
            "evidence": "China opposes this", "confidence": 0.75,
        },
    ],
    "claims": [
        {
            "statement": "NATO expanded eastward",
            "type": "factual", "polarity": "neutral",
            "entities_involved": ["NATO"],
            "confidence": 0.95, "temporal_scope": "ongoing",
        },
        {
            "statement": "China opposes NATO expansion",
            "type": "assessment", "polarity": "negative",
            "entities_involved": ["China", "NATO"],
            "confidence": 0.6, "temporal_scope": "ongoing",
        },
    ],
}


class TestLoadPrompt:
    def test_loads_v1(self):
        prompt = load_prompt("v1")
        assert "{source_name}" in prompt
        assert "{transcript_text}" in prompt

    def test_missing_version_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("v999")

    def test_v4_prompt_loads_and_mentions_operates(self):
        p = load_prompt("v4")
        # OPERATES must appear as a standalone token (not just as a prefix of OPERATES_IN)
        assert "OPERATES |" in p or "OPERATES " in p
        assert "OPERATES_IN" in p  # both present; OPERATES is the new platform-operation relation

    def test_v5_prompt_tightens_operates_and_commands_precision(self):
        p = load_prompt("v5")
        assert "manufacturer" in p.lower()
        assert "Lockheed Martin" in p
        assert "SUPPLIES_TO" in p
        assert "company, university, lab, or think tank" in p
        assert "Do NOT use COMMANDS" in p

    def test_v6_prompt_tightens_supplies_to_direction_and_competes(self):
        p = load_prompt("v6")
        # SUPPLIES_TO direction: vendor->customer, not reversed
        assert "direction is critical" in p.lower()
        assert "REVERSE" in p
        # acquisition is not SUPPLIES_TO
        assert "ACQUISITION" in p and "is NOT SUPPLIES_TO" in p
        # COMPETES_WITH excludes formal allies
        assert "Formal allies are NOT competitors" in p

    def test_v7_prompt_tightens_commands_operates_evidence(self):
        p = load_prompt("v7")
        # COMMANDS: rank/authorship/membership is not command
        assert "explicit operational command" in p.lower()
        assert "is NOT command" in p
        # OPERATES operator must be COUNTRY/MILITARY_UNIT (not an organization)
        assert "operator must be a COUNTRY or a MILITARY_UNIT" in p
        # OPERATES_IN must be evidence-backed (foreign-ops unit not home country)
        assert "Quds Force" in p and "foreign" in p.lower()

    def test_v8_prompt_excludes_planned_partnership_interview_capability(self):
        p = load_prompt("v8")
        # planned/ordered/in-development is not OPERATES
        assert "IN ACTIVE SERVICE" in p
        assert "Main Ground Combat System" in p and "Gripen" in p
        # business partnership is not ALLIED_WITH
        assert "Hadion" in p and "is NOT an alliance" in p
        # interview is not NEGOTIATES_WITH; MEMBER_OF needs documented affiliation
        assert "Der Standard" in p
        assert "do NOT emit `Luftwaffe —MEMBER_OF→ NATO`" in p


class TestExtractWithQwen:
    @pytest.mark.asyncio
    async def test_returns_extraction(self):
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(_QWEN_RESPONSE)}}
                ]
            },
            request=httpx.Request("POST", "http://localhost:8000/v1/chat/completions"),
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        extraction = await extract_with_qwen(
            source=_make_source(),
            metadata={"source_name": "RAND", "title": "Test Report"},
            client=client,
            vllm_url="http://localhost:8000",
            vllm_model="qwen3.5",
        )
        assert extraction.notebook_id == "nb1"
        assert len(extraction.entities) == 2
        assert len(extraction.claims) == 2
        assert extraction.extraction_model == "qwen3.5"
        assert extraction.prompt_version == "v8"  # v8 is the default

    @pytest.mark.asyncio
    async def test_vllm_error_raises(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        err_req = httpx.Request("POST", "http://x")
        client.post.side_effect = httpx.HTTPStatusError(
            "500", request=err_req, response=httpx.Response(500, request=err_req)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await extract_with_qwen(
                source=_make_source(),
                metadata={"source_name": "X", "title": "Y"},
                client=client,
                vllm_url="http://localhost:8000",
                vllm_model="qwen3.5",
            )


class TestExtractContext:
    def test_extracts_window(self):
        text = "A " * 500 + "TARGET " + "B " * 500
        window = extract_context(text, "TARGET", radius=50)
        assert "TARGET" in window
        assert len(window) < len(text)

    def test_short_text_returns_all(self):
        text = "short text"
        window = extract_context(text, "short", radius=500)
        assert window == text


class TestReviewWithClaude:
    @pytest.mark.asyncio
    async def test_upgrades_low_confidence(self):
        extraction = Extraction(
            notebook_id="nb1",
            entities=[],
            relations=[],
            claims=[
                {
                    "statement": "China opposes NATO expansion",
                    "type": "assessment", "polarity": "negative",
                    "entities_involved": ["China", "NATO"],
                    "confidence": 0.6, "temporal_scope": "ongoing",
                },
            ],
            extraction_model="qwen3.5",
            prompt_version="v1",
            source_kind="transcript",
            source_id="transcript",
        )
        source = _make_source()

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.85}')]
        mock_client.messages.create.return_value = mock_message

        reviewed = await review_with_claude(
            extraction=extraction,
            source=source,
            claude_client=mock_client,
            claude_model="claude-sonnet-4-20250514",
        )
        assert reviewed.claims[0].confidence == 0.85

    @pytest.mark.asyncio
    async def test_respects_budget(self):
        claims = [
            {
                "statement": f"Claim number {i} about geopolitics",
                "type": "assessment", "polarity": "neutral",
                "entities_involved": [], "confidence": 0.5,
                "temporal_scope": "ongoing",
            }
            for i in range(200)
        ]
        extraction = Extraction(
            notebook_id="nb1", entities=[], relations=[],
            claims=claims, extraction_model="qwen3.5", prompt_version="v1",
            source_kind="transcript", source_id="transcript",
        )
        source = _make_source("word " * 40_000)

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.8}')]
        mock_client.messages.create.return_value = mock_message

        await review_with_claude(
            extraction=extraction,
            source=source,
            claude_client=mock_client,
            claude_model="claude-sonnet-4-20250514",
        )
        call_count = mock_client.messages.create.call_count
        assert call_count < 200


_REQ = httpx.Request("POST", "http://x/v1/chat/completions")


@pytest.mark.asyncio
async def test_extract_with_qwen_sets_provenance():
    content = '{"entities": [], "relations": [], "claims": []}'
    body = {"choices": [{"message": {"content": content}}]}
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(200, json=body, request=_REQ)

    source = ExtractionSource(
        notebook_id="nb1", source_id="rep-a", source_kind="report", text="report text"
    )
    result = await extract_with_qwen(
        source=source,
        metadata={"source_name": "RAND", "title": "T"},
        client=client,
        vllm_url="http://x",
        vllm_model="qwen",
    )
    assert result.source_kind == "report"
    assert result.source_id == "rep-a"
    assert result.notebook_id == "nb1"


def _sent_prompt(client) -> str:
    """The user-message content of the chat-completions payload the client received."""
    return client.post.call_args.kwargs["json"]["messages"][0]["content"]


def _ok_client():
    empty = '{"entities": [], "relations": [], "claims": []}'
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(
        200, json={"choices": [{"message": {"content": empty}}]}, request=_REQ)
    return client


class TestPromptV3:
    def test_v3_loads_and_is_source_agnostic(self):
        prompt = load_prompt("v3")
        assert "{source_name}" in prompt
        assert "{source_text}" in prompt          # honest, source-agnostic placeholder
        assert "{source_hint}" in prompt           # dynamic source-kind hint slot
        assert "{transcript_text}" not in prompt   # old placeholder retired in v3
        # LOCATION is a canonical EntityType in schemas.py (13 values) — must appear in prompt
        assert "LOCATION" in prompt
        # Hard enforcement: EVENT must be explicitly called out as forbidden
        assert "EVENT" in prompt
        # Events-are-not-entities rule must be present
        assert "events" in prompt.lower() and "claims" in prompt.lower()

    def test_v3_entity_types_match_schema_exactly(self):
        """Prompt entity type list must match CANONICAL_ENTITY_TYPES in schemas.py exactly.

        Extracts the pipe-delimited type string from the prompt's Output Format block
        and asserts it is an exact set-match against the Literal values in schemas.py.
        This test fails if a type is added to schemas.py but not the prompt, or vice versa.
        """
        import re
        prompt = load_prompt("v3")
        # Extract the type enum line from the JSON template block
        match = re.search(r'"type":\s*"([^"]+)"', prompt)
        assert match, "Could not find entity type enum line in v3 prompt"
        type_line = match.group(1)
        prompt_types = {t.strip() for t in type_line.split("|")}
        assert prompt_types == set(CANONICAL_ENTITY_TYPES), (
            f"Prompt entity types do not match schemas.py EntityType Literal.\n"
            f"  In prompt only:  {prompt_types - set(CANONICAL_ENTITY_TYPES)}\n"
            f"  In schema only:  {set(CANONICAL_ENTITY_TYPES) - prompt_types}"
        )

    @pytest.mark.asyncio
    async def test_v3_still_loads_when_requested_explicitly(self):
        # default is now v5; v3 still loads correctly when requested explicitly
        client = _ok_client()
        result = await extract_with_qwen(
            source=_make_source(), metadata={"source_name": "RAND", "title": "T"},
            client=client, vllm_url="http://x", vllm_model="qwen",
            prompt_version="v3")
        assert result.prompt_version == "v3"

    @pytest.mark.asyncio
    async def test_injects_report_hint_and_text(self):
        client = _ok_client()
        source = ExtractionSource(notebook_id="nb1", source_id="rep-a",
                                  source_kind="report", text="REPORT BODY CONTENT")
        await extract_with_qwen(source=source, metadata={"source_name": "RAND", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen")
        prompt = _sent_prompt(client)
        assert "The following source is a written research report." in prompt
        assert "REPORT BODY CONTENT" in prompt
        for ph in ("{source_text}", "{source_hint}", "{source_name}", "{title}"):
            assert ph not in prompt                # every placeholder resolved

    @pytest.mark.asyncio
    async def test_injects_transcript_hint(self):
        client = _ok_client()
        await extract_with_qwen(source=_make_source(text="PODCAST WORDS"),
                                metadata={"source_name": "RAND", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen")
        prompt = _sent_prompt(client)
        assert "The following source is a podcast transcript." in prompt
        assert "PODCAST WORDS" in prompt

    @pytest.mark.asyncio
    async def test_legacy_v1_still_injects_source_text(self):
        # Backward compat: v1 uses {transcript_text}; source.text must still land in the prompt
        # because extract.py replaces both {source_text} and {transcript_text}.
        client = _ok_client()
        await extract_with_qwen(source=_make_source(text="LEGACY V1 TEXT"),
                                metadata={"source_name": "RAND", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen",
                                prompt_version="v1")
        prompt = _sent_prompt(client)
        assert "LEGACY V1 TEXT" in prompt
        assert "{transcript_text}" not in prompt


def _payload(client) -> dict:
    return client.post.call_args.kwargs["json"]


def _client_returning(content: str):
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}, request=_REQ)
    return client


class TestStructuredOutputAndLenient:
    @pytest.mark.asyncio
    async def test_payload_uses_strict_json_schema(self):
        from nlm_ingest.schemas import CANONICAL_ENTITY_TYPES
        client = _ok_client()
        await extract_with_qwen(source=_make_source(), metadata={"source_name": "R", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen")
        rf = _payload(client)["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["strict"] is True
        props = rf["json_schema"]["schema"]["properties"]
        ent_type = props["entities"]["items"]["properties"]["type"]
        rel_type = props["relations"]["items"]["properties"]["type"]
        claim_type = props["claims"]["items"]["properties"]["type"]
        # entity type enum-enforced and matches the 13 canonical schema types (no drift)
        assert set(ent_type["enum"]) == set(CANONICAL_ENTITY_TYPES)
        # relation type is a FREE string (NOT enum) by design — observe out-of-enum values
        assert "enum" not in rel_type
        # claim type/polarity ARE enum-enforced
        assert claim_type["enum"] == ["factual", "assessment", "prediction"]

    @pytest.mark.asyncio
    async def test_max_tokens_default_is_8000_and_overridable(self):
        client = _ok_client()
        await extract_with_qwen(source=_make_source(), metadata={"source_name": "R", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen")
        assert _payload(client)["max_tokens"] == 8000
        client2 = _ok_client()
        await extract_with_qwen(
            source=_make_source(), metadata={"source_name": "R", "title": "T"},
            client=client2, vllm_url="http://x", vllm_model="qwen", max_tokens=12345)
        assert _payload(client2)["max_tokens"] == 12345

    @pytest.mark.asyncio
    async def test_lenient_skips_out_of_enum_entity_keeps_rest(self):
        content = json.dumps({
            "entities": [
                {"name": "NATO", "type": "ORGANIZATION", "aliases": [], "confidence": 0.9},
                {"name": "Dronevation 2026", "type": "EVENT", "aliases": [], "confidence": 0.9},
            ],
            "relations": [], "claims": [],
        })
        result = await extract_with_qwen(
            source=_make_source(), metadata={"source_name": "R", "title": "T"},
            client=_client_returning(content), vllm_url="http://x", vllm_model="qwen")
        # one bad EVENT item must NOT nuke the notebook — NATO survives, EVENT dropped
        assert [e.name for e in result.entities] == ["NATO"]

    @pytest.mark.asyncio
    async def test_keeps_out_of_enum_relation_type_for_validator(self):
        content = json.dumps({
            "entities": [],
            "relations": [
                {"source": "A", "target": "B", "type": "DEVELOPS",
                 "evidence": "x", "confidence": 0.8},
                {"source": "C", "target": "D", "type": "COMPETES_WITH",
                 "evidence": "y", "confidence": 0.8},
            ],
            "claims": [],
        })
        result = await extract_with_qwen(
            source=_make_source(), metadata={"source_name": "R", "title": "T"},
            client=_client_returning(content), vllm_url="http://x", vllm_model="qwen")
        # spec §8: relation `type` is now a free str (NOT the RelationType Literal), so an
        # out-of-enum type like DEVELOPS must SURVIVE extraction (no longer silently dropped
        # by the lenient builder). The role validator — the type authority now — classifies it
        # downstream as a `relation_type_unknown` candidate. Both relations are kept here.
        assert [r.type for r in result.relations] == ["DEVELOPS", "COMPETES_WITH"]

    @pytest.mark.asyncio
    async def test_null_array_does_not_crash_notebook(self):
        # Model emits "entities": null (not absent) — must NOT raise; coerced to empty.
        content = json.dumps({"entities": None, "relations": None, "claims": None})
        result = await extract_with_qwen(
            source=_make_source(), metadata={"source_name": "R", "title": "T"},
            client=_client_returning(content), vllm_url="http://x", vllm_model="qwen")
        assert result.entities == [] and result.relations == [] and result.claims == []
