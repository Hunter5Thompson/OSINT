from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import get_args

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from nlm_ingest.schemas import (
    Claim,
    ClaimPolarity,
    ClaimType,
    Entity,
    EntityType,
    Extraction,
    ExtractionSource,
    Relation,
)

log = structlog.get_logger()

CLAUDE_BUDGET_PER_RUN = 50_000
PROMPT_DIR = Path(__file__).parent / "prompts"

# JSON Schema for vLLM `response_format` (strict guided decoding). Enums are derived
# from the schema Literals so they never drift from schemas.py. DESIGN: entity `type`
# and claim `type`/`polarity` ARE enum-constrained (we trust those taxonomies — this
# stops the model emitting e.g. EVENT entities). Relation `type` is deliberately a free
# string (NOT enum): the 9 RelationTypes are intentionally narrow, so we let the model
# emit naturally and observe out-of-enum values via the lenient skip-logger below,
# feeding a future curated relation-type expansion. See docs/nlm-smoke-2026-06-19.md.
_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": list(get_args(EntityType))},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "type", "aliases", "confidence"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "type": {"type": "string"},  # free string by design (see note above)
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["source", "target", "type", "evidence", "confidence"],
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "statement": {"type": "string"},
                    "type": {"type": "string", "enum": list(get_args(ClaimType))},
                    "polarity": {"type": "string", "enum": list(get_args(ClaimPolarity))},
                    "entities_involved": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "temporal_scope": {"type": "string"},
                },
                "required": [
                    "statement", "type", "polarity",
                    "entities_involved", "confidence", "temporal_scope",
                ],
            },
        },
    },
    "required": ["entities", "relations", "claims"],
}


def _build_items(
    cls: type[BaseModel], raws: list, *, kind: str, notebook_id: str
) -> list:
    """Build pydantic items leniently: skip+log any item that fails validation rather
    than letting one bad item (e.g. an out-of-enum type) kill the whole notebook.

    Logs each skipped item AND a per-kind summary Counter of the offending `type`
    values — that summary is the signal for a future curated taxonomy expansion
    (esp. relation types, which are intentionally not schema-enforced).

    For entities/claims this is a FALLBACK (the strict response schema is the primary
    guard against out-of-enum types); for relations it is the PRIMARY mechanism, since
    relation `type` is deliberately not schema-constrained. Also coerces a non-list
    `raws` (model emitting ``"entities": null``) to ``[]`` so one malformed array can
    never crash the whole notebook — the entire point of this lenient layer."""
    if not isinstance(raws, list):
        # Telemetry: a non-list array (e.g. model emitted ``"entities": null``) is coerced
        # to [] so it can't crash the notebook — but log it so full-run quality regressions
        # (a model/server starting to emit malformed arrays) stay visible.
        log.warning(
            "nlm_extract_nonlist_array", kind=kind, notebook_id=notebook_id,
            got_type=type(raws).__name__,
        )
        raws = []
    out: list = []
    skipped_types: list[str] = []
    for raw in raws:
        try:
            out.append(cls(**raw))
        except (ValidationError, TypeError) as e:
            bad_type = raw.get("type") if isinstance(raw, dict) else "<non-dict>"
            skipped_types.append(str(bad_type))
            log.warning(
                "nlm_extract_item_skipped",
                kind=kind, notebook_id=notebook_id, bad_type=bad_type,
                error=str(e).splitlines()[0], raw=raw,
            )
    if skipped_types:
        log.info(
            "nlm_extract_skipped_summary",
            kind=kind, notebook_id=notebook_id,
            skipped=len(skipped_types), kept=len(out),
            skipped_types=dict(Counter(skipped_types)),
        )
    return out


def load_prompt(version: str) -> str:
    path = PROMPT_DIR / f"extraction_{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text()


def extract_context(full_text: str, target: str, radius: int = 500) -> str:
    idx = full_text.find(target)
    if idx == -1:
        return full_text[: radius * 2]
    start = max(0, idx - radius)
    end = min(len(full_text), idx + len(target) + radius)
    return full_text[start:end]


async def extract_with_qwen(
    source: ExtractionSource,
    metadata: dict,
    client: httpx.AsyncClient,
    vllm_url: str,
    vllm_model: str,
    # Default is "v4": adds OPERATES (platform-operation relation, distinct from the
    # locative OPERATES_IN) and tightens OPERATES_IN/COMMANDS/TARGETS/ALLIED_WITH
    # guidance to reduce systematic taxonomy errors. v3 was source-agnostic with a
    # dynamic source-kind hint; v4 inherits all of that. v1/v2/v3 remain available
    # for rollback. See docs/superpowers/specs/2026-06-20-relation-v2-design.md §7.
    prompt_version: str = "v4",
    # Per-request HTTP timeout. Defaults high because the Spark (35B MoE) is shared
    # with the live RSS pipeline; a single extraction measured ~160s under load, so
    # the old hardcoded 120s caused ReadTimeouts. The CLI passes
    # settings.nlm_ingestion_vllm_timeout (NLM-specific; RSS keeps its own 120s).
    timeout: float = 600.0,
    # Output token budget. 8000 (not 4000): long transcripts produced JSON that
    # truncated mid-string at 4000 -> parse failure. Callers pass
    # settings.ingestion_max_tokens.
    max_tokens: int = 8000,
) -> Extraction:
    prompt_template = load_prompt(prompt_version)
    # Dynamic hint so the model knows what kind of source it is reading.
    source_hint = (
        "The following source is a podcast transcript."
        if source.source_kind == "transcript"
        else "The following source is a written research report."
    )
    body = source.text[:16_000]
    # Use explicit replacement instead of str.format() — the prompt contains
    # JSON example blocks with bare braces that would cause KeyError. Replace both
    # the v3 placeholder ({source_text}) and the legacy v1/v2 one ({transcript_text})
    # so old prompt versions stay backward-compatible.
    prompt = (
        prompt_template
        .replace("{source_name}", metadata.get("source_name", "unknown"))
        .replace("{title}", metadata.get("title", "untitled"))
        .replace("{source_hint}", source_hint)
        .replace("{source_text}", body)
        .replace("{transcript_text}", body)
    )

    payload = {
        "model": vllm_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        # Strict guided decoding: forces valid JSON + valid entity/claim enum values
        # (kills out-of-enum entity types like EVENT at the source). Relation `type`
        # stays a free string by design (see _RESPONSE_SCHEMA note).
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "nlm_extraction",
                "schema": _RESPONSE_SCHEMA,
                "strict": True,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }

    response = await client.post(
        f"{vllm_url}/v1/chat/completions",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(content)

    nid = source.notebook_id
    return Extraction(
        notebook_id=nid,
        entities=_build_items(Entity, data.get("entities", []), kind="entity", notebook_id=nid),
        relations=_build_items(
            Relation, data.get("relations", []), kind="relation", notebook_id=nid
        ),
        claims=_build_items(Claim, data.get("claims", []), kind="claim", notebook_id=nid),
        extraction_model=vllm_model,
        prompt_version=prompt_version,
        source_kind=source.source_kind,
        source_id=source.source_id,
    )


async def review_with_claude(
    extraction: Extraction,
    source: ExtractionSource,
    claude_client,
    claude_model: str,
) -> Extraction:
    low_conf_claims = [c for c in extraction.claims if c.confidence < 0.7]
    if not low_conf_claims:
        log.info("claude_review_skip", reason="no low-confidence claims")
        return extraction

    token_budget = CLAUDE_BUDGET_PER_RUN
    reviewed_count = 0

    for claim in low_conf_claims:
        context_window = extract_context(
            source.text, claim.statement[:80], radius=500
        )
        # Estimate input tokens (context // 4) plus the 200-token response budget.
        estimated_tokens = len(context_window) // 4 + 200
        if token_budget < estimated_tokens:
            log.info("claude_budget_exhausted", reviewed=reviewed_count)
            break
        token_budget -= estimated_tokens

        try:
            message = await claude_client.messages.create(
                model=claude_model,
                max_tokens=200,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Verify this claim extracted from a think-tank source.\n\n"
                            f"Claim: \"{claim.statement}\"\n"
                            f"Type: {claim.type} | Polarity: {claim.polarity}\n\n"
                            f"Transcript context:\n{context_window}\n\n"
                            f'Return JSON: {{"verdict": "confirmed|rejected|modified",'
                            f' "confidence": 0.0-1.0}}'
                        ),
                    }
                ],
            )
            result = json.loads(message.content[0].text)
            if result.get("verdict") == "rejected":
                claim.confidence = 0.0
            else:
                claim.confidence = result.get("confidence", claim.confidence)
            reviewed_count += 1
        except Exception:
            log.warning("claude_review_failed", claim=claim.statement[:50])
            continue

    log.info("claude_review_done", reviewed=reviewed_count, budget_remaining=token_budget)
    return extraction
