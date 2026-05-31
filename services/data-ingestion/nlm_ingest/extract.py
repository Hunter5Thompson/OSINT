from __future__ import annotations

import json
from pathlib import Path

import httpx
import structlog

from nlm_ingest.schemas import (
    Claim,
    Entity,
    Extraction,
    ExtractionSource,
    Relation,
)

log = structlog.get_logger()

CLAUDE_BUDGET_PER_RUN = 50_000
PROMPT_DIR = Path(__file__).parent / "prompts"


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
    # Default is "v3": source-agnostic prompt with a dynamic source-kind hint, so
    # report sources are no longer mislabeled as podcast transcripts. v3 is derived
    # from v1 semantics (it does NOT include v2's opt-in LOCATION entity type).
    # v1/v2 remain available for rollback / explicit opt-in (e.g. prompt_version="v2"
    # still pairs with the default-OFF `entity_type_normalize` flag). See
    # docs/superpowers/plans/2026-04-30-patch-c-entity-canonicalization.md
    prompt_version: str = "v3",
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
        "max_tokens": 4000,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    response = await client.post(
        f"{vllm_url}/v1/chat/completions",
        json=payload,
        timeout=120.0,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(content)

    return Extraction(
        notebook_id=source.notebook_id,
        entities=[Entity(**e) for e in data.get("entities", [])],
        relations=[Relation(**r) for r in data.get("relations", [])],
        claims=[Claim(**c) for c in data.get("claims", [])],
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
